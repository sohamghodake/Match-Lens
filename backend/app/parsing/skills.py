"""Skill normalization, shared by resume parsing, job ingestion, matching and ATS scoring.

Both sides of every comparison go through `normalize_skills`, so "JS" on a resume and
"JavaScript" in a job posting count as the same skill.
"""

import re
from collections.abc import Iterable

# canonical name -> aliases (matched case-insensitively; the canonical name itself is
# always an alias). Extend freely; keep canonical names as the industry spells them.
CANONICAL_SKILLS: dict[str, tuple[str, ...]] = {
    # Languages
    "Python": ("python3", "py"),
    "JavaScript": ("js", "java script", "ecmascript", "es6", "es2015"),
    "TypeScript": ("ts",),
    "Java": ("java 8", "java 11", "java 17", "java 21"),
    "Kotlin": (),
    "Scala": (),
    "Go": ("golang",),
    "Rust": (),
    "C": (),
    "C++": ("cpp", "c plus plus"),
    "C#": ("c sharp", "csharp"),
    "Ruby": (),
    "PHP": (),
    "Swift": (),
    "Objective-C": ("objective c", "objc"),
    "R": (),
    "SQL": ("structured query language",),
    "Bash": ("shell", "shell scripting", "bash scripting", "sh"),
    "Elixir": (),
    "Dart": (),
    "HTML": ("html5",),
    "CSS": ("css3",),
    # Frontend
    "React": ("reactjs", "react.js", "react js"),
    "React Native": ("react-native",),
    "Next.js": ("nextjs", "next js", "next"),
    "Vue.js": ("vue", "vuejs", "vue js"),
    "Nuxt": ("nuxt.js", "nuxtjs"),
    "Angular": ("angularjs", "angular.js", "angular 2+"),
    "Svelte": ("sveltekit",),
    "Redux": ("redux toolkit",),
    "Tailwind CSS": ("tailwind", "tailwindcss"),
    "Sass": ("scss",),
    "Webpack": (),
    "Vite": (),
    "Figma": (),
    "jQuery": ("jquery",),
    # Backend frameworks
    "Node.js": ("node", "nodejs", "node js"),
    "Express": ("express.js", "expressjs"),
    "NestJS": ("nest.js", "nest"),
    "Django": (),
    "Django REST Framework": ("drf", "django rest"),
    "Flask": (),
    "FastAPI": ("fast api",),
    "Spring Boot": ("springboot", "spring-boot"),
    "Spring": ("spring framework",),
    "Ruby on Rails": ("rails", "ror"),
    "Laravel": (),
    ".NET": ("dotnet", "asp.net", ".net core", "asp.net core"),
    "GraphQL": (),
    "gRPC": ("grpc",),
    "REST APIs": ("rest", "restful", "rest api", "restful apis", "restful api"),
    "Microservices": ("microservice", "micro-services", "microservice architecture"),
    "Celery": (),
    # Data stores
    "PostgreSQL": ("postgres", "postgresql", "psql", "pg"),
    "MySQL": (),
    "SQLite": (),
    "MongoDB": ("mongo",),
    "Redis": (),
    "Elasticsearch": ("elastic search", "elk", "opensearch"),
    "Cassandra": (),
    "DynamoDB": ("dynamo db",),
    "Snowflake": (),
    "BigQuery": ("big query",),
    "pgvector": (),
    # Messaging / data engineering
    "Kafka": ("apache kafka",),
    "RabbitMQ": ("rabbit mq",),
    "Apache Spark": ("spark", "pyspark"),
    "Apache Airflow": ("airflow",),
    "dbt": (),
    "Hadoop": (),
    "ETL": ("elt", "data pipelines"),
    # Cloud / DevOps
    "AWS": ("amazon web services",),
    "Google Cloud": ("gcp", "google cloud platform"),
    "Azure": ("microsoft azure",),
    "Docker": (),
    "Kubernetes": ("k8s", "kube"),
    "Terraform": (),
    "Ansible": (),
    "Helm": (),
    "CI/CD": ("ci cd", "cicd", "continuous integration", "continuous delivery"),
    "GitHub Actions": ("gh actions",),
    "Jenkins": (),
    "GitLab CI": ("gitlab ci/cd",),
    "Linux": ("unix",),
    # Not "GitHub"/"GitLab": those are products (and GitLab is an employer).
    "Git": ("version control",),
    "Nginx": (),
    "Prometheus": (),
    "Grafana": (),
    "Datadog": (),
    "Serverless": (),
    "AWS Lambda": ("lambda",),
    # ML / data science
    "Machine Learning": ("ml",),
    "Deep Learning": ("dl",),
    "PyTorch": ("torch",),
    "TensorFlow": ("tensorflow 2",),
    "Keras": (),
    "scikit-learn": ("sklearn", "scikit learn"),
    "pandas": (),
    "NumPy": ("numpy",),
    "Jupyter": ("jupyter notebook", "jupyter notebooks"),
    "NLP": ("natural language processing",),
    "Computer Vision": (),
    "LLMs": ("llm", "large language models"),
    "Hugging Face": ("huggingface", "transformers"),
    "LangChain": (),
    "Tableau": (),
    "Power BI": ("powerbi",),
    "Statistics": ("statistical analysis",),
    "A/B Testing": ("ab testing", "a/b tests", "experimentation"),
    # Testing
    "Pytest": (),
    "Jest": (),
    "Playwright": (),
    "Cypress": (),
    "Selenium": (),
    "JUnit": (),
    "Unit Testing": ("unit tests", "tdd", "test-driven development"),
    # Mobile
    "Android": (),
    "iOS": ("ios",),
    "Flutter": (),
    # Practices
    "Agile": ("scrum", "kanban"),
    "System Design": ("distributed systems",),
    "Data Structures & Algorithms": ("dsa", "data structures", "algorithms"),
}

