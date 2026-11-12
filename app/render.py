"""Small server-side HTML renderer (no template engine / no network assets)."""

from __future__ import annotations

from html import escape
from typing import Any, Iterable

CSS = """
:root {
  --ink:#17212b; --muted:#5b6b7a; --line:#dbe3ea; --bg:#f5f7fa; --card:#fff;
  --blue:#195b9b; --blue-soft:#e8f1fb; --green:#1c7a4b; --green-soft:#e7f6ee;
  --red:#b42318; --red-soft:#fdecea; --amber:#9a6700; --amber-soft:#fff4d6;
  --gray-soft:#eef1f4;
}
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif;
  color:var(--ink); background:var(--bg); line-height:1.55; }
header { background:#0f2c47; color:#fff; }
header .wrap { max-width:1180px; margin:0 auto; padding:14px 20px; display:flex; gap:22px; align-items:center; flex-wrap:wrap; }
header h1 { font-size:18px; margin:0; font-weight:650; letter-spacing:.3px; }
header nav a { color:#cfe0f3; text-decoration:none; margin-right:16px; font-size:14px; }
header nav a.active { color:#fff; border-bottom:2px solid #7ab7f0; padding-bottom:2px; }
main { max-width:1180px; margin:0 auto; padding:24px 20px 60px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px 22px; margin-bottom:18px; box-shadow:0 1px 2px rgba(16,36,58,.04); }
h2 { font-size:20px; margin:0 0 6px; }
h3 { font-size:16px; margin:0 0 10px; }
p.lead { color:var(--muted); margin:0 0 18px; }
.small { color:var(--muted); font-size:12.5px; }
label { display:block; font-size:13px; font-weight:600; margin:0 0 6px; }
input[type=text], input[type=url] { width:100%; padding:10px 12px; border:1px solid #c7d2dd; border-radius:8px;
  font-size:14px; font-family:inherit; background:#fff; }
input:focus { outline:2px solid #8fc3ef; outline-offset:1px; border-color:#5b9dd4; }
.grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.grid .full { grid-column:1 / -1; }
.actions { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-top:18px; }
button { background:var(--blue); color:#fff; border:0; border-radius:8px; padding:10px 22px; font-size:14px; font-weight:600; cursor:pointer; }
button:hover { background:#134a7f; }
.preset { display:inline-block; border:1px solid #b7cde2; color:var(--blue); background:var(--blue-soft);
  text-decoration:none; padding:7px 12px; border-radius:8px; font-size:13px; }
.preset:hover { background:#d9e9f8; }
.banner { border-radius:12px; padding:16px 18px; margin-bottom:18px; border:1px solid; }
.banner.ok { background:var(--green-soft); border-color:#b7e2ca; color:#125d39; }
.banner.issues { background:var(--red-soft); border-color:#f3c2bd; color:#8f1d14; }
.banner.pending { background:var(--amber-soft); border-color:#ead18b; color:#6e4b00; }
.banner strong { font-size:17px; }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:12px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.stat .num { font-size:24px; font-weight:700; line-height:1.1; }
.stat .lbl { color:var(--muted); font-size:12.5px; margin-top:4px; }
.badge { display:inline-block; border-radius:999px; padding:2px 10px; font-size:12.5px; font-weight:650; white-space:nowrap; }
.badge.covered, .badge.ok { background:var(--green-soft); color:var(--green); }
.badge.missing, .badge.duplicate, .badge.issues { background:var(--red-soft); color:var(--red); }
.badge.pending, .badge.pending_verification { background:var(--amber-soft); color:var(--amber); }
.badge.optional { background:var(--gray-soft); color:var(--muted); }
table { width:100%; border-collapse:collapse; font-size:13.5px; }
th, td { text-align:left; vertical-align:top; border-bottom:1px solid var(--line); padding:10px 9px; }
th { background:#f0f4f8; color:#3e5265; font-size:12.5px; font-weight:650; white-space:nowrap; }
tr:last-child td { border-bottom:0; }
.clause-content { color:var(--muted); font-size:12.5px; margin-top:4px; max-width:420px; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.source-list { list-style:none; padding:0; margin:0; }
.source-list li { margin:0 0 5px; font-size:12.5px; }
.source-list a { color:var(--blue); word-break:break-all; }
.tag { display:inline-block; background:#eef1f4; border-radius:5px; padding:0 6px; font-size:11.5px; color:#4b5e70; margin-right:5px; }
.empty { color:var(--muted); font-size:13px; padding:8px 0; }
details { margin-top:6px; }
summary { cursor:pointer; color:var(--blue); font-size:13px; }
.chips { display:flex; flex-wrap:wrap; gap:8px; }
.chip { border:1px solid #e3b5b0; background:#fff7f6; color:var(--red); border-radius:999px; padding:3px 10px; font-size:12.5px; }
.chip.amber { border-color:#ead18b; background:#fff9e8; color:var(--amber); }
.section-note { color:var(--muted); font-size:13px; margin:0 0 8px; }
footer { max-width:1180px; margin:0 auto; padding:0 20px 40px; color:var(--muted); font-size:12px; }
@media (max-width:760px) { .grid { grid-template-columns:1fr; } .clause-content { max-width:none; } }
"""


