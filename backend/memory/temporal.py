import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from backend.core.utils.timezone import VANCOUVER_TZ, now_vancouver
from backend.core.logging import get_logger

_log = get_logger("memory.temporal")

KOREAN_MONTHS = {
    "1월": 1, "2월": 2, "3월": 3, "4월": 4, "5월": 5, "6월": 6,
    "7월": 7, "8월": 8, "9월": 9, "10월": 10, "11월": 11, "12월": 12
}

KOREAN_DATE_PATTERN = re.compile(
    r'(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일'
)

KOREAN_DAY_ONLY_PATTERN = re.compile(
    r'(?<![0-9월])(\d{1,2})일(?!\s*전)'
)

KOREAN_RELATIVE_PATTERNS = {
    r'오늘': lambda: (now_vancouver().date(), now_vancouver().date()),
    r'어제': lambda: ((now_vancouver() - timedelta(days=1)).date(),
                      (now_vancouver() - timedelta(days=1)).date()),
    r'그저[께게]': lambda: ((now_vancouver() - timedelta(days=2)).date(),
                           (now_vancouver() - timedelta(days=2)).date()),
    r'지난\s*주': lambda: ((now_vancouver() - timedelta(days=7)).date(),
                          now_vancouver().date()),
    r'지난\s*(\d+)\s*일': None,
    r'(\d+)\s*일\s*전': None,
}

ENGLISH_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
    "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12
}

ENGLISH_DATE_PATTERN = re.compile(
    r'(january|february|march|april|may|june|july|august|september|october|november|december|'
    r'jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?',
    re.IGNORECASE
)

ISO_DATE_PATTERN = re.compile(r'(\d{4})-(\d{2})-(\d{2})')

ENGLISH_RELATIVE_PATTERNS = {
    r'today': lambda: (now_vancouver().date(), now_vancouver().date()),
    r'yesterday': lambda: ((now_vancouver() - timedelta(days=1)).date(),
                           (now_vancouver() - timedelta(days=1)).date()),
    r'last\s+week': lambda: ((now_vancouver() - timedelta(days=7)).date(),
                             now_vancouver().date()),
    r'(\d+)\s+days?\s+ago': None,
}

def parse_temporal_query(query: str) -> Optional[Dict[str, Any]]:
    query_lower = query.lower()

    result = _parse_korean_date(query)
    if result:
        _log.debug("temporal parsed", query=query[:50], result_type=result["type"])
        return result

    result = _parse_korean_relative(query_lower)
    if result:
        _log.debug("temporal parsed", query=query[:50], result_type=result["type"])
        return result

    result = _parse_english_date(query_lower)
    if result:
        _log.debug("temporal parsed", query=query[:50], result_type=result["type"])
        return result

    result = _parse_english_relative(query_lower)
    if result:
        _log.debug("temporal parsed", query=query[:50], result_type=result["type"])
        return result

    result = _parse_iso_date(query)
    if result:
        _log.debug("temporal parsed", query=query[:50], result_type=result["type"])
        return result

    return None

def _parse_korean_date(query: str) -> Optional[Dict[str, Any]]:
    match = KOREAN_DATE_PATTERN.search(query)
    if match:
        year = int(match.group(1)) if match.group(1) else now_vancouver().year
        month = int(match.group(2))
        day = int(match.group(3))
        _log.debug("korean date matched", year=year, month=month, day=day)
    else:

        day_match = KOREAN_DAY_ONLY_PATTERN.search(query)
        if not day_match:
            return None

        now = now_vancouver()
        year = now.year
        month = now.month
        day = int(day_match.group(1))

        if day > now.day:
            if month == 1:
                month = 12
                year -= 1
            else:
                month -= 1

        _log.debug("korean day-only matched", year=year, month=month, day=day)

    try:
        date = datetime(year, month, day).date()

        if date > now_vancouver().date():
            if match:
                date = datetime(year - 1, month, day).date()

        return _build_exact_filter(date)
    except ValueError:
        return None

