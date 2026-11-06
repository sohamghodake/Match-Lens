"""Resume date strings ("Mar 2021", "03/2021", "2019", "Present") and experience totals.

The LLM copies dates as written; this module turns them into "YYYY-MM" / "YYYY" /
"present" and computes total experience, because LLMs are unreliable at date arithmetic.
"""

import re
from dataclasses import dataclass
from datetime import date

PRESENT = "present"

MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
SEASONS = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}
PRESENT_WORDS = re.compile(
    r"^(present|current(ly)?|now|today|ongoing|till date|to date|till now|date)$", re.I
)

_YEAR = r"((?:19|20)\d{2})"
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"^{_YEAR}[-/.](\d{{1,2}})$"), "ym"),  # 2021-03, 2021/3
    (re.compile(rf"^(\d{{1,2}})[-/.]{_YEAR}$"), "my"),  # 03/2021, 3-2021
    (re.compile(rf"^([a-z]+)\.?,?\s*'?{_YEAR}$", re.I), "namey"),  # Mar 2021, March, 2021
    (re.compile(r"^([a-z]+)\.?\s*'(\d{2})$", re.I), "namey2"),  # Mar '21
    (re.compile(rf"^{_YEAR}$"), "y"),
]


@dataclass(frozen=True)
class YearMonth:
    year: int
    month: int | None  # None when only the year is known

    def __str__(self) -> str:
        return f"{self.year}" if self.month is None else f"{self.year}-{self.month:02d}"


def parse_date(value: str | None) -> YearMonth | str | None:
    """Return a YearMonth, the string "present", or None if the value isn't a date."""
    if value is None:
        return None
    text = value.strip().strip(".,()").strip()
    if not text:
        return None
    if PRESENT_WORDS.match(text):
        return PRESENT
    for pattern, kind in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        if kind == "y":
            return YearMonth(int(match[1]), None)
        if kind == "ym":
            year, month = int(match[1]), int(match[2])
        elif kind == "my":
            month, year = int(match[1]), int(match[2])
        else:
            name = match[1].lower()
            year = int(match[2]) if kind == "namey" else 2000 + int(match[2])
            if name in SEASONS:
                return YearMonth(year, SEASONS[name])
            if name not in MONTHS:
                return None
            month = MONTHS[name]
        return YearMonth(year, month) if 1 <= month <= 12 else None
    return None


def normalize_date(value: str | None) -> str | None:
    """ "Mar 2021" -> "2021-03", "2019" -> "2019", "Currently" -> "present"; else None."""
    parsed = parse_date(value)
    return None if parsed is None else str(parsed)


def _month_index(value: YearMonth | str, today: date) -> int:
    if value == PRESENT:
        return today.year * 12 + today.month - 1
    assert isinstance(value, YearMonth)
    # Year-only dates count from mid-year, so "2019 - 2021" is about two years, not three.
    return value.year * 12 + (value.month or 6) - 1


def total_years(ranges: list[tuple[str | None, str | None]], today: date | None = None) -> float:
    """Total experience in years, counting overlapping ranges once (two jobs at once,
    or a promotion listed as a separate role, shouldn't double-count).

    Months are inclusive ("Jan 2020 - Mar 2020" is 3 months). Ranges without a
    parseable start are skipped; a missing end counts as a single month.
    """
    today = today or date.today()
    intervals: list[tuple[int, int]] = []
    for start, end in ranges:
        start_date = parse_date(start)
        if start_date is None or start_date == PRESENT:
            continue
        end_date = parse_date(end) or start_date
        first, last = _month_index(start_date, today), _month_index(end_date, today)
        if last >= first:
            intervals.append((first, last))

    months = 0
    current: tuple[int, int] | None = None
    for first, last in sorted(intervals):
        if current is None or first > current[1] + 1:
            if current is not None:
                months += current[1] - current[0] + 1
            current = (first, last)
        else:
            current = (current[0], max(current[1], last))
    if current is not None:
        months += current[1] - current[0] + 1
    return round(months / 12, 1)


_MONTH_NAMES = "|".join(sorted({*MONTHS, *SEASONS}, key=len, reverse=True))
_DATE_TOKEN = (
    rf"(?:\b(?:{_MONTH_NAMES})\.?,?\s*'?\d{{2,4}}"  # Mar 2021, Sept. 2024, Summer '20
    r"|\d{1,2}[/.-](?:19|20)\d{2}"  # 03/2021
    r"|(?:19|20)\d{2}(?:[/.-]\d{1,2})?"  # 2021, 2021-03
    r"|present|current|now)"
)
DATE_RANGE = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*(?:-|–|—|to|until|till)\s*(?P<end>{_DATE_TOKEN})", re.I
)


def find_date_ranges(text: str) -> list[tuple[str, str]]:
    """Every "start - end" date range in free text (used when the LLM is unavailable)."""
    ranges = []
    for match in DATE_RANGE.finditer(text):
        start, end = match["start"], match["end"]
        if parse_date(start) not in (None, PRESENT) and parse_date(end) is not None:
            ranges.append((start, end))
    return ranges