def e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def public_url(url: str) -> str:
    """Turn sample:// URLs into links served by this application."""
    if url.startswith("sample://"):
        return "/samples/" + url[len("sample://"):]
    return url


def _link(url: str, label: str | None = None) -> str:
    if not url:
        return '<span class="small">（无 URL）</span>'
    href = public_url(url)
    return f'<a href="{e(href)}" target="_blank" rel="noopener">{e(label or url)}</a>'


def _shell(title: str, body: str, active: str = "") -> str:
    def nav_link(href: str, text: str, key: str) -> str:
        cls = ' class="active"' if active == key else ""
        return f'<a href="{e(href)}"{cls}>{e(text)}</a>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · 技术响应核对</title>
<style>{CSS}</style>
</head>
<body>
<header><div class="wrap">
  <h1>投标技术响应核对</h1>
  <nav>
    {nav_link("/", "响应核对", "check")}
    {nav_link("/response-check", "核对页", "check")}
    {nav_link("/docs", "API 文档", "docs")}
  </nav>
</div></header>
<main>{body}</main>
<footer>本工具只做条款覆盖核对，不替代招标文件与评标口径的最终解释。离线样例使用 <span class="mono">sample://</span> URL。</footer>
</body></html>"""


SAMPLE_PRESETS = [
    {
        "label": "完整样例（含缺项·重复·失效引用）",
        "announcement_list_url": "sample://demo/list.html",
        "project_no": "ZB-2026-001",
        "lot_no": "LOT-A",
        "response_url": "sample://demo/response.html",
    },
    {
        "label": "抓取不完整样例（结论待核实）",
        "announcement_list_url": "sample://demo-incomplete/list.html",
        "project_no": "ZB-2026-002",
        "lot_no": "LOT-B",
        "response_url": "sample://demo-incomplete/response.html",
    },
]


def _preset_href(preset: dict[str, str]) -> str:
    from urllib.parse import urlencode

    params = {key: value for key, value in preset.items() if key != "label"}
    return "/response-check?" + urlencode(params)


def render_form(prefill: dict[str, str] | None = None, error: str = "") -> str:
    prefill = prefill or {}
    values = {
        "announcement_list_url": prefill.get("announcement_list_url", ""),
        "project_no": prefill.get("project_no", ""),
        "lot_no": prefill.get("lot_no", ""),
        "response_url": prefill.get("response_url", ""),
    }
    presets = "".join(
        f'<a class="preset" href="{e(_preset_href(preset))}">{e(preset["label"])}</a>'
        for preset in SAMPLE_PRESETS
    )
    error_html = f'<div class="banner issues"><strong>输入有误</strong><p>{e(error)}</p></div>' if error else ""
    body = f"""
