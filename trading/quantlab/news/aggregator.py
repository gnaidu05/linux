"""Collect, deduplicate, and tag headlines.

Scope, stated plainly: this module groups reading material. It tags a headline
with an asset when one of that asset's configured keywords appears in the title,
deduplicates stories that several outlets ran with near-identical wording, and
keeps every source and link so you can go read the original.

It assigns no sentiment, no polarity, and no score. That omission is
deliberate. Published research on headline sentiment as a price predictor finds
effects that are small, unstable across periods, and mostly gone after costs at
retail speed — and a keyword tagger in a local toolkit is far weaker than the
methods in that research. Any number this module emitted about "bullishness"
would be a number you could not act on, so it does not emit one. The counts
below are counts of articles, and mean only that.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .models import Headline

AssetKeywords = dict[str, list[str]]


def tag_assets(headline: Headline, keywords: AssetKeywords) -> Headline:
    """Return a copy of ``headline`` tagged with every asset whose keyword hits.

    Matching is case-insensitive and on whole words, so ``"ETH"`` does not tag a
    story about ethics and ``"BTC"`` does not tag one about BTCUSD-Perp unless
    that string is itself a configured keyword.
    """
    title = headline.title
    hits = tuple(
        sorted(
            asset
            for asset, words in keywords.items()
            if any(re.search(rf"\b{re.escape(w)}\b", title, re.IGNORECASE) for w in words)
        )
    )
    return Headline(
        source=headline.source,
        title=headline.title,
        url=headline.url,
        published_at=headline.published_at,
        assets=hits,
    )


def deduplicate(headlines: list[Headline]) -> tuple[list[Headline], dict[str, list[str]]]:
    """Collapse headlines with identical normalized titles, keeping the earliest.

    Returns the kept headlines and a map from each kept headline's fingerprint
    to the list of sources that also carried the story, so a widely syndicated
    wire piece is visibly one story from many outlets rather than many stories.
    """
    by_fp: dict[str, list[Headline]] = defaultdict(list)
    for h in headlines:
        by_fp[h.fingerprint()].append(h)
    kept: list[Headline] = []
    sources: dict[str, list[str]] = {}
    for fp, group in by_fp.items():
        group.sort(key=lambda h: (h.published_at, h.source))
        kept.append(group[0])
        sources[fp] = sorted({h.source for h in group})
    kept.sort(key=lambda h: (h.published_at, h.source))
    return kept, sources


@dataclass(frozen=True)
class NewsDigest:
    """Organized headlines with their provenance."""

    headlines: list[Headline]
    sources_by_fingerprint: dict[str, list[str]]
    window_start: datetime | None
    window_end: datetime | None

    def by_asset(self) -> dict[str, list[Headline]]:
        out: dict[str, list[Headline]] = defaultdict(list)
        for h in self.headlines:
            for asset in h.assets:
                out[asset].append(h)
        return dict(sorted(out.items()))

    def by_source(self) -> dict[str, list[Headline]]:
        out: dict[str, list[Headline]] = defaultdict(list)
        for h in self.headlines:
            out[h.source].append(h)
        return dict(sorted(out.items()))

    def untagged(self) -> list[Headline]:
        """Headlines no configured keyword matched."""
        return [h for h in self.headlines if not h.assets]

    def report(self) -> str:
        lines = [
            f"{len(self.headlines)} distinct headlines "
            f"from {len(self.by_source())} source(s)",
            "Article counts only. This digest does not score sentiment and makes",
            "no claim that coverage predicts price.",
            "",
        ]
        for asset, items in self.by_asset().items():
            lines.append(f"{asset}  ({len(items)} article(s))")
            for h in items:
                carried = self.sources_by_fingerprint[h.fingerprint()]
                also = f"  [also: {', '.join(s for s in carried if s != h.source)}]" if len(carried) > 1 else ""
                lines.append(
                    f"  {h.published_at:%Y-%m-%d %H:%M}  {h.source}: {h.title}{also}"
                )
                lines.append(f"      {h.url}")
        untagged = self.untagged()
        if untagged:
            lines.extend(["", f"untagged ({len(untagged)})"])
            for h in untagged:
                lines.append(f"  {h.source}: {h.title}")
                lines.append(f"      {h.url}")
        return "\n".join(lines)


def aggregate(headlines: list[Headline], keywords: AssetKeywords) -> NewsDigest:
    """Tag, deduplicate, and organize a batch of headlines."""
    tagged = [tag_assets(h, keywords) for h in headlines]
    kept, sources = deduplicate(tagged)
    return NewsDigest(
        headlines=kept,
        sources_by_fingerprint=sources,
        window_start=kept[0].published_at if kept else None,
        window_end=kept[-1].published_at if kept else None,
    )
