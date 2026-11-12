"""HTML / JSON extraction for announcement lists, announcements and responses.

Supported page shapes (all optional, parsers choose the first that yields data):

* announcement list: an embedded JSON array, a table whose headers contain
  "项目"/"标段", elements carrying ``data-announcement``/``data-project``, or
  link rows with a project number in the text;
* announcement detail: embedded JSON (``clauses``), elements carrying
  ``data-clause-no``, a clause table, or simple labelled text lines;
* response table: embedded JSON, rows carrying ``data-clause-no``, or a table
  whose headers contain a clause number and a response/answer column.

Relative links are resolved against the page URL.  The parsers also return a
small ``recognized``/issue flag so the checker can distinguish "empty" from
"could not read this page at all" and mark the result 待核实.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .models import Announcement, AnnouncementRef, Clause, ResponseRow


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

_SAMPLE_SCHEME = "sample"


def resolve_url(base: str, href: str) -> str:
    """Resolve a possibly relative link for http(s), file and sample URLs."""
    href = (href or "").strip()
    if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
        return ""
    if href.startswith(("http://", "https://", "file://", "sample://")):
        return href
    if base.startswith("sample://"):
        parts = urlsplit(base)
        if href.startswith("/"):
            path = href
        else:
            directory = parts.path.rsplit("/", 1)[0]
            path = directory + "/" + href
        path = _normalise_posix_path(path)
        return urlunsplit((_SAMPLE_SCHEME, parts.netloc, path, "", ""))
    return urljoin(base, href)


def _normalise_posix_path(path: str) -> str:
    # Keep query strings out of the normalisation.
    clean, _, query = path.partition("?")
    parts = [p for p in clean.split("/")]
    # posixpath.normpath would turn "/" specially; preserve one leading slash.
    import posixpath

    norm = posixpath.normpath(clean)
    if norm == ".":
        norm = "/"
    result = norm
    if query:
        result += "?" + query
    return result


def same_url_scope(base: str, candidate: str) -> bool:
    if not candidate:
        return False
    if base.startswith("sample://"):
        return candidate.startswith("sample://") and urlsplit(candidate).netloc == urlsplit(base).netloc
    if base.startswith("file://"):
        return candidate.startswith("file://")
    if base.startswith(("http://", "https://")):
        return candidate.startswith(("http://", "https://")) and urlsplit(candidate).netloc == urlsplit(base).netloc
    return True


# ---------------------------------------------------------------------------
# Value normalisation
# ---------------------------------------------------------------------------


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "；".join(text_of(v) for v in value)
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_identifier(value: Any) -> str:
    value = unicodedata.normalize("NFKC", text_of(value))
    return re.sub(r"\s+", "", value).casefold()


def clean_identifier(value: Any) -> str:
    s = unicodedata.normalize("NFKC", text_of(value))
    s = re.sub(r"(?:项目|标段|包|标包)(?:编号|编码|号)?\s*[:：]?\s*", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def normalize_clause_no(value: Any) -> str:
    s = unicodedata.normalize("NFKC", text_of(value))
    s = re.sub(r"^\s*(?:条款(?:编号|号)?|条号|编号|序号)\s*[:：]?\s*", "", s)
    s = re.sub(r"^\s*第\s*", "", s)
    s = re.sub(r"\s*号\s*$", "", s)
    s = s.strip(" \t\r\n（）()【】[]「」\"'")
    s = s.replace("－", "-").replace("—", "-").replace("–", "-").replace("．", ".")
    s = re.sub(r"\s+", "", s)
    return s


def parse_version_number(value: Any) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", text_of(value))
    return tuple(int(n) for n in numbers)


def parse_mandatory(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    s = unicodedata.normalize("NFKC", text_of(value)).lower()
    if not s:
        return False
    for marker in ("非强制", "不强制", "非必须", "不必须", "不是", "不必", "不需要", "可选", "no", "false", "0"):
        if marker in s:
            return False
    if s.startswith("否"):
        return False
    for marker in ("强制", "必须", "required", "mandatory", "是", "yes", "true", "1", "√", "☑"):
        if marker in s:
            return True
    return False


def classify_kind(value: Any, fallback_text: str = "") -> str:
    s = unicodedata.normalize("NFKC", text_of(value)).lower()
    if not s:
        s = unicodedata.normalize("NFKC", text_of(fallback_text)).lower()
    if any(word in s for word in ("更正", "变更", "补遗", "澄清", "答疑", "修改", "addendum", "amendment", "correction", "change")):
        return "correction"
    return "original"


_CORRECTION_WORDS = ("更正", "变更", "补遗", "澄清", "答疑", "修改", "addendum", "amendment", "correction")


def parse_references(value: Any) -> list[str]:
    """Parse an explicitly supplied reference list.

    ``"1.1、1.2"`` and ``["1.1", "1.2"]`` both become ``["1.1", "1.2"]``.
    """
    if value is None:
        return []
    raw_items: list[str]
    if isinstance(value, (list, tuple)):
        raw_items = [text_of(v) for v in value]
    else:
        s = unicodedata.normalize("NFKC", text_of(value))
        s = re.sub(r"(?:引用|参见|关联|修改)(?:条款|条)?\s*[:：]?\s*", "", s)
        if s.strip() in ("", "-", "—", "无", "none", "null", "不涉及"):
            return []
        raw_items = re.split(r"[，,、;；/\s]+|和", s)
    result: list[str] = []
    for item in raw_items:
        item = text_of(item)
        if not item or item in ("-", "—", "无", "不涉及"):
            continue
        item = re.sub(r"(?:引用|参见|关联|修改)(?:条款|条)?\s*[:：]?\s*", "", item)
        match = re.search(r"[A-Za-z]?\d+(?:[.\-][0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*)", item)
        number = normalize_clause_no(match.group(0) if match else item)
        if number and number not in result:
            result.append(number)
    return result


def extract_project(text: str) -> str:
    m = re.search(r"项目(?:编号|编码|号)?\s*[:：]\s*([A-Za-z0-9一-鿿_.\-/]+)", text)
    if m:
        return clean_identifier(m.group(1))
    m = re.search(r"(?:采购|招标)(?:编号|项目编号)\s*[:：]\s*([A-Za-z0-9_.\-/]+)", text)
    return clean_identifier(m.group(1)) if m else ""


def extract_lot(text: str) -> str:
    m = re.search(r"(?:标段|标包|分包|包号)(?:编号|号)?\s*[:：]\s*([A-Za-z0-9一-鿿_.\-/]+)", text)
    if m:
        return clean_identifier(m.group(1))
    m = re.search(r"(?:标段|标包|分包)\s+([A-Za-z0-9_.\-/]+)", text)
    if m:
        return clean_identifier(m.group(1))
    m = re.search(r"(LOT[-_][A-Za-z0-9]+)", text, re.IGNORECASE)
    return clean_identifier(m.group(1)) if m else ""


def extract_version(text: str) -> str:
    m = re.search(r"(?:版本|版次|修订版)\s*[:：]\s*(v?\d+(?:\.\d+)*)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"第\s*(\d+)\s*版", text)
    if m:
        return "v" + m.group(1)
    return ""


# ---------------------------------------------------------------------------
# List page
# ---------------------------------------------------------------------------


@dataclass
class ListPage:
    refs: list[AnnouncementRef] = field(default_factory=list)
    next_links: list[str] = field(default_factory=list)
    recognized: bool = False
    issues: list[str] = field(default_factory=list)


def _attr(el: Tag, names: Iterable[str]) -> str:
    for name in names:
        if el.has_attr(name):
            value = el.get(name)
            if isinstance(value, (list, tuple)):
                value = " ".join(value)
            if text_of(value):
                return text_of(value)
    return ""


def _iter_json_scripts(soup: BeautifulSoup, hint: str) -> Iterable[Any]:
    for script in soup.find_all("script"):
        script_type = (script.get("type") or "").lower()
        sid = " ".join(
            str(script.get(attr, "")) for attr in ("id", "data-role", "data-name")
        ).lower()
        if script_type not in ("application/json", "") and "json" not in script_type:
            # Inline JavaScript is only used when it clearly contains our block.
            if hint not in sid:
                continue
        if hint not in sid and script_type not in ("application/json",):
            continue
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            yield json.loads(raw)
        except (ValueError, TypeError):
            continue


def _try_json_text(text: str) -> Any:
    """Parse a response whose whole body is JSON (an API URL, not an HTML page)."""
    stripped = (text or "").lstrip("﻿ \t\r\n")
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        return None


def _json_get(mapping: dict[str, Any], *names: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    lower = {str(key).lower().replace("_", ""): value for key, value in mapping.items()}
    for name in names:
        key = name.lower().replace("_", "")
        if key in lower:
            return lower[key]
    return None


def _ref_from_mapping(item: dict[str, Any], base_url: str, order: int) -> Optional[AnnouncementRef]:
    project = _json_get(item, "project_no", "projectno", "project", "项目编号", "项目编码", "招标编号")
    lot = _json_get(item, "lot_no", "lotno", "lot", "lot_id", "标段号", "标段编号", "标包")
    kind = _json_get(item, "kind", "type", "announcement_type", "公告类型", "类型")
    version = _json_get(item, "version", "公告版本", "版本", "release")
    title = _json_get(item, "title", "name", "公告标题", "标题")
    url = _json_get(item, "url", "href", "link", "公告链接", "链接")
    date = _json_get(item, "published_at", "date", "publish_date", "发布日期", "日期")
    if not url or not isinstance(url, str):
        return None
    text_blob = " ".join(text_of(v) for v in (kind, title, version))
    return AnnouncementRef(
        project_no=clean_identifier(project),
        lot_no=clean_identifier(lot),
        kind=classify_kind(kind, text_blob),
        version=text_of(version) or extract_version(text_blob),
        title=text_of(title),
        url=resolve_url(base_url, url),
        published_at=text_of(date),
        order=order,
    )


def _table_headers(table: Tag) -> tuple[list[str], list[Tag]]:
    rows = table.find_all("tr")
    if not rows:
        return [], []
    header_cells = rows[0].find_all(["th", "td"])
    headers = [text_of(cell.get_text(" ", strip=True)) for cell in header_cells]
    if any(cell.name == "th" for cell in header_cells):
        return headers, rows[1:]
    # No th: use the first row as a header only if it looks like one.
    joined = " ".join(headers)
    if any(word in joined for word in ("项目", "标段", "公告", "版本")):
        return headers, rows[1:]
    return [], rows


def _find_col(headers: list[str], keywords: Iterable[str], exclude: Iterable[str] = ()) -> int:
    for index, header in enumerate(headers):
        if any(keyword in header for keyword in exclude):
            continue
        if all(keyword in header for keyword in keywords):
            return index
    return -1


def _cell(row: Tag, index: int) -> str:
    cells = row.find_all(["td", "th"])
    if 0 <= index < len(cells):
        return text_of(cells[index].get_text(" ", strip=True))
    return ""


def _cell_tag(row: Tag, index: int) -> Optional[Tag]:
    cells = row.find_all(["td", "th"])
    if 0 <= index < len(cells):
        return cells[index]
    return None


def _table_refs(table: Tag, base_url: str, start_order: int) -> list[AnnouncementRef]:
    headers, data_rows = _table_headers(table)
    if not headers:
        return []
    project_col = _find_col(headers, ("项目", "编号"))
    if project_col < 0:
        project_col = _find_col(headers, ("项目",))
    lot_col = _find_col(headers, ("标段", "号")) if any("标段" in h for h in headers) else -1
    if lot_col < 0 and any("标段" in h for h in headers):
        lot_col = _find_col(headers, ("标段",))
    if lot_col < 0:
        lot_col = _find_col(headers, ("包", "号")) if any("包" in h for h in headers) else -1
    if lot_col < 0 and any("包" in h for h in headers):
        lot_col = _find_col(headers, ("包",))
    if project_col < 0 or lot_col < 0:
        return []
    kind_col = _find_col(headers, ("类型",)) if any("类型" in h for h in headers) else _find_col(headers, ("类别",))
    version_col = _find_col(headers, ("版本",))
    date_col = _find_col(headers, ("日期",)) if any("日期" in h for h in headers) else _find_col(headers, ("时间",))
    title_col = _find_col(headers, ("标题",)) if any("标题" in h for h in headers) else -1

    result: list[AnnouncementRef] = []
    for offset, row in enumerate(data_rows):
        if not row.find_all(["td", "th"]):
            continue
        project = clean_identifier(_cell(row, project_col))
        if not project:
            project = extract_project(row.get_text(" ", strip=True))
        lot = clean_identifier(_cell(row, lot_col))
        if not lot:
            lot = extract_lot(row.get_text(" ", strip=True))
        row_text = text_of(row.get_text(" ", strip=True))
        kind_raw = _cell(row, kind_col) if kind_col >= 0 else ""
        version = _cell(row, version_col) if version_col >= 0 else ""
        version = version or extract_version(row_text)
        date = _cell(row, date_col) if date_col >= 0 else ""
        title = _cell(row, title_col) if title_col >= 0 else ""

        anchor = row.find("a", href=True)
        url = resolve_url(base_url, anchor.get("href")) if anchor else ""
        if not url:
            # Some tables put the URL in the link/title cell text.
            for link_keyword in ("链接", "网址", "url"):
                idx = _find_col(headers, (link_keyword,))
                if idx >= 0:
                    candidate = _cell(row, idx)
                    if candidate.startswith(("http", "sample:", "file:", "/")):
                        url = resolve_url(base_url, candidate)
                        break
        if not url:
            continue
        if anchor and not title:
            title = text_of(anchor.get_text(" ", strip=True))
        result.append(
            AnnouncementRef(
                project_no=project,
                lot_no=lot,
                kind=classify_kind(kind_raw, row_text),
                version=version,
                title=title,
                url=url,
                published_at=date,
                order=start_order + offset,
            )
        )
    return result


def _ref_from_element(el: Tag, base_url: str, order: int) -> Optional[AnnouncementRef]:
    row_text = text_of(el.get_text(" ", strip=True))
    project = _attr(el, ("data-project", "data-project-no", "data-projectno", "data-xiangmu"))
    lot = _attr(el, ("data-lot", "data-lot-no", "data-lotno", "data-biaoduan", "data-section"))
    kind = _attr(el, ("data-kind", "data-type", "data-announcement-type"))
    version = _attr(el, ("data-version", "data-release"))
    date = _attr(el, ("data-date", "data-published", "data-published-at"))
    title = _attr(el, ("data-title", "data-name"))
    url = _attr(el, ("data-url", "data-href", "data-link"))
    anchor = el.find("a", href=True)
    if not url and anchor:
        url = anchor.get("href", "")
    if not url:
        return None
    project = project or extract_project(row_text)
    lot = lot or extract_lot(row_text)
    version = version or extract_version(row_text)
    if not title and anchor:
        title = text_of(anchor.get_text(" ", strip=True))
    if not title:
        heading = el.find(["h1", "h2", "h3", "h4"])
        title = text_of(heading.get_text(" ", strip=True)) if heading else ""
    return AnnouncementRef(
        project_no=clean_identifier(project),
        lot_no=clean_identifier(lot),
        kind=classify_kind(kind, row_text),
        version=version,
        title=title,
        url=resolve_url(base_url, url),
        published_at=date,
        order=order,
    )


def _looks_like_pagination(anchor: Tag) -> bool:
    href = (anchor.get("href") or "").lower()
    classes = " ".join(anchor.get("class", [])).lower()
    rel = " ".join(anchor.get("rel", [])).lower()
    text = text_of(anchor.get_text(" ", strip=True))
    ancestors = [anchor] + list(anchor.parents)
    in_pager = any(
        any(word in " ".join(parent.get("class", [])).lower() for word in ("pagination", "pager", "page-nav", "pagebar"))
        for parent in ancestors
        if isinstance(parent, Tag)
    )
    if "next" in rel or "next" in classes:
        return True
    if text in ("下一页", "下页", "下一頁", "next", "»", ">"):
        return True
    if in_pager and (text.isdigit() or any(marker in href for marker in ("page=", "page/", "/p", "index_" , "list_"))):
        return True
    return False


def _extract_next_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links: list[str] = []
    for link in soup.find_all("link", href=True):
        if "next" in " ".join(link.get("rel", [])).lower():
            resolved = resolve_url(base_url, link.get("href", ""))
            if resolved:
                links.append(resolved)
    for anchor in soup.find_all("a", href=True):
        if not _looks_like_pagination(anchor):
            continue
        resolved = resolve_url(base_url, anchor.get("href", ""))
        if resolved:
            links.append(resolved)
    # Explicit "next" fields in embedded list JSON.
    for payload in _iter_json_scripts(soup, "announcement"):
        if isinstance(payload, dict):
            nxt = _json_get(payload, "next", "next_url", "next_page", "下一页")
            if isinstance(nxt, str) and nxt.strip():
                resolved = resolve_url(base_url, nxt)
                if resolved:
                    links.append(resolved)
    seen: set[str] = set()
    result: list[str] = []
    for link in links:
        if link not in seen and link != base_url:
            seen.add(link)
            result.append(link)
    return result


def parse_announcement_list(html: str, base_url: str) -> ListPage:
    soup = BeautifulSoup(html, "html.parser")
    page = ListPage()
    order = 0

    # 1) Embedded JSON (or a JSON API body).
    payloads: list[Any] = []
    direct = _try_json_text(html)
    if direct is not None:
        payloads.append(direct)
    payloads.extend(_iter_json_scripts(soup, "announcement"))
    direct_next: list[str] = []
    for payload in payloads:
        items: Any = None
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = (
                payload.get("announcements")
                or payload.get("items")
                or payload.get("data")
                or payload.get("list")
            )
            nxt = _json_get(payload, "next", "next_url", "next_page", "下一页")
            if isinstance(nxt, str) and nxt.strip():
                resolved = resolve_url(base_url, nxt)
                if resolved:
                    direct_next.append(resolved)
        if isinstance(items, list):
            page.recognized = True
            for item in items:
                if not isinstance(item, dict):
                    continue
                ref = _ref_from_mapping(item, base_url, order)
                if ref:
                    page.refs.append(ref)
                    order += 1

    # 2) Tables.
    for table in soup.find_all("table"):
        refs = _table_refs(table, base_url, order)
        if refs:
            page.refs.extend(refs)
            order += len(refs)
            page.recognized = True

    # 3) Semantic announcement elements (outside tables).
    for el in soup.find_all(True):
        if el.name not in ("li", "div", "article", "section"):
            continue
        if el.find_parent("table") is not None:
            continue
        classes = " ".join(el.get("class", [])).lower()
        if not (
            "announcement" in classes
            or "notice-item" in classes
            or el.has_attr("data-announcement")
            or (el.has_attr("data-project") and el.has_attr("data-kind"))
        ):
            continue
        ref = _ref_from_element(el, base_url, order)
        if ref:
            page.refs.append(ref)
            order += 1
            page.recognized = True

    # 4) Last-resort link rows.  Only accept rows that clearly name a project.
    if not page.refs:
        for anchor in soup.find_all("a", href=True):
            if _looks_like_pagination(anchor):
                continue
            row = anchor.find_parent(["tr", "li", "div"])
            blob = text_of((row or anchor).get_text(" ", strip=True))
            if not any(word in blob for word in ("公告", "通知", "更正", "变更", "补遗", "澄清")):
                continue
            if not extract_project(blob):
                continue
            ref = AnnouncementRef(
                project_no=extract_project(blob),
                lot_no=extract_lot(blob),
                kind=classify_kind("", blob),
                version=extract_version(blob),
                title=text_of(anchor.get_text(" ", strip=True)),
                url=resolve_url(base_url, anchor.get("href", "")),
                published_at="",
                order=order,
            )
            page.refs.append(ref)
            order += 1
            page.recognized = True

    page.next_links = direct_next + _extract_next_links(soup, base_url)
    page.next_links = list(dict.fromkeys(page.next_links))
    if not page.refs and not page.recognized and not page.next_links:
        page.issues.append("未能在页面中识别公告列表结构")
    return page


# ---------------------------------------------------------------------------
# Announcement detail page
# ---------------------------------------------------------------------------


def _detail_meta(soup: BeautifulSoup, ref: AnnouncementRef) -> dict[str, str]:
    meta: dict[str, str] = {}

    def put(key: str, value: Any) -> None:
        value = text_of(value)
        if value:
            meta[key] = value

    for name in ("project-no", "project", "project_no", "lot-no", "lot", "lot_no",
                 "kind", "type", "announcement-type", "version", "published-at", "date"):
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            put(name.replace("-", "_"), tag.get("content"))

    containers = soup.select(".announcement-detail, .announcement-meta, [data-announcement-detail]")
    if not containers:
        containers = soup.find_all(
            lambda tag: isinstance(tag, Tag)
            and tag.has_attr("data-project")
            and tag.has_attr("data-kind")
        )
    for el in containers:
        for attr, key in (
            ("data-project", "project_no"),
            ("data-project-no", "project_no"),
            ("data-lot", "lot_no"),
            ("data-lot-no", "lot_no"),
            ("data-kind", "kind"),
            ("data-type", "kind"),
            ("data-version", "version"),
            ("data-date", "published_at"),
            ("data-published-at", "published_at"),
            ("data-title", "title"),
        ):
            put(key, _attr(el, (attr,)))

    title = soup.find("title")
    if title:
        put("title", title.get_text(" ", strip=True))
    heading = soup.find(["h1", "h2"])
    if heading:
        put("title", heading.get_text(" ", strip=True))

    return {"project_no": ref.project_no, "lot_no": ref.lot_no,
            "kind": ref.kind, "version": ref.version, "title": ref.title,
            "published_at": ref.published_at, **meta}


def _clause_from_mapping(item: dict[str, Any], *, source_url: str, default_version: str,
                         default_kind: str, default_title: str, default_date: str,
                         order: int) -> Optional[Clause]:
    number = _json_get(item, "clause_no", "clause", "number", "no", "条款编号", "编号", "条款号")
    number = normalize_clause_no(number)
    if not number:
        return None
    refs = _json_get(item, "references", "refs", "reference", "引用", "引用条款")
    version = _json_get(item, "version", "版本", "版次") or default_version
    mandatory = _json_get(item, "mandatory", "required", "强制", "强制标记", "是否强制")
    content = _json_get(item, "content", "text", "body", "条款内容", "内容", "要求")
    return Clause(
        number=number,
        version=text_of(version),
        mandatory=parse_mandatory(mandatory),
        references=parse_references(refs),
        content=text_of(content),
        source_url=source_url,
        announcement_title=default_title,
        announcement_kind=default_kind,
        published_at=default_date,
        order=order,
        raw={},
    )


def _extract_detail_json(soup: BeautifulSoup, source_url: str, version: str,
                         kind: str, title: str, date: str,
                         raw_html: str = "") -> tuple[list[Clause], dict[str, Any]]:
    clauses: list[Clause] = []
    meta: dict[str, Any] = {}
    payloads: list[Any] = []
    direct = _try_json_text(raw_html)
    if direct is not None:
        payloads.append(direct)
    payloads.extend(_iter_json_scripts(soup, "clause"))
    for payload in payloads:
        obj = payload
        if isinstance(obj, dict):
            if isinstance(obj.get("announcement"), dict):
                meta.update(obj["announcement"])
            for key in ("project_no", "project", "lot_no", "lot", "kind", "type",
                        "version", "title", "published_at", "date"):
                if key in obj and obj[key] is not None:
                    meta.setdefault(key, obj[key])
        if isinstance(obj, dict) and isinstance(obj.get("clauses"), list):
            items = obj["clauses"]
        elif isinstance(obj, list):
            items = obj
        else:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            clause = _clause_from_mapping(
                item, source_url=source_url, default_version=version,
                default_kind=kind, default_title=title, default_date=date,
                order=len(clauses),
            )
            if clause:
                clauses.append(clause)
    return clauses, meta


def _clause_no_from_element(el: Tag) -> str:
    attr = _attr(el, ("data-clause-no", "data-clause", "data-no", "data-number"))
    if attr:
        return normalize_clause_no(attr)
    for selector in (".clause-no", ".clause-number", ".clause-id"):
        child = el.select_one(selector)
        if child:
            return normalize_clause_no(child.get_text(" ", strip=True))
    # A label inside the element: "条款编号：1.1"
    blob = text_of(el.get_text(" ", strip=True))
    m = re.search(r"(?:条款(?:编号|号)?|编号)\s*[:：]\s*([A-Za-z]?\d+(?:[.\-]\d+)+)", blob)
    if m:
        return normalize_clause_no(m.group(1))
    m = re.match(r"\s*([A-Za-z]?\d+(?:[.\-]\d+)+)\s*(?:[：:、]|\s)", blob)
    return normalize_clause_no(m.group(1)) if m else ""


def _clause_refs_from_element(el: Tag) -> list[str]:
    attr = _attr(el, ("data-references", "data-refs", "data-reference", "data-ref"))
    if attr:
        return parse_references(attr)
    for selector in (".clause-references", ".clause-refs", ".clause-reference", ".references"):
        child = el.select_one(selector)
        if child:
            return parse_references(child.get_text(" ", strip=True))
    blob = text_of(el.get_text(" ", strip=True))
    m = re.search(r"(?:引用|参见|关联)(?:条款|条)?\s*[:：]\s*([^\s，,；;]*(?:[、，,；;][^\s，,；;]*)*)", blob)
    return parse_references(m.group(1)) if m else []


def _clause_content_from_element(el: Tag) -> str:
    attr = _attr(el, ("data-content", "data-text", "data-body"))
    if attr:
        return attr
    for selector in (".clause-content", ".clause-text", ".content", ".clause-body"):
        child = el.select_one(selector)
        if child:
            return text_of(child.get_text(" ", strip=True))
    return text_of(el.get_text(" ", strip=True))


def _class_tokens(el: Tag) -> list[str]:
    return [str(token).lower() for token in el.get("class", [])]


def _is_clause_container(el: Tag) -> bool:
    tokens = _class_tokens(el)
    return (
        any(token in ("clause", "clause-item") for token in tokens)
        or any(el.has_attr(a) for a in ("data-clause-no", "data-clause", "data-no", "data-number"))
    )


def _extract_clause_elements(soup: BeautifulSoup, source_url: str, version: str,
                             kind: str, title: str, date: str) -> list[Clause]:
    clauses: list[Clause] = []
    for el in soup.find_all(True):
        if el.name not in ("li", "div", "article", "section"):
            continue
        if not _is_clause_container(el):
            continue
        # Avoid nested clause wrappers producing duplicate children.
        if any(
            isinstance(child, Tag) and _is_clause_container(child)
            for child in el.find_all(True, recursive=False)
        ):
            continue
        number = _clause_no_from_element(el)
        if not number:
            continue
        blob = text_of(el.get_text(" ", strip=True))
        mandatory = parse_mandatory(_attr(el, ("data-mandatory", "data-required", "data-must")))
        if not mandatory and "非强制" not in blob and ("强制" in blob or "必须" in blob):
            mandatory = True
        clause_version = _attr(el, ("data-version", "data-release")) or version
        clauses.append(
            Clause(
                number=number,
                version=clause_version,
                mandatory=mandatory,
                references=_clause_refs_from_element(el),
                content=_clause_content_from_element(el),
                source_url=source_url,
                announcement_title=title,
                announcement_kind=kind,
                published_at=date,
                order=len(clauses),
            )
        )
    return clauses


def _table_header_index(headers: list[str], keywords: Iterable[str], exclude: Iterable[str] = ()) -> int:
    for index, header in enumerate(headers):
        if any(word in header for word in exclude):
            continue
        if all(word in header for word in keywords):
            return index
    return -1


def _extract_clause_table(soup: BeautifulSoup, source_url: str, version: str,
                          kind: str, title: str, date: str) -> list[Clause]:
    clauses: list[Clause] = []
    for table in soup.find_all("table"):
        headers, data_rows = _table_headers(table)
        if not headers:
            continue
        joined = " ".join(headers)
        if "条款" not in joined and not (any("编号" in h for h in headers) and any("内容" in h for h in headers)):
            continue
        no_col = _table_header_index(headers, ("条款", "编号"))
        if no_col < 0:
            no_col = _table_header_index(headers, ("条款", "号"))
        if no_col < 0 and any("条款" in h for h in headers):
            no_col = _table_header_index(headers, ("编号",))
        version_col = _table_header_index(headers, ("版本",))
        mandatory_col = _table_header_index(headers, ("强制",))
        refs_col = _table_header_index(headers, ("引用",))
        content_col = _table_header_index(headers, ("内容",))
        if content_col < 0:
            content_col = _table_header_index(headers, ("要求",))
        if no_col < 0 or content_col < 0:
            continue
        for row in data_rows:
            number = normalize_clause_no(_cell(row, no_col))
            if not number:
                continue
            refs = parse_references(_cell(row, refs_col)) if refs_col >= 0 else []
            clause_version = (_cell(row, version_col) if version_col >= 0 else "") or version
            mandatory = parse_mandatory(_cell(row, mandatory_col)) if mandatory_col >= 0 else False
            content = _cell(row, content_col)
            if not content:
                # Fall back to all non-structural columns.
                parts = []
                for idx, _header in enumerate(headers):
                    if idx not in (no_col, version_col, mandatory_col, refs_col):
                        parts.append(_cell(row, idx))
                content = "；".join(p for p in parts if p)
            clauses.append(
                Clause(
                    number=number,
                    version=clause_version,
                    mandatory=mandatory,
                    references=refs,
                    content=content,
                    source_url=source_url,
                    announcement_title=title,
                    announcement_kind=kind,
                    published_at=date,
                    order=len(clauses),
                )
            )
    return clauses


def _extract_clause_text(soup: BeautifulSoup, source_url: str, version: str,
                         kind: str, title: str, date: str) -> list[Clause]:
    lines = [text_of(line) for line in soup.get_text("\n").splitlines()]
    clauses: list[Clause] = []
    for raw_line in lines:
        if not raw_line or not ("强制" in raw_line or "必须" in raw_line or "条款" in raw_line):
            continue
        line = raw_line
        m = re.search(r"(?:条款(?:编号|号)?|编号)\s*[:：]\s*([A-Za-z]?\d+(?:[.\-]\d+)+)", line)
        if not m:
            m = re.match(r"\s*([A-Za-z]?\d+(?:[.\-]\d+)+)\s+.*(?:强制|必须)", line)
        if not m:
            continue
        number = normalize_clause_no(m.group(1))
        if not number:
            continue
        vm = re.search(r"(?:版本|版次)\s*[:：]\s*(v?\d+(?:\.\d+)*)", line, re.IGNORECASE)
        clause_version = vm.group(1) if vm else version
        mandatory = parse_mandatory("非强制" if "非强制" in line else "强制")
        rm = re.search(r"(?:引用|参见|关联)(?:条款|条)?\s*[:：]\s*([^；;。]*)", line)
        refs = parse_references(rm.group(1)) if rm else []
        cm = re.search(r"(?:内容|要求)\s*[:：]\s*(.*)$", line)
        content = cm.group(1) if cm else line
        clauses.append(
            Clause(
                number=number,
                version=clause_version,
                mandatory=mandatory,
                references=refs,
                content=text_of(content),
                source_url=source_url,
                announcement_title=title,
                announcement_kind=kind,
                published_at=date,
                order=len(clauses),
            )
        )
    return clauses


def parse_announcement_detail(html: str, url: str, ref: AnnouncementRef) -> tuple[Announcement, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    meta = _detail_meta(soup, ref)
    kind = classify_kind(meta.get("kind", ""), meta.get("title", "")) if meta.get("kind") else ref.kind
    version = meta.get("version", "") or ref.version
    title = meta.get("title", "") or ref.title
    date = meta.get("published_at", "") or ref.published_at

    clauses, json_meta = _extract_detail_json(soup, url, version, kind, title, date, raw_html=html)
    if json_meta:
        kind = classify_kind(json_meta.get("kind", ""), title) if json_meta.get("kind") else kind
        version = text_of(json_meta.get("version")) or version
        title = text_of(json_meta.get("title")) or title
        date = text_of(json_meta.get("published_at") or json_meta.get("date")) or date
    issues: list[str] = []
    if not clauses:
        clauses = _extract_clause_elements(soup, url, version, kind, title, date)
    if not clauses:
        clauses = _extract_clause_table(soup, url, version, kind, title, date)
    if not clauses:
        clauses = _extract_clause_text(soup, url, version, kind, title, date)

    # Deduplicate identical clause numbers read twice (e.g. wrapper + child).
    seen: dict[str, Clause] = {}
    deduped: list[Clause] = []
    for clause in clauses:
        key = normalize_clause_no(clause.number)
        if not key:
            continue
        if key in seen:
            continue
        seen[key] = clause
        clause.order = len(deduped)
        deduped.append(clause)

    if not deduped:
        issues.append("未能从公告页面识别任何条款")

    return Announcement(
        ref=AnnouncementRef(
            project_no=text_of(json_meta.get("project_no") or json_meta.get("project")) or meta.get("project_no", ref.project_no),
            lot_no=text_of(json_meta.get("lot_no") or json_meta.get("lot")) or meta.get("lot_no", ref.lot_no),
            kind=kind,
            version=version,
            title=title,
            url=url,
            published_at=date,
            order=ref.order,
        ),
        clauses=deduped,
        fetched=True,
    ), issues


# ---------------------------------------------------------------------------
# Response table
# ---------------------------------------------------------------------------


@dataclass
class ResponsePage:
    rows: list[ResponseRow] = field(default_factory=list)
    recognized: bool = False
    issues: list[str] = field(default_factory=list)


def _response_row_from_mapping(item: dict[str, Any], url: str, index: int) -> Optional[ResponseRow]:
    number = _json_get(item, "clause_no", "clause", "number", "no", "条款编号", "编号", "条款号")
    answer = _json_get(item, "answer", "response", "reply", "答复", "响应", "应答", "回复", "响应内容")
    number = normalize_clause_no(number)
    if not number:
        return None
    return ResponseRow(
        number=number,
        answer=text_of(answer),
        source_url=url,
        row_index=index,
    )


def parse_response(html: str, url: str) -> ResponsePage:
    soup = BeautifulSoup(html, "html.parser")
    page = ResponsePage()

    # 1) Embedded JSON (or a JSON API body).
    payloads: list[Any] = []
    direct = _try_json_text(html)
    if direct is not None:
        payloads.append(direct)
    payloads.extend(_iter_json_scripts(soup, "response"))
    for payload in payloads:
        items: Any = None
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = (
                payload.get("responses")
                or payload.get("rows")
                or payload.get("items")
                or payload.get("data")
            )
        if isinstance(items, list):
            page.recognized = True
            for item in items:
                if isinstance(item, dict):
                    row = _response_row_from_mapping(item, url, len(page.rows) + 1)
                    if row:
                        page.rows.append(row)
                    else:
                        page.issues.append("存在无法识别的响应 JSON 行（缺少条款编号）")

    # 2) Semantic response rows.
    for el in soup.find_all(True):
        if el.name not in ("tr", "li", "div"):
            continue
        classes = " ".join(el.get("class", [])).lower()
        has_attr = any(el.has_attr(a) for a in ("data-response-clause", "data-clause-no", "data-clause"))
        if not (has_attr or "response-row" in classes):
            continue
        # Rows inside tables are handled by the table parser below; this
        # avoids reading the same table row twice.
        if el.find_parent("table") is not None:
            continue
        number = normalize_clause_no(
            _attr(el, ("data-response-clause", "data-clause-no", "data-clause", "data-no"))
        )
        if not number:
            number = _clause_no_from_element(el)
        answer = _attr(el, ("data-answer", "data-response", "data-reply"))
        if not answer:
            for selector in (".answer", ".response", ".reply", ".response-answer"):
                child = el.select_one(selector)
                if child:
                    answer = child.get_text(" ", strip=True)
                    break
        if not answer:
            answer = text_of(el.get_text(" ", strip=True))
        page.recognized = True
        if not number:
            page.issues.append("存在无法识别的响应行（缺少条款编号）")
            continue
        page.rows.append(ResponseRow(number=number, answer=text_of(answer),
                                     source_url=url, row_index=len(page.rows) + 1))

    # 3) Response table.
    for table in soup.find_all("table"):
        headers, data_rows = _table_headers(table)
        if not headers:
            continue
        joined = " ".join(headers)
        no_col = _table_header_index(headers, ("条款", "编号"))
        if no_col < 0:
            no_col = _table_header_index(headers, ("条款", "号"))
        if no_col < 0:
            no_col = _table_header_index(headers, ("编号",))
        answer_col = -1
        for keyword in ("答复", "响应", "应答", "回复", "说明", "响应情况", "是否响应"):
            answer_col = _table_header_index(headers, (keyword,))
            if answer_col >= 0:
                break
        if no_col < 0 or answer_col < 0:
            continue
        if not ("条款" in joined or "答复" in joined or "响应" in joined):
            continue
        page.recognized = True
        for row in data_rows:
            number = normalize_clause_no(_cell(row, no_col))
            if not number:
                if any(_cell(row, i) for i in range(len(headers))):
                    page.issues.append("响应表中存在缺少条款编号的行")
                continue
            answer = _cell(row, answer_col)
            page.rows.append(
                ResponseRow(number=number, answer=answer, source_url=url,
                            row_index=len(page.rows) + 1)
            )

    # Deduplicate rows that were found both as elements and in a table?  We
    # intentionally keep them: duplicate clause numbers are a required finding.
    # But if the exact same element/table row was read twice, drop exact copies.
    deduped: list[ResponseRow] = []
    for row in page.rows:
        duplicate_of_last = any(
            previous.number == row.number
            and previous.answer == row.answer
            and previous.row_index == row.row_index
            for previous in deduped
        )
        if not duplicate_of_last:
            deduped.append(row)
    page.rows = deduped
    for index, row in enumerate(page.rows, start=1):
        row.row_index = index

    if not page.recognized:
        page.issues.append("未能从响应页面识别响应表结构")
    return page
