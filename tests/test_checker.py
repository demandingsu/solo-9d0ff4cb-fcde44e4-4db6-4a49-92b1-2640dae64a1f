from pathlib import Path

import pytest

from app.checker import run_check, _apply_corrections
from app.models import Announcement, AnnouncementRef, Clause

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _clause(number, mandatory=True, references=None, version="v1", content="", order=0):
    return Clause(
        number=number,
        version=version,
        mandatory=mandatory,
        references=references or [],
        content=content,
        source_url="sample://unit/original.html",
        announcement_title="unit",
        announcement_kind="original",
        published_at="2026-01-01",
        order=order,
    )


def _announcement(kind, version, clauses, url="sample://unit/x.html", order=0):
    return Announcement(
        ref=AnnouncementRef(
            project_no="P-1",
            lot_no="L-1",
            kind=kind,
            version=version,
            title=kind,
            url=url,
            published_at="2026-01-01",
            order=order,
        ),
        clauses=clauses,
        fetched=True,
    )


def test_complete_sample_finds_all_separate_categories():
    report = run_check(
        "sample://demo/list.html",
        "ZB-2026-001",
        "LOT-A",
        "sample://demo/response.html",
        samples_root=SAMPLES,
    )

    assert report["overall_status"] == "issues"
    assert report["chain_complete"] is True
    assert report["response_complete"] is True

    # 1.3 is non-mandatory and therefore not a requirement.
    requirements = {item["clause_no"]: item for item in report["clauses"]}
    assert set(requirements) == {"1.1", "1.2", "2.1", "2.2"}

    # v3 correction replaced v1/v2 only because it referenced clause 1.2.
    assert requirements["1.2"]["version"] == "v3"
    assert requirements["1.2"]["status"] == "covered"
    superseded = {(item["clause_no"], item["version"]) for item in report["superseded"]}
    assert ("1.2", "v1") in superseded
    assert ("1.2", "v2") in superseded
    assert all("不作为当前要求" in item["status_label"] for item in report["superseded"])

    assert requirements["2.1"]["status"] == "duplicate"
    assert report["missing"] == [
        {"clause_no": "2.2", "version": "v1", "reason": "响应表无该条款"}
    ]
    assert [(item["clause_no"], item["count"]) for item in report["duplicates"]] == [("2.1", 2)]

    # Both invalid-reference categories are listed separately.
    invalid = {(item["clause_no"], item["reason"]) for item in report["invalid_corrections"]}
    assert any(no == "9.9" and "不存在" in reason for no, reason in invalid)
    assert any(no == "3.3" and "未明确引用" in reason for no, reason in invalid)

    # Pagination was followed to the second page.
    assert [page["url"] for page in report["list_pages"]] == [
        "sample://demo/list.html",
        "sample://demo/page2.html",
    ]

    # Every conclusion carries announcement and response sources.
    for item in report["clauses"]:
        assert item["sources"]
        assert any(source["type"] == "announcement" for source in item["sources"])
        if item["status"] in ("covered", "duplicate", "missing"):
            assert any(source["type"] == "response" for source in item["sources"])


def test_incomplete_chain_and_response_are_pending_not_old_versions():
    report = run_check(
        "sample://demo-incomplete/list.html",
        "ZB-2026-002",
        "LOT-B",
        "sample://demo-incomplete/response.html",
        samples_root=SAMPLES,
    )

    assert report["overall_status"] == "pending_verification"
    assert report["chain_complete"] is False
    assert report["response_complete"] is False
    assert report["missing"] == []
    assert all(item["status"] == "pending_verification" for item in report["clauses"])
    assert all(
        any("旧版本未被当作当前要求" in note for note in item["notes"])
        for item in report["clauses"]
    )
    scopes = {issue["scope"] for issue in report["fetch_issues"]}
    assert {"pagination", "response"} <= scopes


def test_response_fetch_failure_does_not_claim_missing():
    report = run_check(
        "sample://demo/list.html",
        "ZB-2026-001",
        "LOT-A",
        "sample://demo/response-missing.html",
        samples_root=SAMPLES,
    )
    assert report["overall_status"] == "pending_verification"
    assert report["chain_complete"] is True
    assert report["response_complete"] is False
    assert report["missing"] == []
    assert all(item["status"] == "pending_verification" for item in report["clauses"])


def test_project_mismatch_is_pending_with_explanation():
    report = run_check(
        "sample://demo/list.html",
        "ZB-2026-000",
        "LOT-A",
        "sample://demo/response.html",
        samples_root=SAMPLES,
    )
    assert report["overall_status"] == "pending_verification"
    assert report["clauses"] == []
    assert any("未找到项目编号" in issue["message"] for issue in report["fetch_issues"])


def test_correction_only_replaces_explicitly_referenced_existing_clause():
    original = _announcement(
        "original",
        "v1",
        [_clause("1.1", content="one"), _clause("1.2", content="two")],
    )
    no_reference = _announcement(
        "correction",
        "v2",
        [_clause("1.1", references=[], version="v2", content="should not be adopted")],
        url="sample://unit/correction-no-ref.html",
    )
    invalid_reference = _announcement(
        "correction",
        "v3",
        [_clause("8.8", references=["8.8"], version="v3", content="not existing")],
        url="sample://unit/correction-invalid.html",
    )
    valid_replacement = _announcement(
        "correction",
        "v4",
        [_clause("1.2", references=["1.2"], version="v4", content="replaced two")],
        url="sample://unit/correction-valid.html",
    )

    state, history, invalid, warnings, originals, corrections = _apply_corrections(
        [original, no_reference, invalid_reference, valid_replacement]
    )

    assert state["1.1"].content == "one"                     # not replaced
    assert state["1.2"].content == "replaced two"            # explicitly referenced
    assert state["1.2"].version == "v4"
    assert len(history["1.2"]) == 2
    assert {item.reason for item in invalid} == {
        "更正条款未明确引用任何现有条款",
        "引用的条款 8.8 不存在，更正未被采用",
    }
    assert warnings == []


def test_missing_input_raises_value_error():
    with pytest.raises(ValueError, match="缺少必填项"):
        run_check("", "P-1", "L-1", "sample://demo/response.html", samples_root=SAMPLES)
