"""FastAPI entry point: response-check form page plus JSON API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import AliasChoices, BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .checker import run_check
from .render import SAMPLE_PRESETS, render_error, render_form, render_result

APP_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = Path(os.environ.get("APP_SAMPLES_DIR", APP_ROOT / "samples")).resolve()


class CheckRequest(BaseModel):
    announcement_list_url: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "announcement_list_url", "announcement_url", "list_url", "公告列表URL"
        ),
        description="公告列表首页 URL；支持 http(s)、file:// 和离线 sample://",
    )
    project_no: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("project_no", "project", "项目编号"),
        description="项目编号",
    )
    lot_no: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("lot_no", "lot", "标段号"),
        description="标段号",
    )
    response_url: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "response_url", "response_table_url", "企业响应表URL"
        ),
        description="企业响应表 URL；支持 http(s)、file:// 和离线 sample://",
    )


app = FastAPI(
    title="投标技术响应核对",
    description=(
        "沿公告分页读取原公告与更正，按明确引用且存在的条款应用更正，"
        "核对当前强制条款是否被企业响应表覆盖。抓取不完整时结论标为待核实。"
    ),
    version="1.0.0",
)

if SAMPLES_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/samples", StaticFiles(directory=str(SAMPLES_DIR)), name="samples")


def _payload_from_aliases(data: dict[str, Any]) -> dict[str, str]:
    aliases = {
        "announcement_list_url": ("announcement_list_url", "announcement_url", "list_url"),
        "project_no": ("project_no", "project"),
        "lot_no": ("lot_no", "lot"),
        "response_url": ("response_url", "response_table_url"),
    }
    result: dict[str, str] = {}
    for field, names in aliases.items():
        for name in names:
            if name in data and str(data[name]).strip():
                result[field] = str(data[name]).strip()
                break
        result.setdefault(field, "")
    return result


async def _form_payload(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        return _payload_from_aliases(data if isinstance(data, dict) else {})
    raw = await request.body()
    try:
        parsed = parse_qs(raw.decode("utf-8")) if raw else {}
    except UnicodeDecodeError:
        parsed = {}
    flat = {key: values[0] for key, values in parsed.items() if values}
    # Fall back to query parameters so prefilled GET links can also submit.
    for key, value in request.query_params.items():
        flat.setdefault(key, value)
    return _payload_from_aliases(flat)


def _validate(payload: dict[str, str]) -> CheckRequest:
    return CheckRequest(**payload)


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(render_form())


@app.get("/response-check", response_class=HTMLResponse)
def response_check_form(request: Request) -> HTMLResponse:
    prefill = _payload_from_aliases(dict(request.query_params))
    return HTMLResponse(render_form(prefill=prefill))


@app.post("/response-check", response_class=HTMLResponse)
async def response_check_submit(request: Request) -> HTMLResponse:
    payload = await _form_payload(request)
    try:
        validated = _validate(payload)
    except ValidationError as exc:
        message = "；".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        return HTMLResponse(render_error("请完整填写输入项。" + message, prefill=payload), status_code=400)

    try:
        report = await run_in_threadpool(
            run_check,
            validated.announcement_list_url,
            validated.project_no,
            validated.lot_no,
            validated.response_url,
            samples_root=SAMPLES_DIR,
        )
    except ValueError as exc:
        return HTMLResponse(render_error(str(exc), prefill=payload), status_code=400)
    except Exception as exc:  # keep the page usable even on unexpected parser bugs
        return HTMLResponse(
            render_error(f"核对失败：{exc.__class__.__name__}: {exc}", prefill=payload),
            status_code=500,
        )
    return HTMLResponse(render_result(report))


@app.post("/api/response-check")
async def response_check_api(payload: CheckRequest) -> dict[str, Any]:
    try:
        return await run_in_threadpool(
            run_check,
            payload.announcement_list_url,
            payload.project_no,
            payload.lot_no,
            payload.response_url,
            samples_root=SAMPLES_DIR,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/samples")
def api_samples() -> list[dict[str, str]]:
    return SAMPLE_PRESETS


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
