import pytest

from app.parsing.seniority import infer_seniority, seniority_from_title
from app.parsing.skills import find_known_skills, normalize_skill, normalize_skills


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("JS", "JavaScript"),
        ("ReactJS", "React"),
        ("react.js", "React"),
        ("NextJS", "Next.js"),
        ("Postgres", "PostgreSQL"),
        ("k8s", "Kubernetes"),
        ("golang", "Go"),
        ("Python 3.12", "Python"),
        ("  Tailwind, ", "Tailwind CSS"),
        ("Some Niche Tool", "Some Niche Tool"),  # unknown skills are kept as written
        ("", None),
    ],
)
def test_normalize_skill(raw: str, expected: str | None) -> None:
    assert normalize_skill(raw) == expected


def test_normalize_skills_dedupes_aliases_keeping_order() -> None:
    assert normalize_skills(["JS", "Python", "javascript", "postgres", "PostgreSQL"]) == [
        "JavaScript",
        "Python",
        "PostgreSQL",
    ]


def test_find_known_skills_favours_precision() -> None:
    text = (
        "Built APIs with FastAPI and Postgres, deployed on k8s via GitHub Actions. "
        "Learned C++ and C# at school. Wrote Node.js services. "
        "I'd go to great lengths for the rest of the team; Spring is my favourite season."
    )
    found = find_known_skills(text)
    assert found == [
        "FastAPI",
        "PostgreSQL",
        "Kubernetes",
        "GitHub Actions",
        "C++",
        "C#",
        "Node.js",
    ]
    for word in ("Go", "REST APIs", "Spring"):
        assert word not in found


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Software Engineer", "senior"),
        ("Sr. Data Analyst", "senior"),
        ("Staff Software Engineer", "lead"),
        ("Senior Engineering Manager", "lead"),
        ("Engineering Lead", "lead"),
        ("Software Engineering Intern", "intern"),
        ("Junior Web Developer (Contract)", "junior"),
        ("Software Engineer III", "senior"),
        ("Data Scientist", None),
        ("Leader in nothing", None),
    ],
)
def test_seniority_from_title(title: str, expected: str | None) -> None:
    assert seniority_from_title(title) == expected


def test_infer_seniority_prefers_title_then_years() -> None:
    assert infer_seniority("Staff Engineer", 3, only_internships=False) == "lead"
    assert infer_seniority("Data Scientist", 1.5, only_internships=False) == "junior"
    assert infer_seniority("Data Scientist", 4, only_internships=False) == "mid"
    assert infer_seniority("Data Scientist", 8, only_internships=False) == "senior"
    assert infer_seniority(None, 0, only_internships=True) == "intern"
