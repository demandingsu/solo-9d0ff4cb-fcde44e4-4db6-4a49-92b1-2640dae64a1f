# 投标技术响应核对

面向投标专员的 FastAPI 网页：在提交技术响应前，读取招标公告列表（含分页）中的原公告与全部更正公告，按版本重建当前有效条款，并逐条核对当前**强制**条款是否已被企业响应表覆盖。

页面地址：`http://localhost:8000/response-check`（首页 `/` 同样进入核对表单）。

## 功能要点

- 输入：公告列表 URL、项目编号、标段号、企业响应表 URL。
- 沿公告列表分页读取全部原公告与更正公告，并按项目编号/标段号过滤。
- 解析条款编号、版本、强制标记、引用关系、条款内容。
- **更正只替换“明确引用且存在”的条款**：
  - 更正条款没有引用、引用自身不存在、引用不存在的编号时，不进入当前条款集；
  - 失效引用单独列入“更正引用失效”；
  - 被替换的旧版本单独列入“已替换的旧版本”，并明确标注“不作为当前要求”。
- 响应表缺项、重复条款编号、失效更正引用分别在页面中列出。
- 公告链（列表分页/公告详情）或响应页抓取不完整时，依赖其完整性的逐条结论标为**待核实**；此时不会把旧版本当作当前要求，也不会把未读到的条款断言为缺项。
- 每条结论附公告/更正/响应表来源链接，可离线打开样例来源。
- 只有当前强制条款进入核对结果；当前非强制条款单独列出，仅供参考。

## 快速开始（本机，无需联网安装依赖）

依赖已随仓库放在 `.pylib/` 中。

```bash
./run.sh
# 打开 http://localhost:8000/response-check
```

运行测试：

```bash
./test.sh
# 或 PYTHONPATH=.pylib/lib/python3.11/site-packages python3 -m pytest -q
```

## Docker Compose（运行时离线）

```bash
docker compose up --build
# 打开 http://localhost:8000/response-check
```

镜像直接复制 `.pylib/` 中的依赖，构建阶段不执行 `pip install`，因此不需要访问 PyPI；运行阶段只使用镜像内的 `sample://` 样例，完全不访问外部网络。首次构建仍需本机已有所需的基础镜像 `python:3.11-slim`。

## 离线样例

页面上的“本地离线样例”按钮会预填下列输入：

| 样例 | 公告列表 | 项目 / 标段 | 响应表 | 预期 |
| --- | --- | --- | --- | --- |
| 完整样例 | `sample://demo/list.html` | `ZB-2026-001` / `LOT-A` | `sample://demo/response.html` | 整体“需处理” |
| 抓取不完整样例 | `sample://demo-incomplete/list.html` | `ZB-2026-002` / `LOT-B` | `sample://demo-incomplete/response.html` | 整体“待核实” |

完整样例展示：

- 公告列表分两页；更正 v2、v3 按页码与版本顺序读取；
- 条款 `1.2` 被 v2、v3 连续替换，最终当前版本为 v3；v1/v2 作为旧版本列出；
- 响应表缺 `2.2` → 缺项；
- 响应表出现两条 `2.1` → 重复编号；
- 更正 v2 引用不存在的 `9.9`、更正 v3 条款 `3.3` 未明确引用 → 分别列为失效更正引用；
- 条款 `1.3` 为非强制，不作为要求。

抓取不完整样例展示：公告“下一页”不存在、响应表 URL 不存在，所有当前条款结论均为“待核实”，且缺项列表为空（不作错误断言）。

`sample://` 是应用内置的离线协议，例如 `sample://demo/list.html` 映射到 `samples/demo/list.html`；页面来源链接会转换为 `/samples/...` 以便浏览器直接打开。也支持 `http(s)://`（需要网络）和 `file://` 本地文件。

## 支持公告/响应页的常见结构

解析器会按优先级自动选择下列结构之一；接入真实网站时，可直接写适配器或让页面包含这些标记。

**公告列表**

- 嵌入 JSON（`script[type="application/json"]`，id/class 含 `announcement`）：数组或 `{"announcements": [...]}`，字段可用 `project_no`/`lot_no`/`kind`/`version`/`url`/`published_at`/`title` 或对应中文；
- 表格：表头包含“项目”“标段”，可选“公告类型/版本/发布日期/标题”，行内提供公告链接；
- 元素：`li/div.article` 带 `data-project`、`data-lot`、`data-kind`、`data-version`、`data-url` 等属性；
- 分页：`a[rel="next"]`、文本“下一页”、或 `nav.pagination` 中的页码链接。

**公告详情**

- JSON：`script` 块包含 `clauses` 数组（字段 `clause_no`/`version`/`mandatory`/`references`/`content`）；
- 元素：`li/div.clause` 或带 `data-clause-no` 的元素，支持 `data-version`、`data-mandatory`、`data-references`、`data-content`；
- 表格：表头包含“条款编号”和“条款内容”，可选“版本/强制/引用条款”；
- 文本兜底：`条款编号：1.1 版本：v2 强制：是 引用：1.1 内容：...`。

**企业响应表**

- JSON：`script` 块包含 `responses`/`rows` 数组（字段 `clause_no`/`answer`）；
- 元素：`.response-row` 或带 `data-clause-no` 的元素；
- 表格：表头同时包含条款编号列与“答复/响应/应答/回复”列。

## JSON API

`POST /api/response-check`

```bash
curl -s http://localhost:8000/api/response-check \
  -H 'content-type: application/json' \
  -d '{
    "announcement_list_url": "sample://demo/list.html",
    "project_no": "ZB-2026-001",
    "lot_no": "LOT-A",
    "response_url": "sample://demo/response.html"
  }'
```

返回字段包括：

- `overall_status`: `ok` / `issues` / `pending_verification`
- `chain_complete`, `response_complete`
- `clauses`: 逐条结论（`status` 为 `covered` / `missing` / `duplicate` / `pending_verification`）、当前版本、引用关系、`sources`
- `missing`, `duplicates`, `invalid_corrections`
- `superseded`: 被替换旧版本（不作为当前要求）
- `fetch_issues`: 公告链/响应页抓取问题
- `announcements`, `response_rows`, `list_pages`

其他端点：`GET /healthz`、`GET /api/samples`、`GET /docs`（FastAPI 自动文档）。

## 目录结构

```
app/
  main.py       FastAPI 路由与表单/JSON 入口
  checker.py    公告链重建、更正应用、逐条核对
  parsing.py    列表/公告详情/响应表解析
  fetch.py      http(s)、file://、sample:// 抓取
  render.py     无外部资源的服务端 HTML 渲染
  models.py     数据模型
samples/        离线完整与不完整样例
tests/          解析/核对/API 测试
Dockerfile
docker-compose.yml
run.sh / test.sh
```

## 判定边界

- “当前强制条款”= 经全部可见更正替换后仍为强制、且属于本次项目/标段的条款。
- 更正没有明确引用时**不会**新增或替换条款；引用不存在条款时更正被丢弃，并列入失效引用。
- 公告链不完整包括：列表页/分页/公告详情抓取失败、公告详情解析不到条款、更正缺少版本和日期无法排序。响应页不完整包括：抓取失败、无法识别响应表结构、存在缺少条款编号的行。
- 抓取不完整时，当前条款版本与覆盖结论均标记“待核实”；旧版本仍只出现在“已替换的旧版本”区，不参与要求统计。
- 本工具不解释招标文件实质含义，也不判断答复内容是否技术合格，只核对强制条款编号的覆盖关系。
