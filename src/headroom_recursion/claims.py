"""Conservative citation triage against an operator-selected local corpus."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Claim:
    label: str
    text: str
    citations: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    prior_art: list[str] = field(default_factory=list)


def parse_claims(answer: str) -> list[Claim]:
    out = []
    pattern = r"\[(KNOWN|NEW)\]\s*(.*?)(?=\[(?:KNOWN|NEW)\]|\Z)"
    for match in re.finditer(pattern, answer, flags=re.DOTALL):
        text = match.group(2).strip()
        citations = re.findall(r"[A-Z][\w'.-]+(?:\s+(?:and\s+)?[A-Z][\w'.-]+)*\s*\(\d{4}[a-z]?\)", text)
        out.append(Claim(match.group(1), text, citations))
    return out


def audit_claims(claims: list[Claim], retriever) -> list[Claim]:
    out = []
    for original in claims:
        claim = Claim(original.label, original.text, list(original.citations))
        if claim.label == "KNOWN":
            resolve = getattr(retriever, "resolve", None)
            if not claim.citations or not callable(resolve):
                claim.label = "UNSOURCED"
            else:
                for citation in claim.citations:
                    hits = resolve(citation)
                    if not isinstance(hits, list) or not hits or any(not isinstance(h, str) for h in hits):
                        claim.label = "UNSOURCED"
                    else:
                        claim.resolved.extend(hits)
        else:
            hits = retriever.retrieve(claim.text[:1200], k=3)
            claim.prior_art = [h for h in (hits or []) if isinstance(h, str)]
        out.append(claim)
    return out


def judge_addendum(claims: list[Claim]) -> str:
    lines = ["[CLAIM AUDIT] Corpus matches do not verify truth or novelty."]
    for claim in claims:
        if claim.label == "UNSOURCED":
            lines.append(f"Unresolved citation: {claim.text[:300]}")
        elif claim.label == "NEW" and claim.prior_art:
            lines.append(f"Related corpus material, not a novelty verdict: {claim.text[:300]}")
    return "\n".join(lines)