<div class="card">
  <h2>响应核对</h2>
  <p class="lead">输入公告列表 URL、项目编号、标段号和企业响应表 URL。系统会沿公告分页读取原公告与更正，按
  <strong>明确引用且存在</strong>的条款应用更正，再逐条核对当前强制条款是否已被响应表覆盖。</p>
  {error_html}
  <form method="post" action="/response-check">
    <div class="grid">
      <div class="full">
        <label for="announcement_list_url">公告列表 URL</label>
        <input id="announcement_list_url" name="announcement_list_url" type="text" required
          value="{e(values['announcement_list_url'])}"
          placeholder="https://... 或 sample://demo/list.html">
      </div>
      <div>
        <label for="project_no">项目编号</label>
        <input id="project_no" name="project_no" type="text" required
          value="{e(values['project_no'])}" placeholder="例如 ZB-2026-001">
      </div>
      <div>
        <label for="lot_no">标段号</label>
        <input id="lot_no" name="lot_no" type="text" required
          value="{e(values['lot_no'])}" placeholder="例如 LOT-A">
      </div>
      <div class="full">
        <label for="response_url">企业响应表 URL</label>
        <input id="response_url" name="response_url" type="text" required
          value="{e(values['response_url'])}"
          placeholder="https://... 或 sample://demo/response.html">
      </div>
    </div>
    <div class="actions">
      <button type="submit">开始核对</button>
      <span class="small">不联网也可运行：直接使用下方本地样例。</span>
    </div>
  </form>
</div>
<div class="card">
  <h3>本地离线样例</h3>
  <div class="chips">{presets}</div>
  <p class="small" style="margin-top:12px">完整样例覆盖：更正接续替换、旧版本被排除、响应缺项、重复条款编号、失效更正引用。
  不完整样例模拟公告分页与响应页抓取失败，所有依赖其完整性的结论会显示为「待核实」。</p>
</div>
<div class="card">
  <h3>核对规则</h3>
  <ul class="small" style="margin:0; padding-left:18px">
    <li>沿公告列表的分页链接读取全部原公告及更正公告，并只保留匹配项目编号与标段号的记录。</li>
    <li>更正条款只有在<strong>明确引用</strong>某个已存在条款时才替换该条款；未引用或引用不存在的更正不会被采纳。</li>
    <li>当前强制条款才构成要求；被替换的旧版本单独列出，绝不作为当前要求。</li>
    <li>公告链或响应页抓取不完整时，相关结论标为「待核实」，不会把旧版本当成当前要求，也不会把未读到的缺项断言为缺项。</li>
    <li>响应表缺项、重复条款编号、失效更正引用分别列出；每条结论均附公告与响应表来源。</li>
  </ul>
