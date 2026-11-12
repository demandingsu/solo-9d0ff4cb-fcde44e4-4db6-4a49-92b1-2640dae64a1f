from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture()
def client():
    return TestClient(app)


def test_form_page_prefills_query_values(client):
    response = client.get(
        "/response-check",
        params={
            "announcement_list_url": "sample://demo/list.html",
            "project_no": "ZB-2026-001",
            "lot_no": "LOT-A",
            "response_url": "sample://demo/response.html",
        },
    )
    assert response.status_code == 200
    assert "sample://demo/list.html" in response.text
    assert "ZB-2026-001" in response.text
    assert "LOT-A" in response.text
    # Offline presets are available on the page.
    assert "完整样例" in response.text
    assert "抓取不完整样例" in response.text


def test_json_api_returns_structured_report(client):
    response = client.post(
        "/api/response-check",
        json={
            "announcement_list_url": "sample://demo/list.html",
            "project_no": "ZB-2026-001",
            "lot_no": "LOT-A",
            "response_url": "sample://demo/response.html",
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["overall_status"] == "issues"
    assert report["summary"]["current_mandatory"] == 4
    assert [item["clause_no"] for item in report["missing"]] == ["2.2"]
    assert [item["clause_no"] for item in report["duplicates"]] == ["2.1"]
    assert {item["clause_no"] for item in report["invalid_corrections"]} == {"9.9", "3.3"}


def test_html_post_renders_per_clause_conclusions_and_sources(client):
    response = client.post(
        "/response-check",
        data={
            "announcement_list_url": "sample://demo/list.html",
            "project_no": "ZB-2026-001",
            "lot_no": "LOT-A",
            "response_url": "sample://demo/response.html",
        },
    )
    assert response.status_code == 200
    text = response.text
    for expected in ("逐条结论与来源", "待核实", "响应表缺项", "重复编号", "更正引用失效",
                     "已替换的旧版本", "sample://demo/detail-correction-v3.html"):
        assert expected in text
    # Old versions are explicitly labelled as not current requirements.
    assert "不作为当前要求" in text
    # Sample sources are exposed as server-served links for offline use.
    assert "/samples/demo/detail-original.html" in text


def test_form_post_with_missing_field_returns_400(client):
    response = client.post(
        "/response-check",
        data={
            "announcement_list_url": "sample://demo/list.html",
            "project_no": "ZB-2026-001",
            "lot_no": "LOT-A",
        },
    )
    assert response.status_code == 400
    assert "输入有误" in response.text


def test_json_api_validation_error_is_422(client):
    response = client.post(
        "/api/response-check",
        json={"announcement_list_url": "sample://demo/list.html"},
    )
    assert response.status_code == 422


def test_samples_and_health_are_offline_accessible(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    response = client.get("/samples/demo/list.html")
    assert response.status_code == 200
    assert "ZB-2026-001" in response.text
    assert client.get("/api/samples").status_code == 200
