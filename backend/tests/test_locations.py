import pytest

from app.parsing.locations import country_code, eligible_places, parse_places
from ingestion.normalize import job_places


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Remote - USA", ["US"]),
        ("United States (Remote)", ["US"]),
        ("San Francisco, CA, US; Remote, US", ["US"]),
        ("Austin, TX", ["US"]),
        ("Remote, Canada; Remote, United States", ["CA", "US"]),
        ("Toronto, ON", ["CA"]),
        ("Canada - Remote (ON, AB, BC, or NS Only)", ["CA"]),
        ("Remote UK", ["GB"]),
        ("Republic of Ireland (Remote)", ["IE"]),
        ("Remote - India", ["IN"]),
        ("Worldwide", ["WORLDWIDE"]),
        ("Anywhere in EMEA", ["EMEA"]),  # "anywhere in X" means X
        ("LATAM (South America)", ["LATAM"]),  # not the US
        ("Europe, USA, Canada", ["EUROPE", "US", "CA"]),
        ("Remote", []),
        ("Distributed", []),
        ("join us", []),  # lower-case "us" is a word, not a country
        (None, []),
    ],
)
def test_parse_places(text: str | None, expected: list[str]) -> None:
    assert parse_places(text) == expected


def test_eligible_places_include_worldwide_and_regions() -> None:
    assert set(eligible_places("IN")) == {"IN", "WORLDWIDE", "APAC"}
    assert {"DE", "WORLDWIDE", "EUROPE", "EMEA"} <= set(eligible_places("DE"))
    assert {"BR", "LATAM", "AMERICAS"} <= set(eligible_places("BR"))


def test_country_code_from_resume_location() -> None:
    assert country_code("Pune, Maharashtra, India") == "IN"
    assert country_code("Seattle, WA") == "US"
    assert country_code("github.com/someone") is None


@pytest.mark.parametrize(
    ("location", "title", "expected"),
    [
        ("Remote - Brazil", "Engineer", ["BR"]),
        ("Remote", "Staff AI Engineer | USA | Remote", ["US"]),  # from a tagged title segment
        ("Remote", "Software Engineer, Asia Pacific Payments", []),  # a team, not a place
        (None, "Backend Engineer (Remote - Canada)", ["CA"]),
    ],
)
def test_job_places(location: str | None, title: str, expected: list[str]) -> None:
    assert job_places(location, title) == expected


def test_worldwide_location_counts_as_remote() -> None:
    from ingestion.models import RawJob
    from ingestion.normalize import is_remote

    job = RawJob(source="greenhouse", source_id="x:1", url="u", title="Engineer", company="X",
                 location="Worldwide", description_html="<p>x</p>", posted_at=None)  # fmt: skip
    assert is_remote(job)