</div>
"""
    return _shell("响应核对", body, "check")


def _stat(value: Any, label: str) -> str:
    return f'<div class="stat"><div class="num">{e(value)}</div><div class="lbl">{e(label)}</div></div>'


def _render_sources(item: dict[str, Any]) -> str:
    entries = item.get("sources") or []
    if not entries:
        return '<span class="small">无来源</span>'
    bits = []
    for source in entries:
        source_type = source.get("type")
        if source_type == "response":
            if source.get("role") == "missing":
                label = "响应表（无对应条款行）"
            else:
                label = f"响应表第 {source.get('row_index')} 行"
            detail = source.get("answer", "")
            bits.append(
                f'<li><span class="tag">响应</span>{_link(source.get("source_url"), label)}'
                f' <span class="small">答复：{e(detail)}</span></li>'
            )
        else:
            role = source.get("role")
            kind = "更正" if source.get("kind") == "correction" else "原公告"
            version = source.get("version") or "版本未标"
            if role == "superseded":
                label = f"旧版本 {version}（已被替换）"
            elif role == "unverified":
                label = f"已读取版本 · {kind} {version}（待核实）"
            else:
                label = f"当前依据 · {kind} {version}"
            extra = " / ".join(filter(None, [source.get("title", ""), source.get("published_at", "")]))
            tag = {"superseded": "旧版", "unverified": "待核实"}.get(role, "公告")
            bits.append(
                f'<li><span class="tag">{e(tag)}</span>'
                f'{_link(source.get("source_url"), label)}'
                f' <span class="small">{e(extra)}</span></li>'
            )
    return '<ul class="source-list">' + "".join(bits) + "</ul>"


def _render_clause_rows(report: dict[str, Any]) -> str:
    clauses = report.get("clauses") or []
    if not clauses:
        return '<tr><td colspan="6" class="empty">没有当前强制条款可核对。</td></tr>'
    rows = []
    for item in clauses:
        status = item.get("status", "")
        answers = item.get("response") or []
        answer_html = "<br>".join(
            f'<span class="small">第 {row["row_index"]} 行：</span>{e(row["answer"] or "（空）")}'
            for row in answers
        ) or '<span class="small">无答复记录</span>'
        references = item.get("references") or []
        ref_html = '<span class="small">无</span>' if not references else ", ".join(
            f'<span class="mono">{e(ref)}</span>' for ref in references
        )
        notes = "".join(f'<div class="small">{e(note)}</div>' for note in item.get("notes", []))
        content = item.get("content") or ""
        rows.append(f"""
<tr>
  <td><strong class="mono">{e(item.get("clause_no"))}</strong>
      <div class="clause-content">{e(content)}</div></td>
  <td>{e(item.get("version") or "未标")}<div class="small">{'强制' if item.get('mandatory') else '非强制'}</div></td>
  <td><span class="badge {e(status)}">{e(item.get("status_label"))}</span>{notes}</td>
  <td>{answer_html}</td>
  <td>{ref_html}</td>
  <td>{_render_sources(item)}</td>
