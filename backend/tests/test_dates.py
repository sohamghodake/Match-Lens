from datetime import date

import pytest

from app.parsing.dates import find_date_ranges, normalize_date, total_years

TODAY = date(2026, 11, 6)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mar 2021", "2021-03"),
        ("March 2021", "2021-03"),
        ("Sept 2024", "2024-09"),
        ("Sept. 2024", "2024-09"),
        ("03/2021", "2021-03"),
        ("3-2021", "2021-03"),
        ("2021-03", "2021-03"),
        ("2021/3", "2021-03"),
        ("Mar '21", "2021-03"),
        ("Summer 2020", "2020-06"),
        ("2019", "2019"),
        ("Present", "present"),
        ("currently", "present"),
        ("Till Date", "present"),
        ("", None),
        (None, None),
        ("13/2021", None),
        ("someday", None),
        ("Foo 2021", None),
    ],
)
def test_normalize_date(raw: str | None, expected: str | None) -> None:
    assert normalize_date(raw) == expected


def test_total_years_month_ranges_are_inclusive() -> None:
    assert total_years([("Jan 2020", "Dec 2020")], TODAY) == 1.0


def test_total_years_merges_overlaps_and_promotions() -> None:
    # Two overlapping jobs, and a promotion listed as a second role at the same company.
    ranges = [("2020-01", "2021-12"), ("2021-06", "2022-12"), ("2023-01", "2023-12")]
    assert total_years(ranges, TODAY) == 4.0


def test_total_years_present_counts_to_today() -> None:
    assert total_years([("2025-11", "present")], TODAY) == 1.1  # Nov 2025..Nov 2026 inclusive


def test_total_years_year_only_counts_from_mid_year() -> None:
    assert total_years([("2019", "2021")], TODAY) == 2.1


def test_total_years_skips_undated_and_backwards_ranges() -> None:
    assert total_years([(None, "2020"), ("2022", "2020"), ("junk", "present")], TODAY) == 0.0


def test_find_date_ranges_in_text() -> None:
    text = (
        "Backend Engineer, Parcelpoint Jul 2019 – Feb 2022\n"
        "Northbeam — Staff Engineer (2021–Present)\n"
        "Brightwave | 07/2023 - present\n"
        "Scored 2019 points, not a range"
    )
    assert find_date_ranges(text) == [
        ("Jul 2019", "Feb 2022"),
        ("2021", "Present"),
        ("07/2023", "present"),
    ]
