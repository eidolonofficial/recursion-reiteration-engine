"""Local text retrieval. A citation match is not evidence that a claim is true."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, *, k: int = 4) -> list[str]: ...


class CorpusRetriever:
    """A local, deterministic paragraph corpus; no embeddings or remote model.

    Retrieval ranks token overlap. Citation resolution deliberately uses a separate
    exact-substring lookup, never a merely related retrieval hit.
    """
    def __init__(self, texts: list[str] | tuple[str, ...]):
        if not isinstance(texts, (list, tuple)) or any(not isinstance(t, str) for t in texts):
            raise TypeError("texts must be a sequence of strings")
        self.texts = [text.strip() for text in texts if text.strip()]

    @classmethod
    def from_file(cls, path: str | Path, *, max_bytes: int = 5_000_000):
        path = Path(path)
        with path.open("rb") as file:
            data = file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("local corpus exceeds the size limit")
        return cls(re.split(r"\n\s*\n", data.decode("utf-8")))

    def retrieve(self, query: str, *, k: int = 4) -> list[str]:
        if type(k) is not int or k < 1:
            raise ValueError("k must be a positive integer")
        tokens = set(re.findall(r"\w+", query.casefold()))
        scored = [(len(tokens & set(re.findall(r"\w+", text.casefold()))), i, text)
                  for i, text in enumerate(self.texts)]
        return [text for score, _, text in sorted(scored, key=lambda row: (-row[0], row[1]))[:k]
                if score > 0]

    def resolve(self, citation: str) -> list[str]:
        needle = " ".join(citation.casefold().split())
        if not needle:
            return []
        return [text for text in self.texts if needle in " ".join(text.casefold().split())]