</tr>""")
    return "".join(rows)


def _render_missing(report: dict[str, Any]) -> str:
    missing = report.get("missing") or []
    if missing:
        return '<div class="chips">' + "".join(
            f'<span class="chip">{e(item["clause_no"])} · {e(item["reason"])}</span>'
            for item in missing
        ) + "</div>"
    if not report.get("response_complete", True):
        return '<p class="section-note">响应页抓取不完整，未对缺项作确定性断言；相关条款标为「待核实」。</p>'
    return '<p class="section-note">无缺项。</p>'


def _render_duplicates(report: dict[str, Any]) -> str:
    duplicates = report.get("duplicates") or []
    if not duplicates:
        return '<p class="section-note">无重复条款编号。</p>'
    rows = []
    for duplicate in duplicates:
        entries = "；".join(
            f'第 {row["row_index"]} 行：{row["answer"] or "（空）"}' for row in duplicate.get("rows", [])
        )
        rows.append(
            f'<tr><td class="mono">{e(duplicate["clause_no"])}</td><td>{e(duplicate["count"])}</td>'
            f'<td>{e(entries)}</td><td>{_link(duplicate.get("source_url"))}</td></tr>'
        )
    return (
        '<table><thead><tr><th>条款编号</th><th>出现次数</th><th>各行答复</th><th>来源</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_invalid(report: dict[str, Any]) -> str:
    invalid = report.get("invalid_corrections") or []
    if not invalid:
        return '<p class="section-note">无失效的更正引用。</p>'
    rows = []
    for item in invalid:
        refs = "、".join(item.get("references") or []) or "（未明确引用）"
        rows.append(
            f'<tr><td class="mono">{e(item["clause_no"])}</td><td>{e(refs)}</td>'
            f'<td>{e(item["reason"])}</td>'
            f'<td>{_link(item.get("announcement_url"), item.get("announcement_title") or item.get("announcement_url"))}'
            f'<div class="small">{e(item.get("version") or "")} {e(item.get("published_at") or "")}</div></td></tr>'
        )
    return (
        '<table><thead><tr><th>更正条款</th><th>引用</th><th>处理结果</th><th>来源公告</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_fetch_issues(report: dict[str, Any]) -> str:
    issues = report.get("fetch_issues") or []
    if not issues:
        return '<p class="section-note">公告链与响应页均已完整读取。</p>'
    scopes = {"list": "公告列表", "pagination": "分页", "announcement": "公告详情", "response": "响应表"}
    rows = [
        f'<tr><td>{e(scopes.get(item.get("scope"), item.get("scope")))}</td>'
        f'<td>{e(item.get("message"))}</td><td>{_link(item.get("url"))}</td></tr>'
        for item in issues
    ]
    return (
        '<table><thead><tr><th>范围</th><th>问题</th><th>URL</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_superseded(report: dict[str, Any]) -> str:
    superseded = report.get("superseded") or []
    if not superseded:
        return '<p class="section-note">没有被更正替换的旧版本条款。</p>'
    rows = [
        f'<tr><td class="mono">{e(item["clause_no"])}</td><td>{e(item.get("version") or "未标")}</td>'
        f'<td>{e("强制" if item.get("mandatory") else "非强制")}</td>'
        f'<td>{e(item.get("content") or "")}</td>'
        f'<td>{_link(item.get("source_url"))}<div class="small">{e(item.get("published_at") or "")}</div></td></tr>'
        for item in superseded
    ]
    return (
        '<p class="section-note">以下旧版本均<strong>不作为当前要求</strong>，仅用于追溯更正过程。</p>'
        '<table><thead><tr><th>条款编号</th><th>版本</th><th>强制</th><th>内容</th><th>来源</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_optional(report: dict[str, Any]) -> str:
    optional = report.get("non_mandatory_current") or []
    if not optional:
        return '<p class="section-note">无当前非强制条款。</p>'
    rows = [
        f'<tr><td class="mono">{e(item["clause_no"])}</td><td>{e(item.get("version") or "未标")}</td>'
        f'<td>{e(item.get("content") or "")}</td><td>{_link(item.get("source_url"))}</td></tr>'
        for item in optional
    ]
    return (
        '<table><thead><tr><th>条款编号</th><th>版本</th><th>内容</th><th>来源</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_announcements(report: dict[str, Any]) -> str:
    announcements = report.get("announcements") or []
    if not announcements:
        return '<p class="section-note">没有读取到匹配的公告。</p>'
    rows = []
    for announcement in announcements:
        kind = "更正" if announcement.get("kind") == "correction" else "原公告"
        fetched = "已读取" if announcement.get("fetched") else f"读取失败：{announcement.get('error', '')}"
        rows.append(
            f'<tr><td>{e(kind)}</td><td>{e(announcement.get("version") or "未标")}</td>'
            f'<td>{e(announcement.get("title") or "")}</td>'
            f'<td>{e(announcement.get("published_at") or "")}</td>'
            f'<td>{_link(announcement.get("url"))}</td>'
            f'<td>{e(announcement.get("clause_count", 0))}</td><td>{e(fetched)}</td></tr>'
        )
    pages = report.get("list_pages") or []
    pages_html = "".join(
        f'<li>{_link(page.get("url"))} · 识别 {e(page.get("announcement_count", 0))} 条公告</li>'
        for page in pages
    )
    return (
        '<table><thead><tr><th>类型</th><th>版本</th><th>标题</th><th>日期</th><th>URL</th><th>条款数</th><th>状态</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table>"
        + ('<details><summary>已抓取的公告列表页</summary><ul class="source-list">' + pages_html + "</ul></details>")
    )


def _render_response_rows(report: dict[str, Any]) -> str:
    rows = report.get("response_rows") or []
    if not rows:
        return '<p class="section-note">没有读取到响应行。</p>'
    body = "".join(
        f'<tr><td>{e(row["row_index"])}</td><td class="mono">{e(row["clause_no"])}</td>'
        f'<td>{e(row["answer"] or "（空）")}</td><td>{_link(row.get("source_url"))}</td></tr>'
        for row in rows
    )
    return (
        '<details><summary>展开响应表原始读取结果（' + e(len(rows)) + ' 行）</summary>'
        '<table><thead><tr><th>行</th><th>条款编号</th><th>答复</th><th>来源</th></tr></thead>'
        "<tbody>" + body + "</tbody></table></details>"
    )


def render_result(report: dict[str, Any]) -> str:
    status = report.get("overall_status", "pending_verification")
    banner_class = {"ok": "ok", "issues": "issues", "pending_verification": "pending"}.get(status, "pending")
    summary = report.get("summary") or {}
    request = report.get("request") or {}

    stats = "".join([
        _stat(summary.get("current_mandatory", 0), "当前强制条款"),
        _stat(summary.get("covered", 0), "已覆盖"),
        _stat(summary.get("missing", 0), "缺项"),
        _stat(summary.get("duplicate_clauses", 0), "重复编号条款"),
        _stat(summary.get("invalid_corrections", 0), "失效更正引用"),
        _stat(summary.get("pending_verification", 0), "待核实条款"),
        _stat(summary.get("fetch_issues", 0), "抓取问题"),
    ])

    body = f"""
