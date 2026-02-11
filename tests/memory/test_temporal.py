"""Tests for backend.memory.temporal — temporal query parsing.

Covers Korean and English relative dates, Korean date patterns,
English date patterns, ISO date patterns, and boost_temporal_score.
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from backend.memory.temporal import (
    parse_temporal_query,
    boost_temporal_score,
    _build_exact_filter,
    _build_range_filter,
    _parse_korean_date,
    _parse_korean_relative,
    _parse_english_date,
    _parse_english_relative,
    _parse_iso_date,
    KOREAN_MONTHS,
    ENGLISH_MONTHS,
)
from backend.core.utils.timezone import VANCOUVER_TZ


# ── Helpers ──────────────────────────────────────────────────────────────

def _fixed_now(y: int = 2025, m: int = 3, d: int = 15, h: int = 12):
    """Return a frozen now_vancouver for deterministic tests."""
    return datetime(y, m, d, h, 0, 0, tzinfo=VANCOUVER_TZ)


@pytest.fixture(autouse=True)
def freeze_now():
    """Pin now_vancouver to 2025-03-15 12:00 for every test."""
    with patch("backend.memory.temporal.now_vancouver", return_value=_fixed_now()):
        yield


# ── _build_exact_filter / _build_range_filter ────────────────────────────

class TestBuildFilters:

    def test_build_exact_filter_structure(self):
        d = date(2025, 3, 15)
        result = _build_exact_filter(d)
        assert result["type"] == "exact"
        assert result["date"] == "2025-03-15"
        assert result["date_end"] == "2025-03-16"
        assert result["chroma_filter"] is None

    def test_build_range_filter_structure(self):
        f = date(2025, 3, 10)
        t = date(2025, 3, 15)
        result = _build_range_filter(f, t)
        assert result["type"] == "range"
        assert result["from"] == "2025-03-10"
        assert result["to"] == "2025-03-15"
        assert result["date_end"] == "2025-03-16"
        assert result["chroma_filter"] is None


# ── Korean date parsing ──────────────────────────────────────────────────

class TestKoreanDate:

    def test_full_korean_date_with_year(self):
        result = parse_temporal_query("2024년 1월 15일에 뭐 했어?")
        assert result is not None
        assert result["type"] == "exact"
        assert result["date"] == "2024-01-15"

    def test_korean_date_without_year_past(self):
        """Month/day without year: defaults to current year."""
        result = parse_temporal_query("1월 15일에 뭐 했어?")
        assert result is not None
        assert result["type"] == "exact"
        assert result["date"] == "2025-01-15"

    def test_korean_date_without_year_future_wraps(self):
        """If the parsed date is in the future, wraps to previous year."""
        # now frozen at 2025-03-15. 6월 1일 > today => year - 1
        result = parse_temporal_query("6월 1일에 뭐 했어?")
        assert result is not None
        assert result["date"] == "2024-06-01"

    def test_korean_month_day_formats(self):
        result = parse_temporal_query("3월 10일")
        assert result is not None
        assert result["date"] == "2025-03-10"

    def test_korean_date_invalid_returns_none(self):
        """Invalid date like 2월 31일 returns None."""
        result = parse_temporal_query("2월 31일")
        assert result is None

    def test_korean_day_only_past(self):
        """Day-only like '10일' uses current month if day <= today."""
        result = parse_temporal_query("10일에 뭐 했어?")
        assert result is not None
        assert result["date"] == "2025-03-10"

    def test_korean_day_only_future_wraps_month(self):
        """Day-only like '20일' when day > today rolls back to previous month."""
        result = parse_temporal_query("20일에 뭐 했어?")
        assert result is not None
        # now = March 15, so 20일 > 15 => wraps to Feb
        assert result["date"] == "2025-02-20"

    def test_korean_day_only_january_wraps_year(self):
        """Day-only in January wraps to December of previous year."""
        with patch("backend.memory.temporal.now_vancouver",
                   return_value=_fixed_now(2025, 1, 10)):
            result = parse_temporal_query("15일에 뭐 했어?")
            assert result is not None
            assert result["date"] == "2024-12-15"

    def test_korean_day_only_does_not_trigger_for_days_ago(self):
        """'3일 전' should NOT match the day-only pattern."""
        result = _parse_korean_date("3일 전")
        assert result is None


# ── Korean relative expressions ──────────────────────────────────────────

class TestKoreanRelative:

    def test_today_korean(self):
        result = parse_temporal_query("오늘 뭐 했어?")
        assert result is not None
        assert result["type"] == "exact"
        assert result["date"] == "2025-03-15"

    def test_yesterday_korean(self):
        result = parse_temporal_query("어제 뭐 했어?")
        assert result is not None
        assert result["type"] == "exact"
        assert result["date"] == "2025-03-14"

    def test_day_before_yesterday_korean(self):
        for expr in ["그저께", "그저게"]:
            result = parse_temporal_query(f"{expr} 뭐 했어?")
            assert result is not None
            assert result["date"] == "2025-03-13", f"Failed for {expr}"

    def test_last_week_korean(self):
        result = parse_temporal_query("지난 주에 뭐 했어?")
        assert result is not None
        assert result["type"] == "range"
        assert result["from"] == "2025-03-08"
        assert result["to"] == "2025-03-15"

    def test_last_n_days_korean_via_internal(self):
        """'지난 N일' range pattern (tested via internal fn because the
        Korean date parser takes priority at the top-level)."""
        result = _parse_korean_relative("지난 5일")
        assert result is not None
        assert result["type"] == "range"
        assert result["from"] == "2025-03-10"
        assert result["to"] == "2025-03-15"

    def test_n_days_ago_korean(self):
        result = parse_temporal_query("3일 전에 뭐 했어?")
        assert result is not None
        assert result["type"] == "exact"
        assert result["date"] == "2025-03-12"

    def test_7_days_ago_korean(self):
        result = parse_temporal_query("7일 전에 뭐 했어?")
        assert result is not None
        assert result["date"] == "2025-03-08"


# ── English date parsing ────────────────────────────────────────────────

class TestEnglishDate:

    def test_full_month_name(self):
        result = parse_temporal_query("What did I do on January 15?")
        assert result is not None
        assert result["date"] == "2025-01-15"

    def test_abbreviated_month(self):
        result = parse_temporal_query("What happened on Feb 1st?")
        assert result is not None
        assert result["date"] == "2025-02-01"

    def test_ordinal_suffixes(self):
        for suffix in ["2nd", "3rd", "4th", "21st"]:
            day = int(suffix.rstrip("stndrdth"))
            result = parse_temporal_query(f"March {suffix}")
            assert result is not None
            assert result["date"] == f"2025-03-{day:02d}"

    def test_case_insensitive(self):
        result = parse_temporal_query("MARCH 10")
        assert result is not None
        assert result["date"] == "2025-03-10"

    def test_invalid_english_date_returns_none(self):
        result = parse_temporal_query("February 30")
        assert result is None

    def test_all_english_months_recognized(self):
        for name, num in ENGLISH_MONTHS.items():
            result = _parse_english_date(f"{name} 1")
            assert result is not None, f"Month not recognized: {name}"


# ── English relative expressions ─────────────────────────────────────────

class TestEnglishRelative:

    def test_today(self):
        result = parse_temporal_query("What happened today?")
        assert result is not None
        assert result["date"] == "2025-03-15"

    def test_yesterday(self):
        result = parse_temporal_query("What about yesterday?")
        assert result is not None
        assert result["date"] == "2025-03-14"

    def test_last_week(self):
        result = parse_temporal_query("last week activities")
        assert result is not None
        assert result["type"] == "range"

    def test_n_days_ago_singular(self):
        result = parse_temporal_query("1 day ago")
        assert result is not None
        assert result["date"] == "2025-03-14"

    def test_n_days_ago_plural(self):
        result = parse_temporal_query("5 days ago")
        assert result is not None
        assert result["date"] == "2025-03-10"


# ── ISO date parsing ─────────────────────────────────────────────────────

class TestISODate:

    def test_valid_iso_date(self):
        result = parse_temporal_query("Show memories from 2024-12-25")
        assert result is not None
        assert result["date"] == "2024-12-25"

    def test_iso_date_embedded_in_text(self):
        result = parse_temporal_query("What happened on 2025-01-01 around noon?")
        assert result is not None
        assert result["date"] == "2025-01-01"

    def test_invalid_iso_date(self):
        result = _parse_iso_date("2025-13-01")
        assert result is None

    def test_iso_date_feb_29_non_leap(self):
        result = _parse_iso_date("2025-02-29")
        assert result is None


# ── parse_temporal_query fallback / priority ─────────────────────────────

class TestParseTemporalQueryPriority:

    def test_no_temporal_returns_none(self):
        result = parse_temporal_query("Hello, how are you?")
        assert result is None

    def test_korean_date_takes_priority_over_iso(self):
        """Korean date pattern is checked before ISO."""
        result = parse_temporal_query("3월 15일 이야기")
        assert result is not None
        assert result["date"] == "2025-03-15"

    def test_empty_string(self):
        result = parse_temporal_query("")
        assert result is None

    def test_numbers_only_no_match(self):
        result = parse_temporal_query("12345")
        assert result is None


# ── boost_temporal_score ─────────────────────────────────────────────────

class TestBoostTemporalScore:

    def test_no_filter_returns_base(self):
        assert boost_temporal_score(0.5, "2025-03-15", None) == 0.5

    def test_no_memory_date_returns_base(self):
        tf = {"type": "exact", "date": "2025-03-15"}
        assert boost_temporal_score(0.5, "", tf) == 0.5

    def test_exact_match_boosts(self):
        tf = {"type": "exact", "date": "2025-03-15"}
        boosted = boost_temporal_score(0.5, "2025-03-15T10:00:00", tf, boost_factor=0.4)
        # boosted = 0.5 * 0.6 + 1.0 * 0.4 = 0.3 + 0.4 = 0.7
        assert boosted == pytest.approx(0.7, abs=0.01)

    def test_exact_no_match_returns_base(self):
        tf = {"type": "exact", "date": "2025-03-15"}
        assert boost_temporal_score(0.5, "2025-03-14T10:00:00", tf) == 0.5

    def test_range_match_boosts(self):
        tf = {"type": "range", "from": "2025-03-10", "to": "2025-03-15"}
        boosted = boost_temporal_score(0.5, "2025-03-12T10:00:00", tf, boost_factor=0.4)
        # boosted = 0.5 * 0.6 + 0.8 * 0.4 = 0.3 + 0.32 = 0.62
        assert boosted == pytest.approx(0.62, abs=0.01)

    def test_range_no_match_returns_base(self):
        tf = {"type": "range", "from": "2025-03-10", "to": "2025-03-12"}
        assert boost_temporal_score(0.5, "2025-03-14T10:00:00", tf) == 0.5

    def test_boost_factor_zero_returns_base(self):
        tf = {"type": "exact", "date": "2025-03-15"}
        boosted = boost_temporal_score(0.5, "2025-03-15T00:00:00", tf, boost_factor=0.0)
        assert boosted == pytest.approx(0.5)

    def test_boost_factor_one_full_boost(self):
        tf = {"type": "exact", "date": "2025-03-15"}
        boosted = boost_temporal_score(0.5, "2025-03-15T00:00:00", tf, boost_factor=1.0)
        assert boosted == pytest.approx(1.0)

    def test_malformed_filter_returns_base(self):
        """If temporal_filter has unexpected type, returns base."""
        tf = {"type": "unknown"}
        assert boost_temporal_score(0.5, "2025-03-15", tf) == 0.5

    def test_memory_date_iso_format_truncation(self):
        """Memory dates with full ISO timestamps should work ([:10] truncation)."""
        tf = {"type": "exact", "date": "2025-03-15"}
        boosted = boost_temporal_score(0.3, "2025-03-15T23:59:59+00:00", tf)
        assert boosted > 0.3


# ── Korean months constant ───────────────────────────────────────────────

class TestKoreanMonthsConstant:

    def test_all_twelve_months(self):
        assert len(KOREAN_MONTHS) == 12
        for i in range(1, 13):
            assert f"{i}월" in KOREAN_MONTHS
            assert KOREAN_MONTHS[f"{i}월"] == i
