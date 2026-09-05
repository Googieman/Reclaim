"""Deterministic retrieval from a reviewed, versioned documentation allowlist."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9]{3,}")
ALIASES = {
    "verify": "verification",
    "verified": "verification",
    "webhooks": "webhook",
    "actions": "action",
    "payments": "payment",
}
STOPWORDS = frozenset(
    {
        "about",
        "and",
        "are",
        "can",
        "how",
        "is",
        "the",
        "what",
        "when",
        "where",
        "which",
        "with",
        "you",
    }
)


@dataclass(frozen=True, slots=True)
class DocumentationPassage:
    source_id: str
    title: str
    path: str
    text: str

    @property
    def prompt_text(self) -> str:
        return f"[{self.source_id}] {self.title}: {self.text}"


class DocumentationRetriever:
    def __init__(
        self,
        *,
        document_version: str,
        passages: tuple[DocumentationPassage, ...],
    ) -> None:
        if not document_version.strip() or not passages:
            raise ValueError("reviewed documentation index is incomplete")
        if len({passage.source_id for passage in passages}) != len(passages):
            raise ValueError("documentation source IDs must be unique")
        self.document_version = document_version
        self.passages = passages

    @classmethod
    def from_default_index(cls) -> DocumentationRetriever:
        path = Path(__file__).resolve().parents[3] / "docs" / "help" / "index.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        passages = tuple(DocumentationPassage(**item) for item in payload["passages"])
        return cls(document_version=str(payload["document_version"]), passages=passages)

    def search(
        self,
        question: str,
        *,
        limit: int = 3,
        max_input_chars: int = 8_192,
    ) -> tuple[DocumentationPassage, ...]:
        terms = {
            _canonical(term)
            for term in TOKEN.findall(question.lower())
            if term not in STOPWORDS
        }
        if not terms:
            return ()
        ranked: list[tuple[int, DocumentationPassage]] = []
        for passage in self.passages:
            haystack = {_canonical(term) for term in TOKEN.findall(passage.prompt_text.lower())}
            score = len(terms.intersection(haystack))
            if score:
                ranked.append((score, passage))
        ranked.sort(key=lambda item: (-item[0], item[1].source_id))
        selected: list[DocumentationPassage] = []
        used = 0
        for _, passage in ranked[:limit]:
            if selected and used + len(passage.prompt_text) > max_input_chars:
                continue
            selected.append(passage)
            used += len(passage.prompt_text)
        return tuple(selected)

    def by_id(self, source_id: str) -> DocumentationPassage | None:
        return next((passage for passage in self.passages if passage.source_id == source_id), None)


def _canonical(term: str) -> str:
    return ALIASES.get(term, term.removesuffix("s"))


__all__ = ["DocumentationPassage", "DocumentationRetriever"]