<div class="banner {banner_class}">
  <strong>{e(report.get("overall_status_label"))}：{e(report.get("message"))}</strong>
  <div class="small" style="margin-top:6px">公告链：{e("完整" if report.get("chain_complete") else "不完整")}
    ｜ 响应页：{e("完整" if report.get("response_complete") else "不完整")}</div>
</div>
<div class="card">
  <h2>核对结果</h2>
  <p class="small">项目编号 <span class="mono">{e(request.get("project_no"))}</span>
    ｜ 标段号 <span class="mono">{e(request.get("lot_no"))}</span></p>
  <p class="small">公告列表：{_link(request.get("announcement_list_url"))}<br>
    响应表：{_link(request.get("response_url"))}</p>
</div>
<div class="stats">{stats}</div>
<div class="card">
  <h3>逐条结论与来源（仅当前强制条款）</h3>
  <table>
    <thead><tr><th>条款</th><th>已读取最新版本</th><th>结论</th><th>响应答复</th><th>引用关系</th><th>来源</th></tr></thead>
    <tbody>{_render_clause_rows(report)}</tbody>
  </table>
</div>
<div class="card">
  <h3>响应表缺项</h3>
  {_render_missing(report)}
</div>
<div class="card">
  <h3>响应表重复编号</h3>
  {_render_duplicates(report)}
</div>
<div class="card">
  <h3>更正引用失效</h3>
  {_render_invalid(report)}
</div>
<div class="card">
  <h3>抓取完整性问题（待核实来源）</h3>
  {_render_fetch_issues(report)}
</div>
<div class="card">
  <h3>已替换的旧版本（不作为当前要求）</h3>
  {_render_superseded(report)}
</div>
<div class="card">
  <h3>当前非强制条款（仅供参考）</h3>
  {_render_optional(report)}
</div>
<div class="card">
  <h3>公告读取记录</h3>
  {_render_announcements(report)}
  <div style="margin-top:10px">{_render_response_rows(report)}</div>
</div>
<div class="card">
  <h3>再次核对</h3>
  <p class="small">使用同一组输入重新核对，或返回修改输入。</p>
  <div class="actions">
    <a class="preset" href="/response-check">修改输入</a>
    <a class="preset" href="/">返回首页</a>
  </div>
</div>
"""
    return _shell("核对结果", body, "check")


def render_error(message: str, prefill: dict[str, str] | None = None) -> str:
    return render_form(prefill=prefill, error=message)
