"""Cross-check announcement clauses against a bidder's response table."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .fetch import FetchError, Fetcher
from .models import (
    Announcement,
    AnnouncementRef,
    Clause,
    FetchIssue,
    InvalidCorrection,
    ResponseRow,
)
from .parsing import (
    normalize_clause_no,
    normalize_identifier,
    parse_announcement_detail,
    parse_announcement_list,
    parse_response,
    parse_version_number,
    same_url_scope,
    text_of,
)

MAX_LIST_PAGES = 50
DEFAULT_SAMPLES_ROOT = Path(__file__).resolve().parent.parent / "samples"


@dataclass
class CheckInputs:
    announcement_list_url: str
    project_no: str
    lot_no: str
    response_url: str


def _natural_key(value: str) -> tuple:
    parts = re.split(r"(\d+)", str(value).casefold())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)


def _matching_ref(ref: AnnouncementRef, project_no: str, lot_no: str) -> bool:
    if not ref.project_no:
        return False
    if normalize_identifier(ref.project_no) != normalize_identifier(project_no):
        return False
    if lot_no and ref.lot_no and normalize_identifier(ref.lot_no) != normalize_identifier(lot_no):
        return False
    return True


def _announcement_sort_key(ann: Announcement) -> tuple:
    return (
        0 if not ann.is_correction else 1,
        parse_version_number(ann.ref.version),
        ann.ref.published_at or "",
        ann.ref.order,
    )


def _issue(issues: list[FetchIssue], scope: str, url: str, message: str) -> None:
    issues.append(FetchIssue(scope=scope, url=url, message=message))


def _crawl_announcement_chain(inputs: CheckInputs, fetcher: Fetcher):
    """Breadth-first crawl of list pages; returns refs and completeness."""
    refs: list[AnnouncementRef] = []
    issues: list[FetchIssue] = []
    pages: list[dict[str, Any]] = []
    chain_complete = True

    seen_pages: set[str] = set()
    queue = [inputs.announcement_list_url]
    seen_refs: set[tuple[str, ...]] = set()
    order = 0

    while queue:
        url = queue.pop(0)
        if url in seen_pages:
            continue
        if len(seen_pages) >= MAX_LIST_PAGES:
            chain_complete = False
            _issue(issues, "pagination", url,
                   f"公告分页超过 {MAX_LIST_PAGES} 页上限，可能仍有遗漏")
            break
        seen_pages.add(url)

        try:
            fetched = fetcher.fetch(url)
        except FetchError as exc:
            chain_complete = False
            scope = "list" if url == inputs.announcement_list_url and not pages else "pagination"
            _issue(issues, scope, url, str(exc))
            if url == inputs.announcement_list_url:
                break
            continue

        try:
            parsed = parse_announcement_list(fetched.text, fetched.final_url or url)
        except Exception as exc:  # defensive: malformed HTML should not crash the check
            chain_complete = False
            scope = "list" if url == inputs.announcement_list_url and not pages else "pagination"
            _issue(issues, scope, url, f"公告列表解析失败：{exc.__class__.__name__}")
            continue

        pages.append({
            "url": url,
            "announcement_count": len(parsed.refs),
            "next_links": list(parsed.next_links),
        })
        for message in parsed.issues:
            chain_complete = False
            _issue(issues, "list", url, message)

        if not parsed.recognized and not parsed.refs and url == inputs.announcement_list_url:
            # parse_announcement_list already reports this; keep the report explicit.
            chain_complete = False

        for ref in parsed.refs:
            ref.order = order
            order += 1
            key = (
                normalize_identifier(ref.project_no),
                normalize_identifier(ref.lot_no),
                ref.kind,
                text_of(ref.version).casefold(),
                ref.url,
            )
            if key in seen_refs:
                continue
            seen_refs.add(key)
            refs.append(ref)

        for next_link in parsed.next_links:
            if not same_url_scope(inputs.announcement_list_url, next_link):
                _issue(issues, "pagination", next_link,
                       "分页链接指向其它站点/样例集，未继续抓取")
                chain_complete = False
                continue
            if next_link not in seen_pages:
                queue.append(next_link)

    return refs, pages, issues, chain_complete


def _fetch_announcements(refs: list[AnnouncementRef], fetcher: Fetcher):
    announcements: list[Announcement] = []
    issues: list[FetchIssue] = []
    complete = True

    for ref in refs:
        if not ref.url:
            complete = False
            _issue(issues, "announcement", "", f"公告「{ref.title or ref.project_no}」缺少详情链接")
            announcements.append(Announcement(ref=ref, fetched=False, error="缺少详情链接"))
            continue
        try:
            fetched = fetcher.fetch(ref.url)
        except FetchError as exc:
            complete = False
            _issue(issues, "announcement", ref.url, str(exc))
            announcements.append(Announcement(ref=ref, fetched=False, error=str(exc)))
            continue
        try:
            announcement, parse_issues = parse_announcement_detail(
                fetched.text, fetched.final_url or ref.url, ref
            )
        except Exception as exc:
            complete = False
            _issue(issues, "announcement", ref.url, f"公告详情解析失败：{exc.__class__.__name__}")
            announcements.append(Announcement(ref=ref, fetched=False, error="解析失败"))
            continue
        for message in parse_issues:
            complete = False
            _issue(issues, "announcement", ref.url, message)
        if not announcement.clauses:
            complete = False
        announcements.append(announcement)

    # A correction with no version and no date cannot be ordered reliably.
    for announcement in announcements:
        if announcement.is_correction and not announcement.ref.version and not announcement.ref.published_at:
            complete = False
            _issue(issues, "announcement", announcement.ref.url,
                   "更正公告缺少版本与发布日期，无法确定更正顺序")

    return announcements, issues, complete


def _apply_corrections(announcements: list[Announcement]):
    """Apply only corrections that explicitly reference an existing clause."""
    originals = [a for a in announcements if not a.is_correction]
    corrections = sorted(
        [a for a in announcements if a.is_correction],
        key=lambda a: (parse_version_number(a.ref.version), a.ref.published_at or "", a.ref.order),
    )

    state: dict[str, Clause] = {}
    history: dict[str, list[Clause]] = {}
    invalid: list[InvalidCorrection] = []
    warnings: list[str] = []

    for announcement in originals:
        for clause in announcement.clauses:
            key = normalize_clause_no(clause.number)
            if not key:
                continue
            if key in state:
                warnings.append(
                    f"原公告中条款 {key} 重复出现（{announcement.ref.url}），已保留首次出现的版本"
                )
                continue
            state[key] = clause
            history[key] = [clause]

    for announcement in corrections:
        for clause in announcement.clauses:
            references = list(clause.references)
            if not references:
                invalid.append(InvalidCorrection(
                    clause_no=clause.number,
                    references=[],
                    reason="更正条款未明确引用任何现有条款",
                    announcement_url=announcement.ref.url,
                    announcement_title=announcement.ref.title,
                    version=clause.version or announcement.ref.version,
                    source_url=announcement.ref.url,
                    published_at=announcement.ref.published_at,
                ))
                continue
            for reference in references:
                target = normalize_clause_no(reference)
                if target not in state:
                    invalid.append(InvalidCorrection(
                        clause_no=clause.number,
                        references=[reference],
                        reason=f"引用的条款 {target} 不存在，更正未被采用",
                        announcement_url=announcement.ref.url,
                        announcement_title=announcement.ref.title,
                        version=clause.version or announcement.ref.version,
                        source_url=announcement.ref.url,
                        published_at=announcement.ref.published_at,
                    ))
                    continue
                replacement = Clause(
                    number=target,
                    version=clause.version or announcement.ref.version,
                    mandatory=clause.mandatory,
                    references=list(clause.references),
                    content=clause.content,
                    source_url=announcement.ref.url,
                    announcement_title=announcement.ref.title,
                    announcement_kind="correction",
                    published_at=announcement.ref.published_at,
                    order=clause.order,
                )
                history.setdefault(target, []).append(replacement)
                state[target] = replacement

    return state, history, invalid, warnings, originals, corrections


def _build_clause_result(
    clause: Clause,
    history: list[Clause],
    responses: list[ResponseRow],
    *,
    chain_complete: bool,
    response_complete: bool,
    response_url: str = "",
) -> dict[str, Any]:
    if not chain_complete or not response_complete:
        status = "pending_verification"
    elif len(responses) > 1:
        status = "duplicate"
    elif not responses:
        status = "missing"
    elif not text_of(responses[0].answer):
        status = "missing"
    else:
        status = "covered"

    notes: list[str] = []
    if not chain_complete:
        notes.append("公告链抓取不完整，无法确认该条款的当前版本；旧版本未被当作当前要求")
    if not response_complete:
        notes.append("响应页抓取不完整，无法确认该条款是否已覆盖")
    if status == "duplicate":
        notes.append(f"响应表中同一条款出现 {len(responses)} 次，无法确定以哪一条为准")
    if status == "missing" and responses and not text_of(responses[0].answer):
        notes.append("响应表存在该条款，但答复为空")
    if status == "covered":
        notes.append("响应表已覆盖该当前强制条款")

    superseded = [
        {
            **old.to_dict(),
            "status": "superseded",
            "status_label": "已被后续版本替换，不作为当前要求",
        }
        for old in history
        if old is not clause
    ]

    source_entries: list[dict[str, Any]] = [{
        "type": "announcement",
        "role": "current" if chain_complete else "unverified",
        "source_url": clause.source_url,
        "version": clause.version,
        "kind": clause.announcement_kind,
        "title": clause.announcement_title,
        "published_at": clause.published_at,
        "mandatory": clause.mandatory,
    }]
    source_entries.extend(
        {
            "type": "announcement",
            "role": "superseded",
            "source_url": old.source_url,
            "version": old.version,
            "kind": old.announcement_kind,
            "title": old.announcement_title,
            "published_at": old.published_at,
            "mandatory": old.mandatory,
        }
        for old in history
        if old is not clause
    )
    source_entries.extend(
        {
            "type": "response",
            "role": "response",
            "source_url": row.source_url,
            "row_index": row.row_index,
            "answer": row.answer,
        }
        for row in responses
    )
    if not responses and response_complete:
        source_entries.append({
            "type": "response",
            "role": "missing",
            "source_url": response_url,
            "row_index": None,
            "answer": "响应表中没有该条款的答复行",
        })

    return {
        "clause_no": clause.number,
        "version": clause.version,
        "mandatory": clause.mandatory,
        "content": clause.content,
        "references": list(clause.references),
        "status": status,
        "status_label": {
            "covered": "已覆盖",
            "missing": "缺项",
            "duplicate": "重复编号",
            "pending_verification": "待核实",
        }[status],
        "notes": notes,
        "response": [row.to_dict() for row in responses],
        "superseded": superseded,
        "sources": source_entries,
    }


def _duplicate_responses(rows: list[ResponseRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ResponseRow]] = {}
    for row in rows:
        grouped.setdefault(normalize_clause_no(row.number), []).append(row)
    duplicates = []
    for number, entries in sorted(grouped.items(), key=lambda item: _natural_key(item[0])):
        if len(entries) > 1:
            duplicates.append({
                "clause_no": number,
                "count": len(entries),
                "rows": [row.to_dict() for row in entries],
                "source_url": entries[0].source_url,
            })
    return duplicates


def run_check(
    announcement_list_url: str,
    project_no: str,
    lot_no: str,
    response_url: str,
    *,
    fetcher: Optional[Fetcher] = None,
    samples_root: str | Path | None = None,
) -> dict[str, Any]:
    inputs = CheckInputs(
        announcement_list_url=(announcement_list_url or "").strip(),
        project_no=(project_no or "").strip(),
        lot_no=(lot_no or "").strip(),
        response_url=(response_url or "").strip(),
    )
    missing_inputs = [
        label for label, value in (
            ("公告列表 URL", inputs.announcement_list_url),
            ("项目编号", inputs.project_no),
            ("标段号", inputs.lot_no),
            ("企业响应表 URL", inputs.response_url),
        ) if not value
    ]
    if missing_inputs:
        raise ValueError("缺少必填项：" + "、".join(missing_inputs))

    if fetcher is None:
        fetcher = Fetcher(samples_root=samples_root or DEFAULT_SAMPLES_ROOT)

    issues: list[FetchIssue] = []

    # 1) Crawl all announcement list pages (original + corrections).
    refs, pages, crawl_issues, chain_complete = _crawl_announcement_chain(inputs, fetcher)
    issues.extend(crawl_issues)

    # 2) Keep only the requested project/lot.
    matching_refs = [ref for ref in refs if _matching_ref(ref, inputs.project_no, inputs.lot_no)]
    if not matching_refs:
        chain_complete = False
        _issue(issues, "list", inputs.announcement_list_url,
               f"未找到项目编号「{inputs.project_no}」、标段号「{inputs.lot_no}」匹配的公告")

    # 3) Read each announcement detail; any failure leaves the chain incomplete.
    announcements, detail_issues, details_complete = _fetch_announcements(matching_refs, fetcher)
    issues.extend(detail_issues)
    chain_complete = chain_complete and details_complete

    originals = [a for a in announcements if not a.is_correction]
    if not any(originals):
        chain_complete = False
        _issue(issues, "announcement", inputs.announcement_list_url,
               "未找到匹配的原公告，无法建立条款基线")

    # 4) Build the effective clause set.  A correction is only applied when it
    #    explicitly references an existing clause number.
    state, history, invalid, warnings, originals, corrections = _apply_corrections(announcements)
    for warning in warnings:
        _issue(issues, "announcement", inputs.announcement_list_url, warning)

    # 5) Read the bidder's response table.
    response_rows: list[ResponseRow] = []
    response_complete = True
    try:
        fetched_response = fetcher.fetch(inputs.response_url)
        response_page = parse_response(fetched_response.text, fetched_response.final_url or inputs.response_url)
        response_rows = response_page.rows
        if response_page.issues:
            response_complete = False
            for message in response_page.issues:
                _issue(issues, "response", inputs.response_url, message)
        if not response_page.recognized:
            response_complete = False
    except FetchError as exc:
        response_complete = False
        _issue(issues, "response", inputs.response_url, str(exc))
    except Exception as exc:
        response_complete = False
        _issue(issues, "response", inputs.response_url, f"响应表解析失败：{exc.__class__.__name__}")

    responses_by_no: dict[str, list[ResponseRow]] = {}
    for row in response_rows:
        responses_by_no.setdefault(normalize_clause_no(row.number), []).append(row)

    # 6) Only current mandatory clauses are requirements.  Superseded versions
    #    are shown separately and never counted as current requirements.
    current_required = [
        state[key] for key in sorted(state, key=_natural_key) if state[key].mandatory
    ]
    current_optional = [
        state[key] for key in sorted(state, key=_natural_key) if not state[key].mandatory
    ]

    clause_results = [
        _build_clause_result(
            clause,
            history.get(normalize_clause_no(clause.number), [clause]),
            responses_by_no.get(normalize_clause_no(clause.number), []),
            chain_complete=chain_complete,
            response_complete=response_complete,
            response_url=inputs.response_url,
        )
        for clause in current_required
    ]

    covered = [item["clause_no"] for item in clause_results if item["status"] == "covered"]
    missing_items = [item for item in clause_results if item["status"] == "missing"]
    duplicates = _duplicate_responses(response_rows)

    missing = [
        {
            "clause_no": item["clause_no"],
            "version": item["version"],
            "reason": "答复为空" if item["response"] and not text_of(item["response"][0]["answer"]) else "响应表无该条款",
        }
        for item in missing_items
    ]

    superseded = [
        {
            **old.to_dict(),
            "status": "superseded",
            "status_label": "已被后续版本替换，不作为当前要求",
        }
        for key in sorted(history, key=_natural_key)
        for old in history[key]
        if (key in state and old is not state[key])
    ]

    if not chain_complete or not response_complete:
        overall_status = "pending_verification"
    elif missing or duplicates or invalid or warnings:
        overall_status = "issues"
    else:
        overall_status = "ok"

    overall_message = {
        "ok": "全部当前强制条款均已被响应表覆盖。",
        "issues": "存在响应缺项、重复编号或失效的更正引用，请处理后提交。",
        "pending_verification": "公告链或响应页抓取不完整，相关结论已标为待核实；旧版本条款未被当作当前要求。",
    }[overall_status]

    return {
        "request": {
            "announcement_list_url": inputs.announcement_list_url,
            "project_no": inputs.project_no,
            "lot_no": inputs.lot_no,
            "response_url": inputs.response_url,
        },
        "overall_status": overall_status,
        "overall_status_label": {
            "ok": "通过",
            "issues": "需处理",
            "pending_verification": "待核实",
        }[overall_status],
        "message": overall_message,
        "chain_complete": chain_complete,
        "response_complete": response_complete,
        "summary": {
            "current_mandatory": len(current_required),
            "covered": len(covered),
            "missing": len(missing),
            "duplicate_clauses": len(duplicates),
            "pending_verification": sum(
                1 for item in clause_results if item["status"] == "pending_verification"
            ),
            "invalid_corrections": len(invalid),
            "superseded_versions": len(superseded),
            "fetch_issues": len(issues),
        },
        "clauses": clause_results,
        "missing": missing,
        "duplicates": duplicates,
        "invalid_corrections": [item.to_dict() for item in invalid],
        "fetch_issues": [issue.to_dict() for issue in issues],
        "superseded": superseded,
        "non_mandatory_current": [
            {**clause.to_dict(), "status": "not_required",
             "status_label": "当前非强制，不作为强制要求"}
            for clause in current_optional
        ],
        "announcements": [announcement.to_dict() for announcement in sorted(announcements, key=_announcement_sort_key)],
        "response_rows": [row.to_dict() for row in response_rows],
        "list_pages": pages,
    }