def _parse_korean_relative(query: str) -> Optional[Dict[str, Any]]:
    for pattern, handler in KOREAN_RELATIVE_PATTERNS.items():
        if handler is None:
            continue
        if re.search(pattern, query):
            from_date, to_date = handler()
            if from_date == to_date:
                return _build_exact_filter(from_date)
            return _build_range_filter(from_date, to_date)

    match = re.search(r'지난\s*(\d+)\s*일', query)
    if match:
        days = int(match.group(1))
        from_date = (now_vancouver() - timedelta(days=days)).date()
        to_date = now_vancouver().date()
        return _build_range_filter(from_date, to_date)

    match = re.search(r'(\d+)\s*일\s*전', query)
    if match:
        days = int(match.group(1))
        date = (now_vancouver() - timedelta(days=days)).date()
        return _build_exact_filter(date)

    return None

def _parse_english_date(query: str) -> Optional[Dict[str, Any]]:
    match = ENGLISH_DATE_PATTERN.search(query)
    if not match:
        return None

    month_str = match.group(1).lower()
    month = ENGLISH_MONTHS.get(month_str)
    day = int(match.group(2))
    year = now_vancouver().year

    if not month:
        return None

    try:
        date = datetime(year, month, day).date()
        return _build_exact_filter(date)
    except ValueError:
        return None

def _parse_english_relative(query: str) -> Optional[Dict[str, Any]]:
    for pattern, handler in ENGLISH_RELATIVE_PATTERNS.items():
        if handler is None:
            continue
        if re.search(pattern, query, re.IGNORECASE):
            from_date, to_date = handler()
            if from_date == to_date:
                return _build_exact_filter(from_date)
            return _build_range_filter(from_date, to_date)

    match = re.search(r'(\d+)\s+days?\s+ago', query, re.IGNORECASE)
    if match:
        days = int(match.group(1))
        date = (now_vancouver() - timedelta(days=days)).date()
        return _build_exact_filter(date)

    return None

def _parse_iso_date(query: str) -> Optional[Dict[str, Any]]:
    match = ISO_DATE_PATTERN.search(query)
    if not match:
        return None

    try:
        date = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3))
        ).date()
        return _build_exact_filter(date)
    except ValueError:
        return None

def _build_exact_filter(date) -> Dict[str, Any]:
    date_str = date.isoformat()
    next_day = (datetime.combine(date, datetime.min.time()) + timedelta(days=1)).date()

    return {
        "type": "exact",
        "date": date_str,
        "date_end": next_day.isoformat(),
        "chroma_filter": None
    }

def _build_range_filter(from_date, to_date) -> Dict[str, Any]:
    end_date = (datetime.combine(to_date, datetime.min.time()) + timedelta(days=1)).date()

    return {
        "type": "range",
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "date_end": end_date.isoformat(),
        "chroma_filter": None
    }

def boost_temporal_score(
    base_score: float,
    memory_date: str,
    temporal_filter: Optional[Dict[str, Any]],
    boost_factor: float = 0.4
) -> float:

    if not temporal_filter or not memory_date:
        return base_score

    score_before = base_score

    try:

        mem_date = memory_date[:10]

        if temporal_filter["type"] == "exact":
            target_date = temporal_filter["date"]
            if mem_date == target_date:

                score_after = base_score * (1 - boost_factor) + 1.0 * boost_factor
                _log.debug("temporal boost", score_before=round(score_before, 3), score_after=round(score_after, 3))
                return score_after

        elif temporal_filter["type"] == "range":
            from_date = temporal_filter["from"]
            to_date = temporal_filter["to"]
            if from_date <= mem_date <= to_date:

                score_after = base_score * (1 - boost_factor) + 0.8 * boost_factor
                _log.debug("temporal boost", score_before=round(score_before, 3), score_after=round(score_after, 3))
                return score_after

    except Exception:
        pass

    return base_score

__all__ = [
    "parse_temporal_query",
    "boost_temporal_score",
    "now_vancouver",
    "VANCOUVER_TZ",
]
