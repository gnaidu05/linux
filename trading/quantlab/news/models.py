"""Headline records.

A ``Headline`` always carries the source it came from and the URL it came from,
so anything this module surfaces can be opened and read in full. The aggregator
exists to organize reading material, not to summarize it into a number.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Headline:
    """One story from one source."""

    source: str
    title: str
    url: str
    published_at: datetime
    assets: tuple[str, ...] = field(default_factory=tuple)
    """Symbols this headline was tagged with, by keyword match."""

    def normalized_title(self) -> str:
        """Lowercased, punctuation-stripped title, used for dedupe."""
        return _SPACE.sub(" ", _PUNCT.sub(" ", self.title.lower())).strip()

    def fingerprint(self) -> str:
        """Stable identity for dedupe: the normalized title."""
        return hashlib.sha256(self.normalized_title().encode()).hexdigest()[:16]
