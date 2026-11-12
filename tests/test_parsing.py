import json

from app.models import AnnouncementRef
from app.parsing import (
    parse_announcement_detail,
    parse_announcement_list,
    parse_mandatory,
    parse_response,
)


def test_json_api_bodies_are_supported_for_list_detail_and_response():
    list_body = json.dumps({
        "announcements": [{
            "project_no": "P-1",
            "lot_no": "L-1",
            "kind": "correction",
            "version": "v2",
            "title": "更正",
            "url": "detail.html",
        }],
        "next": "page2.json",
    })
    list_page = parse_announcement_list(list_body, "sample://demo/api/list.json")
    assert list_page.recognized is True
    assert len(list_page.refs) == 1
    assert list_page.refs[0].kind == "correction"
    assert list_page.next_links == ["sample://demo/api/page2.json"]

    detail_body = json.dumps({
        "project_no": "P-1",
        "lot_no": "L-1",
        "kind": "original",
        "version": "v1",
        "clauses": [{"clause_no": "1.1", "mandatory": True, "content": "要求"}],
    })
    announcement, issues = parse_announcement_detail(
        detail_body,
        "sample://demo/api/detail.json",
        AnnouncementRef(project_no="P-1", lot_no="L-1"),
    )
    assert announcement.ref.project_no == "P-1"
    assert [(clause.number, clause.mandatory) for clause in announcement.clauses] == [("1.1", True)]
    assert issues == []

    response_body = json.dumps({"responses": [{"clause_no": "1.1", "answer": "满足"}]})
    response_page = parse_response(response_body, "sample://demo/api/response.json")
    assert response_page.recognized is True
    assert [(row.number, row.answer) for row in response_page.rows] == [("1.1", "满足")]


def test_mandatory_flag_does_not_misread_shi_fou():
    assert parse_mandatory("是否强制：是") is True
    assert parse_mandatory("否") is False
    assert parse_mandatory("非强制") is False
    assert parse_mandatory("非必须") is False
    assert parse_mandatory("必须") is True
