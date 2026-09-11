"""Typed, bounded memory interfaces. Memories are advisory, never proof authority."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from datetime import datetime, timezone


class MemoryContractError(ValueError):
    pass


def wire(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(wire(value).encode("utf-8")).hexdigest()


def bounded_text(value, name="text", maximum=2000, empty=False) -> str:
    if type(value) is not str or len(value) > maximum or (not empty and not value.strip()):
        raise MemoryContractError(f"invalid {name}")
    return value


def integer(value, name="integer", minimum=0, maximum=1000000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise MemoryContractError(f"invalid {name}")
    return value


def fields(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise MemoryContractError("unexpected memory fields")
    return value


def timestamp(value=None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
    bounded_text(value, "timestamp", 40)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timezone required")
        return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except ValueError as exc:
        raise MemoryContractError("invalid timezone-aware timestamp") from exc


@dataclass(frozen=True)
class Principal:
    user: str
    project: str

    def __post_init__(self):
        bounded_text(self.user, "user", 128)
        bounded_text(self.project, "project", 128)


@dataclass(frozen=True)
class MemoryPolicy:
    k: int = 5
    capacity: int = 10000
    summary_chars: int = 800
    packet_chars: int = 8000
    max_queries: int = 4
    max_writes: int = 4
    consolidate_every: int = 12
    batch_size: int = 16
    max_archive_bytes: int = 64000000
    max_source_chars: int = 1000000
    max_pending: int = 20000
    max_records: int = 100000
    allow_private_consolidation: bool = True

    def __post_init__(self):
        for name, lo, hi in (("k", 1, 64), ("capacity", 1, 100000),
                ("summary_chars", 64, 4000), ("packet_chars", 256, 32000),
                ("max_queries", 1, 16), ("max_writes", 1, 16),
                ("consolidate_every", 1, 1000), ("batch_size", 1, 64),
                ("max_archive_bytes", 1024, 1000000000), ("max_source_chars", 64, 10000000),
                ("max_pending", 1, 100000)):
            integer(getattr(self, name), name, lo, hi)
        integer(self.max_records, "max_records", 1, 1000000)
        for name in ("allow_private_consolidation",):
            if type(getattr(self, name)) is not bool:
                raise MemoryContractError(f"{name} must be bool")


@dataclass(frozen=True)
class MemoryModels:
    """Opaque operator-selected identities; no model or weights are downloaded."""
    controller: str | None = None
    selector: str | None = None
    writer: str | None = None
    consolidator: str | None = None

    def __post_init__(self):
        for value in (self.controller, self.selector, self.writer, self.consolidator):
            if value is not None:
                bounded_text(value, "model", 200)


KINDS = {"fact", "decision", "constraint", "failure", "hypothesis", "procedure", "observation"}


def tags(value):
    if (type(value) not in (list, tuple) or len(value) > 8 or
            any(type(t) is not str for t in value) or len(set(value)) != len(value)):
        raise MemoryContractError("invalid tags")
    for t in value:
        bounded_text(t, "tag", 48)
    if {t.casefold() for t in value} & {"holdout", "validation", "confirmation", "restricted"}:
        raise MemoryContractError("restricted evidence cannot enter generation memory")
    return tuple(value)
