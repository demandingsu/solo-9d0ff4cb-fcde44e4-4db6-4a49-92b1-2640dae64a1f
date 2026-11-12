"""Data models for the announcement / response cross-check.

The checker deliberately keeps a small, explicit model instead of trying to
mirror every possible announcement site.  Parsers turn pages into these
objects; the checker only reasons about versions, references and responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Clause:
    number: str
    version: str = ""
    mandatory: bool = False
    references: list[str] = field(default_factory=list)
    content: str = ""
    source_url: str = ""
    announcement_title: str = ""
    announcement_kind: str = "original"
    published_at: str = ""
    order: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_no": self.number,
            "version": self.version,
            "mandatory": self.mandatory,
            "references": list(self.references),
            "content": self.content,
            "source_url": self.source_url,
            "announcement_title": self.announcement_title,
            "announcement_kind": self.announcement_kind,
            "published_at": self.published_at,
        }


@dataclass
class AnnouncementRef:
    project_no: str = ""
    lot_no: str = ""
    kind: str = "original"          # original | correction
    version: str = ""
    title: str = ""
    url: str = ""
    published_at: str = ""
    order: int = 0


@dataclass
class Announcement:
    ref: AnnouncementRef
    clauses: list[Clause] = field(default_factory=list)
    fetched: bool = False
    error: str = ""

    @property
    def is_correction(self) -> bool:
        return self.ref.kind == "correction"

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_no": self.ref.project_no,
            "lot_no": self.ref.lot_no,
            "kind": self.ref.kind,
            "version": self.ref.version,
            "title": self.ref.title,
            "url": self.ref.url,
            "published_at": self.ref.published_at,
            "fetched": self.fetched,
            "error": self.error,
            "clause_count": len(self.clauses),
        }


@dataclass
class ResponseRow:
    number: str
    answer: str
    source_url: str
    row_index: int
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_no": self.number,
            "answer": self.answer,
            "source_url": self.source_url,
            "row_index": self.row_index,
        }


@dataclass
class FetchIssue:
    scope: str                      # list | pagination | announcement | response
    url: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"scope": self.scope, "url": self.url, "message": self.message}


@dataclass
class InvalidCorrection:
    clause_no: str
    references: list[str]
    reason: str
    announcement_url: str
    announcement_title: str = ""
    version: str = ""
    source_url: str = ""
    published_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_no": self.clause_no,
            "references": list(self.references),
            "reason": self.reason,
            "announcement_url": self.announcement_url,
            "announcement_title": self.announcement_title,
            "version": self.version,
            "source_url": self.source_url,
            "published_at": self.published_at,
        }
