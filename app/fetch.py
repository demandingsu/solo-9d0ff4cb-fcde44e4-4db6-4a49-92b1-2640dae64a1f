"""URL fetching that works online (http/https) and offline (sample://, file://)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

import httpx


@dataclass
class FetchedPage:
    url: str
    final_url: str
    text: str
    content_type: str = ""


class FetchError(RuntimeError):
    pass


class Fetcher:
    """Fetch pages and cache them for one check run.

    ``sample://demo/list.html`` resolves to ``<samples_root>/demo/list.html``.
    This keeps Docker Compose fully usable without network access.
    """

    def __init__(self, samples_root: str | os.PathLike[str] | None = None, timeout: float = 10.0):
        self.samples_root = Path(samples_root) if samples_root else None
        self.timeout = timeout
        self._cache: dict[str, FetchedPage] = {}

    def fetch(self, url: str) -> FetchedPage:
        if url in self._cache:
            return self._cache[url]
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme == "sample":
            page = self._fetch_sample(url, parts)
        elif scheme == "file":
            page = self._fetch_file(url, parts)
        elif scheme in ("http", "https"):
            page = self._fetch_http(url)
        else:
            raise FetchError(f"不支持的 URL 协议：{scheme or '（无）'}（{url}）")
        self._cache[url] = page
        return page

    def _fetch_sample(self, url: str, parts) -> FetchedPage:
        if self.samples_root is None:
            raise FetchError("未配置本地样例目录")
        if parts.netloc:
            relative = Path(unquote(parts.netloc)) / unquote(parts.path.lstrip("/"))
        else:
            relative = Path(unquote(parts.path.lstrip("/")))
        path = (self.samples_root / relative).resolve()
        self._ensure_in_samples(path)
        if not path.is_file():
            raise FetchError(f"样例文件不存在：{path.name}")
        return FetchedPage(url=url, final_url=url,
                           text=path.read_text(encoding="utf-8"),
                           content_type="text/html; charset=utf-8")

    def _fetch_file(self, url: str, parts) -> FetchedPage:
        path = Path(url2pathname(parts.path)).resolve()
        if not path.is_file():
            raise FetchError(f"本地文件不存在：{path.name}")
        return FetchedPage(url=url, final_url=url,
                           text=path.read_text(encoding="utf-8"),
                           content_type="text/html; charset=utf-8")

    def _fetch_http(self, url: str) -> FetchedPage:
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self.timeout,
                headers={"User-Agent": "technical-response-checker/1.0"},
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                if len(response.content) > 8 * 1024 * 1024:
                    raise FetchError("页面内容超过 8MB，已停止读取")
                return FetchedPage(
                    url=url,
                    final_url=str(response.url),
                    text=response.text,
                    content_type=response.headers.get("content-type", ""),
                )
        except FetchError:
            raise
        except httpx.HTTPStatusError as exc:
            raise FetchError(f"HTTP {exc.response.status_code}：{url}") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"抓取失败：{exc.__class__.__name__}：{url}") from exc

    def _ensure_in_samples(self, path: Path) -> None:
        try:
            path.relative_to(self.samples_root.resolve())  # type: ignore[union-attr]
        except ValueError as exc:
            raise FetchError("样例 URL 越界") from exc
