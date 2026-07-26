from datetime import datetime, timedelta, timezone

from quantlab.news.aggregator import aggregate, deduplicate, tag_assets
from quantlab.news.models import Headline

T0 = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)

KEYWORDS = {
    "BTC-USD": ["bitcoin", "btc"],
    "ETH-USD": ["ethereum", "eth"],
    "AAPL": ["apple", "aapl"],
}


def hl(source, title, minutes=0, url=None):
    return Headline(source, title, url or f"https://example.invalid/{abs(hash(title)) % 9999}",
                    T0 + timedelta(minutes=minutes))


def test_tagging_is_case_insensitive():
    assert tag_assets(hl("s", "BITCOIN rallies"), KEYWORDS).assets == ("BTC-USD",)
    assert tag_assets(hl("s", "bitcoin rallies"), KEYWORDS).assets == ("BTC-USD",)


def test_tagging_matches_whole_words_only():
    """'eth' must not tag a story about ethics."""
    assert tag_assets(hl("s", "Board debates ethics policy"), KEYWORDS).assets == ()
    assert tag_assets(hl("s", "ETH gas fees fall"), KEYWORDS).assets == ("ETH-USD",)


def test_a_headline_can_carry_several_assets():
    tagged = tag_assets(hl("s", "Bitcoin and Ethereum both slide"), KEYWORDS)
    assert tagged.assets == ("BTC-USD", "ETH-USD")


def test_untagged_headlines_keep_an_empty_asset_tuple():
    assert tag_assets(hl("s", "Central bank holds rates"), KEYWORDS).assets == ()


def test_tagging_preserves_source_title_url_and_time():
    original = hl("wire", "Apple ships", url="https://example.invalid/x")
    tagged = tag_assets(original, KEYWORDS)
    assert (tagged.source, tagged.title, tagged.url, tagged.published_at) == (
        original.source, original.title, original.url, original.published_at
    )


def test_normalized_title_ignores_case_and_punctuation():
    a = hl("a", "Bitcoin ETF flows hit record!")
    b = hl("b", "bitcoin etf flows hit record")
    assert a.normalized_title() == b.normalized_title()
    assert a.fingerprint() == b.fingerprint()


def test_dedupe_keeps_the_earliest_copy_and_records_every_carrier():
    items = [
        hl("wire-b", "Bitcoin ETF flows hit record", minutes=30),
        hl("wire-a", "Bitcoin ETF flows hit record!", minutes=0),
        hl("wire-c", "bitcoin etf flows hit record", minutes=60),
    ]
    kept, sources = deduplicate(items)
    assert len(kept) == 1
    assert kept[0].source == "wire-a"
    assert sources[kept[0].fingerprint()] == ["wire-a", "wire-b", "wire-c"]


def test_dedupe_keeps_genuinely_different_stories():
    kept, _ = deduplicate([hl("a", "Story one"), hl("b", "Story two")])
    assert len(kept) == 2


def test_digest_groups_by_asset_and_by_source():
    digest = aggregate(
        [
            hl("wire-a", "Bitcoin rallies", 0),
            hl("wire-b", "Ethereum upgrade lands", 10),
            hl("wire-a", "Apple guidance trimmed", 20),
        ],
        KEYWORDS,
    )
    assert set(digest.by_asset()) == {"BTC-USD", "ETH-USD", "AAPL"}
    assert set(digest.by_source()) == {"wire-a", "wire-b"}
    assert len(digest.by_source()["wire-a"]) == 2


def test_digest_surfaces_untagged_headlines_rather_than_dropping_them():
    digest = aggregate([hl("a", "Bitcoin rallies"), hl("b", "Rates unchanged")], KEYWORDS)
    assert [h.title for h in digest.untagged()] == ["Rates unchanged"]
    assert len(digest.headlines) == 2


def test_digest_window_spans_first_to_last_publication():
    digest = aggregate([hl("a", "One", 0), hl("b", "Two", 90)], KEYWORDS)
    assert digest.window_start == T0
    assert digest.window_end == T0 + timedelta(minutes=90)


def test_empty_input_produces_an_empty_digest():
    digest = aggregate([], KEYWORDS)
    assert digest.headlines == []
    assert digest.window_start is None
    assert digest.by_asset() == {}


def test_report_links_every_headline():
    items = [hl("a", "Bitcoin rallies"), hl("b", "Rates unchanged")]
    text = aggregate(items, KEYWORDS).report()
    for h in items:
        assert h.url in text


def test_report_states_that_it_does_not_predict_price():
    text = aggregate([hl("a", "Bitcoin rallies")], KEYWORDS).report()
    assert "does not score sentiment" in text
    assert "no claim that coverage predicts price" in text


def test_digest_exposes_no_sentiment_or_score_field():
    """Guard against a scoring field being added without a stated method."""
    digest = aggregate([hl("a", "Bitcoin rallies")], KEYWORDS)
    banned = ("sentiment", "score", "polarity", "bullish", "bearish", "prediction")
    fields = set(vars(digest)) | set(vars(digest.headlines[0]))
    for name in fields:
        assert not any(b in name.lower() for b in banned), f"unexpected field {name!r}"