_LOOKUP: dict[str, str] = {}
for _canonical, _aliases in CANONICAL_SKILLS.items():
    for _alias in (_canonical, *_aliases):
        _LOOKUP[_alias.lower()] = _canonical

# Too ambiguous to find by plain text search (fallback mode): English words and single
# letters. They are still normalized when the LLM extracts them.
_AMBIGUOUS = {"C", "R", "Go", "Swift", "Rust", "Spring", "Express", "Statistics"}

_WS = re.compile(r"\s+")
_VERSION_SUFFIX = re.compile(r"\s+v?\d+(\.\d+)*$")  # "Python 3.12" -> "Python"


def normalize_skill(raw: str) -> str | None:
    """Map one skill string to its canonical name; unknown skills are kept, tidied."""
    text = _WS.sub(" ", raw).strip().strip(".,;:•·-–—*").strip()
    if not text or len(text) > 60:
        return None
    key = text.lower()
    if key in _LOOKUP:
        return _LOOKUP[key]
    trimmed = _VERSION_SUFFIX.sub("", key)
    if trimmed in _LOOKUP:
        return _LOOKUP[trimmed]
    return text


def normalize_skills(raw_skills: Iterable[str]) -> list[str]:
    """Normalize and dedupe (case-insensitively), keeping first-seen order."""
    seen: set[str] = set()
    result = []
    for raw in raw_skills:
        skill = normalize_skill(raw)
        if skill and skill.lower() not in seen:
            seen.add(skill.lower())
            result.append(skill)
    return result


def _alias_pattern(alias: str) -> str:
    # Word boundaries that also work for names like "C++", "C#", ".NET" and "Node.js".
    return rf"(?<![\w.+#-]){re.escape(alias)}(?![\w+#]|\.\w)"


# Aliases that are also everyday words ("the rest of the team", "guard rails").
_UNSEARCHABLE_ALIASES = {
    "rest", "shell", "next", "node", "nest", "lambda", "rails", "transformers",
    "experimentation", "algorithms", "data structures", "kube", "version control",
}  # fmt: skip

_SEARCHABLE = sorted(
    (
        (alias, canonical)
        for canonical, aliases in CANONICAL_SKILLS.items()
        for alias in (canonical, *aliases)
        # Ambiguous names ("Go") are handled separately; their aliases ("golang") are fine.
        if alias != canonical or canonical not in _AMBIGUOUS
        # Two-letter words (js, ts, py, ml) are too short to search for; "C#" is fine.
        if (len(alias) > 2 or not alias.isalpha()) and alias.lower() not in _UNSEARCHABLE_ALIASES
    ),
    key=lambda pair: -len(pair[0]),
)
_SEARCH_RE = re.compile("|".join(_alias_pattern(a) for a, _ in _SEARCHABLE), re.I)


# Ambiguous names count only when written exactly ("Go", not "go") inside a list of
# skills: followed by a separator ("Go, Python", "Go or Rust"), or the last item after
# one ("Python, Go" at the end of a line). Not "Go-to-market", "Grade: C", or
# "the team; Spring is lovely".
_AMBIGUOUS_RE = re.compile(
    "|".join(rf"(?<![\w.+#-]){re.escape(name)}(?![\w+#-]|\.\w)" for name in _AMBIGUOUS)
)
_SEPARATOR_BEFORE = re.compile(r"(?:[,/|;(:]|\b(?:or|and)|&)\s*$")
_SEPARATOR_AFTER = re.compile(r"^\s*(?:[,/|;)]|(?:or|and)\b|&(?=\s))")
_LIST_END = re.compile(r"^\s*[.)]?\s*$")
_R_AND_D = re.compile(r"\bR\s*&\s*D\b")


def find_known_skills(text: str) -> list[str]:
    """Known skills mentioned anywhere in free text, favouring precision. Used for job
    descriptions and as the resume fallback when the LLM is unavailable."""
    found: list[tuple[int, str]] = []
    for line_start, line in _lines_with_offsets(text):
        plain = [(m.start(), _LOOKUP[m.group(0).lower()]) for m in _SEARCH_RE.finditer(line)]
        found += [(line_start + pos, skill) for pos, skill in plain]
        if not plain:
            continue  # ambiguous names need other skills on the same line
        # Blank out "R&D" (same length, so offsets stay valid) before looking for "R".
        masked = _R_AND_D.sub(lambda m: " " * len(m.group(0)), line)
        for m in _AMBIGUOUS_RE.finditer(masked):
            after = masked[m.end() :]
            if _SEPARATOR_AFTER.match(after) or (
                _LIST_END.match(after) and _SEPARATOR_BEFORE.search(masked[: m.start()])
            ):
                found.append((line_start + m.start(), m.group(0)))
    return normalize_skills(skill for _, skill in sorted(found))


def _lines_with_offsets(text: str) -> Iterable[tuple[int, str]]:
    offset = 0
    for line in text.splitlines(keepends=True):
        yield offset, line
        offset += len(line)
