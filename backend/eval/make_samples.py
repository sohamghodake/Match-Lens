"""Generate the fictional sample resumes in eval/samples/ and their ground-truth labels.

    python -m eval.make_samples

Each resume and its labels come from the same data below, so the labels can't drift
from the files. The five deliberately differ in the ways real resumes do: one- and
two-column PDFs, a table-based DOCX, contact details in a DOCX page header, title-first
and company-first lines, five date formats, and skill aliases ("JS", "k8s", "Postgres").
All people, companies, emails and phone numbers are made up.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    ListFlowable,
    ListItem,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).parent / "samples"


@dataclass
class Job:
    title: str
    company: str
    location: str
    start_text: str  # as printed on the resume
    end_text: str
    start: str  # expected normalized value
    end: str
    bullets: list[str]


@dataclass
class School:
    degree: str
    field: str | None
    institution: str
    year: str


@dataclass
class Sample:
    slug: str
    kind: str  # "pdf" | "docx"
    layout: str
    name: str
    headline: str
    email: str
    phone: str
    location: str
    linkedin: str | None
    summary: str
    skills: dict[str, list[str]]  # section label -> skills as printed
    jobs: list[Job]
    schools: list[School]
    seniority: str  # expected; judgment calls are noted in `notes`
    expected_skills: list[str]  # normalized names the parser must find
    notes: str = ""
    extra_lines: list[str] = field(default_factory=list)


SAMPLES = [
    Sample(
        slug="alex_chen_backend",
        kind="pdf",
        layout="single column; title and right-aligned dates on one line",
        name="Alex Chen",
        headline="Senior Backend Engineer",
        email="alex.chen@example.com",
        phone="(206) 555-0147",
        location="Seattle, WA",
        linkedin="linkedin.com/in/alexchen-dev",
        summary=(
            "Backend engineer with seven years of experience building high-throughput "
            "payment and logistics APIs in Python and Go. I care about clear service "
            "boundaries, observability and boring, reliable deploys."
        ),
        skills={
            "Languages": ["Python", "Go", "SQL"],
            "Frameworks": ["FastAPI", "Django", "gRPC"],
            "Data & infrastructure": [
                "PostgreSQL",
                "Redis",
                "Kafka",
                "Docker",
                "Kubernetes",
                "AWS",
                "Terraform",
            ],
        },  # fmt: skip
        jobs=[
            Job(
                "Senior Backend Engineer",
                "Ledgerly",
                "Seattle, WA",
                "Mar 2022",
                "Present",
                "2022-03",
                "present",
                [
                    "Led the redesign of the payments ledger service in Python (FastAPI) and "
                    "PostgreSQL, cutting p99 latency from 480 ms to 120 ms.",
                    "Introduced Kafka-based event sourcing for 40M monthly transactions.",
                    "Mentored four engineers and ran the backend interview loop.",
                ],
            ),
            Job(
                "Backend Engineer",
                "Parcelpoint",
                "Remote",
                "Jul 2019",
                "Feb 2022",
                "2019-07",
                "2022-02",
                [
                    "Built route-optimization APIs in Go and gRPC serving 3,000 requests per "
                    "second at peak.",
                    "Moved services from EC2 to Kubernetes on AWS (EKS), managed with Terraform.",
                    "Added Redis caching that reduced primary database load by 35%.",
                ],
            ),
            Job(
                "Software Engineer Intern",
                "Parcelpoint",
                "Seattle, WA",
                "May 2018",
                "Aug 2018",
                "2018-05",
                "2018-08",
                ["Wrote Django admin tooling used daily by warehouse operations staff."],
            ),
        ],  # fmt: skip
        schools=[School("B.S.", "Computer Science", "University of Washington", "2019")],
        seniority="senior",
        expected_skills=[
            "Python",
            "Go",
            "SQL",
            "FastAPI",
            "Django",
            "gRPC",
            "PostgreSQL",
            "Redis",
            "Kafka",
            "Docker",
            "Kubernetes",
            "AWS",
            "Terraform",
        ],  # fmt: skip
    ),
    Sample(
        slug="maria_gonzalez_data",
        kind="pdf",
        layout="two columns: sidebar (contact, skills, education) beside experience",
        name="Maria Gonzalez",
        headline="Data Scientist",
        email="maria.gonzalez@example.com",
        phone="+1 512.555.0198",
        location="Austin, TX",
        linkedin="linkedin.com/in/maria-gonzalez-ds",
        summary=(
            "Data scientist working on clinical risk models and experimentation. I turn "
            "messy operational data into models that people actually use, and I like "
            "explaining the results to non-technical teams."
        ),
        skills={
            "Skills": [
                "Python",
                "SQL",
                "pandas",
                "scikit-learn",
                "XGBoost",
                "PyTorch",
                "Spark",
                "Airflow",
                "Tableau",
                "AWS",
                "A/B testing",
                "Statistics",
            ]
        },  # fmt: skip
        jobs=[
            Job(
                "Data Scientist",
                "Brightwave Health",
                "Austin, TX",
                "07/2023",
                "present",
                "2023-07",
                "present",
                [
                    "Built patient-readmission models in Python (scikit-learn, XGBoost) that "
                    "reduced 30-day readmissions by 8% across 12 hospitals.",
                    "Productionized feature pipelines with Apache Airflow and Spark on AWS.",
                    "Designed and analyzed A/B tests for care-outreach programs and presented "
                    "results to clinical leadership every quarter.",
                    "Prototyped a PyTorch model for triaging discharge notes.",
                ],
            ),
            Job(
                "Data Analyst",
                "Cobalt Retail",
                "Dallas, TX",
                "01/2022",
                "06/2023",
                "2022-01",
                "2023-06",
                [
                    "Owned weekly sales forecasting in SQL and pandas for 400 stores.",
                    "Built Tableau dashboards used by 60 regional managers to plan staffing.",
                    "Automated inventory anomaly reports, saving the planning team ten hours "
                    "a week.",
                ],
            ),
        ],  # fmt: skip
        schools=[
            School("M.S.", "Statistics", "The University of Texas at Austin", "2021"),
            School("B.S.", "Mathematics", "Texas A&M University", "2019"),
        ],
        seniority="mid",
        expected_skills=[
            "Python",
            "SQL",
            "pandas",
            "scikit-learn",
            "PyTorch",
            "Apache Spark",
            "Apache Airflow",
            "Tableau",
            "AWS",
        ],  # fmt: skip
        notes="~4.9 years; mid by experience.",
    ),
    Sample(
        slug="sam_okafor_frontend",
        kind="docx",
        layout="DOCX; contact in page header; roles in a borderless table",
        name="Sam Okafor",
        headline="Frontend Developer",
        email="sam.okafor@example.com",
        phone="07700 900123",
        location="London, UK",
        linkedin=None,
        summary=(
            "Frontend developer who moved into tech from a history degree via a coding "
            "bootcamp. I build accessible, fast interfaces and enjoy working closely with "
            "designers."
        ),
        skills={"Skills": ["JS", "TS", "ReactJS", "NextJS", "Tailwind", "Jest", "Figma", "Git"]},
        jobs=[
            Job(
                "Frontend Developer",
                "Lumen Studio",
                "London",
                "Sept 2024",
                "Present",
                "2024-09",
                "present",
                [
                    "Rebuilt the client booking flow in Next.js and TypeScript, lifting mobile "
                    "conversion by 14%.",
                    "Set up Jest and Testing Library; coverage went from 0 to 70%.",
                ],
            ),
            Job(
                "Junior Web Developer (Contract)",
                "Harbour & Finch",
                "Remote",
                "Jan 2024",
                "Aug 2024",
                "2024-01",
                "2024-08",
                ["Built marketing pages in React and Tailwind from Figma designs."],
            ),
        ],  # fmt: skip
        schools=[
            School("Bootcamp certificate", "Full-Stack Web Development", "Northcoders", "2023"),
            School("BA", "History", "University of Leeds", "2022"),
        ],
        seniority="junior",
        expected_skills=[
            "JavaScript",
            "TypeScript",
            "React",
            "Next.js",
            "Tailwind CSS",
            "Jest",
            "Figma",
        ],  # fmt: skip
        notes="~2.9 years after a career change; junior or mid are both defensible.",
    ),
    Sample(
        slug="priya_nair_fullstack",
        kind="docx",
        layout="DOCX; plain paragraphs; promotion at the same company; Indian format",
        name="Priya Nair",
        headline="Software Development Engineer II",
        email="priya.nair@example.com",
        phone="+91 98765 43210",
        location="Bengaluru, India",
        linkedin="linkedin.com/in/priyanair",
        summary=(
            "Full-stack engineer with six years at a high-growth logistics SaaS company, "
            "working mostly on Java and Spring Boot microservices with a Node.js and React "
            "front end."
        ),
        skills={
            "Technical Skills": [
                "Java",
                "Spring Boot",
                "Node.js",
                "Postgres",
                "MongoDB",
                "AWS",
                "Microservices",
                "Docker",
                "Jenkins",
            ]
        },  # fmt: skip
        jobs=[
            Job(
                "Software Development Engineer II",
                "Zentrix Technologies",
                "Bengaluru",
                "June 2022",
                "Present",
                "2022-06",
                "present",
                [
                    "Own the shipment-tracking microservices (Java, Spring Boot) handling 9M "
                    "events a day.",
                    "Cut AWS spend by 22% by moving batch jobs to spot instances.",
                ],
            ),
            Job(
                "Software Development Engineer",
                "Zentrix Technologies",
                "Bengaluru",
                "July 2020",
                "May 2022",
                "2020-07",
                "2022-05",
                [
                    "Built the carrier-integration platform in Node.js and MongoDB, onboarding "
                    "40 carriers.",
                    "Set up Jenkins pipelines and Docker-based deploys for six services.",
                ],
            ),
            Job(
                "Software Engineering Intern",
                "Kalpa Systems",
                "Pune",
                "Jan 2020",
                "Jun 2020",
                "2020-01",
                "2020-06",
                ["Developed REST endpoints for an internal HR portal using Spring."],
            ),
        ],  # fmt: skip
        schools=[
            School(
                "B.Tech",
                "Computer Science and Engineering",
                "National Institute of Technology, Tiruchirappalli",
                "2020",
            )
        ],
        seniority="mid",
        expected_skills=[
            "Java",
            "Spring Boot",
            "Node.js",
            "PostgreSQL",
            "MongoDB",
            "AWS",
            "Microservices",
            "Docker",
            "Jenkins",
        ],  # fmt: skip
        notes="SDE II with ~6.4 years; mid by title, senior by years.",
        extra_lines=["CGPA: 8.7/10", "Class XII (CBSE), 2016: 94.2%"],
    ),
    Sample(
        slug="daniel_weiss_staff",
        kind="pdf",
        layout="single column; company first; year-only dates in parentheses",
        name="Daniel Weiss",
        headline="Staff Software Engineer",
        email="daniel.weiss@example.com",
        phone="+1 416 555 0182",
        location="Toronto, ON",
        linkedin=None,
        summary=(
            "Staff engineer with fourteen years across data infrastructure and platform "
            "teams. I set technical direction for streaming systems and grow senior "
            "engineers."
        ),
        skills={
            "Core": ["Scala", "Java", "Kotlin", "Kafka", "Spark"],
            "Platform": ["k8s", "GCP", "Terraform", "gRPC", "PostgreSQL"],
        },
        jobs=[
            Job(
                "Staff Software Engineer",
                "Northbeam",
                "Toronto",
                "2021",
                "Present",
                "2021",
                "present",
                [
                    "Set the architecture for a Kafka and Spark streaming platform processing "
                    "2 TB a day.",
                    "Led a 12-engineer migration from self-managed clusters to GKE on GCP.",
                ],
            ),
            Job(
                "Engineering Lead",
                "Quillstack",
                "Toronto",
                "2018",
                "2021",
                "2018",
                "2021",
                ["Managed a team of seven building the billing platform in Scala."],
            ),
            Job(
                "Senior Software Engineer",
                "Quillstack",
                "Toronto",
                "2016",
                "2018",
                "2016",
                "2018",
                ["Designed gRPC services in Kotlin for usage metering."],
            ),
            Job(
                "Software Engineer",
                "Atlas Freight",
                "Waterloo",
                "2013",
                "2016",
                "2013",
                "2016",
                ["Built Java services for freight pricing on PostgreSQL."],
            ),
            Job(
                "Junior Developer",
                "Pixelmint",
                "Waterloo",
                "2012",
                "2013",
                "2012",
                "2013",
                ["Maintained a PHP e-commerce site and its MySQL database."],
            ),
        ],  # fmt: skip
        schools=[
            School("B.A.Sc.", "Software Engineering", "University of Waterloo", "2012"),
        ],
        seniority="lead",
        expected_skills=[
            "Scala",
            "Java",
            "Kotlin",
            "Kafka",
            "Apache Spark",
            "Kubernetes",
            "Google Cloud",
            "Terraform",
            "gRPC",
            "PostgreSQL",
        ],  # fmt: skip
    ),
]


# ── PDF rendering ───────────────────────────────────────────────────────────────
# reportlab Paragraphs parse XML-like markup, so data strings go through `esc`
# ("Texas A&M" would otherwise render as "A&M;").

styles = getSampleStyleSheet()
NAME = ParagraphStyle("name", parent=styles["Title"], fontSize=20, alignment=0, spaceAfter=2)
H2 = ParagraphStyle(
    "h2", parent=styles["Heading2"], fontSize=11.5, spaceBefore=10, spaceAfter=4,
    textColor=colors.HexColor("#1f3a5f"),
)  # fmt: skip
BODY = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=12.5)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=9, textColor=colors.HexColor("#444444"))
RIGHT = ParagraphStyle("right", parent=BODY, alignment=TA_RIGHT)


def esc(text: str) -> str:
    return escape(text)


def para(text: str, style: ParagraphStyle = BODY, *, bold: str | None = None) -> Paragraph:
    """A paragraph of plain text, optionally starting with a bold prefix."""
    prefix = f"<b>{esc(bold)}</b>" if bold else ""
    return Paragraph(prefix + esc(text), style)


def _bullets(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(para(b), leftIndent=10) for b in items],
        bulletType="bullet", start="•", leftIndent=10, bulletFontSize=8,
    )  # fmt: skip


def _contact(s: Sample) -> str:
    parts = [s.email, s.phone, s.location] + ([s.linkedin] if s.linkedin else [])
    return "  |  ".join(parts)


def render_single_column_pdf(s: Sample, path: Path, company_first: bool = False) -> None:
    doc = SimpleDocTemplate(
        str(path), pagesize=LETTER, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch, title=f"{s.name} resume",
    )  # fmt: skip
    story = [
        para(s.name, NAME),
        para(s.headline, SMALL),
        para(_contact(s), SMALL),
        para("Summary", H2),
        para(s.summary),
        para("Experience", H2),
    ]
    for job in s.jobs:
        if company_first:
            story.append(
                para(f" — {job.title} ({job.start_text}–{job.end_text})", bold=job.company)
            )
        else:
            row = [
                para(f", {job.company} · {job.location}", bold=job.title),
                para(f"{job.start_text} – {job.end_text}", RIGHT),
            ]
            table = Table([row], colWidths=[5.0 * inch, 2.1 * inch])
            table.setStyle(
                TableStyle(
                    [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]
                )
            )
            story.append(table)
        story += [_bullets(job.bullets), Spacer(1, 5)]
    story.append(para("Education", H2))
    for e in s.schools:
        story.append(para(f", {e.institution}, {e.year}", bold=f"{e.degree}, {e.field}"))
    story.append(para("Skills", H2))
    for label, items in s.skills.items():
        story.append(para(" " + ", ".join(items), bold=f"{label}:"))
    doc.build(story)


def render_two_column_pdf(s: Sample, path: Path) -> None:
    width, height = LETTER
    margin, gap, sidebar = 0.6 * inch, 0.3 * inch, 2.2 * inch
    header_h = 0.9 * inch
    header = Frame(margin, height - margin - header_h, width - 2 * margin, header_h, id="header")
    body_h = height - 2 * margin - header_h
    left = Frame(margin, margin, sidebar, body_h, id="sidebar")
    right_x = margin + sidebar + gap
    right = Frame(right_x, margin, width - right_x - margin, body_h, id="main")
    doc = BaseDocTemplate(str(path), pagesize=LETTER, title=f"{s.name} resume")
    doc.addPageTemplates([PageTemplate(id="two-col", frames=[header, left, right])])

    story = [para(s.name, NAME), para(s.headline, SMALL), FrameBreak(), para("Contact", H2)]
    story += [para(x, SMALL) for x in (s.email, s.phone, s.location)]
    if s.linkedin:
        story.append(para(s.linkedin, SMALL))
    story.append(para("Skills", H2))
    story += [para(x, SMALL) for items in s.skills.values() for x in items]
    story.append(para("Education", H2))
    for e in s.schools:
        story += [
            para("", SMALL, bold=f"{e.degree} {e.field or ''}"),
            para(f"{e.institution}, {e.year}", SMALL),
        ]
    story += [FrameBreak(), para("Profile", H2), para(s.summary), para("Experience", H2)]
    for job in s.jobs:
        story += [
            para("", bold=job.title),
            para(f"{job.company}, {job.location} | {job.start_text} - {job.end_text}", SMALL),
            _bullets(job.bullets),
            Spacer(1, 6),
        ]
    doc.build(story)


# ── DOCX rendering ──────────────────────────────────────────────────────────────


def _docx_base(s: Sample) -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    return doc


def render_table_docx(s: Sample, path: Path) -> None:
    doc = _docx_base(s)
    header = doc.sections[0].header
    header.paragraphs[0].text = f"{s.name} · {s.headline}"
    header.add_paragraph(f"{s.email} · {s.phone} · {s.location}")
    doc.add_heading("About me", level=2)
    doc.add_paragraph(s.summary)
    doc.add_heading("Experience", level=2)
    table = doc.add_table(rows=0, cols=2)
    for job in s.jobs:
        left, right = table.add_row().cells
        left.paragraphs[0].add_run(job.title).bold = True
        left.add_paragraph(f"{job.company}, {job.location}")
        for bullet in job.bullets:
            left.add_paragraph(f"• {bullet}")
        right.paragraphs[0].text = f"{job.start_text} – {job.end_text}"
    doc.add_heading("Education", level=2)
    for e in s.schools:
        doc.add_paragraph(f"{e.degree}, {e.field} — {e.institution} ({e.year})")
    doc.add_heading("Skills", level=2)
    for label, items in s.skills.items():
        doc.add_paragraph(f"{label}: {', '.join(items)}")
    doc.save(path)


def render_plain_docx(s: Sample, path: Path) -> None:
    doc = _docx_base(s)
    doc.add_heading(s.name, level=1)
    doc.add_paragraph(s.headline)
    contact = [s.email, s.phone, s.location] + ([s.linkedin] if s.linkedin else [])
    doc.add_paragraph(" | ".join(contact))
    doc.add_heading("Professional Summary", level=2)
    doc.add_paragraph(s.summary)
    doc.add_heading("Professional Experience", level=2)
    for job in s.jobs:
        p = doc.add_paragraph()
        p.add_run(job.title).bold = True
        p.add_run(f" | {job.company}, {job.location}")
        doc.add_paragraph(f"{job.start_text} – {job.end_text}")
        for bullet in job.bullets:
            doc.add_paragraph(bullet, style="List Bullet")
    doc.add_heading("Education", level=2)
    for e in s.schools:
        doc.add_paragraph(f"{e.degree}, {e.field}, {e.institution}, {e.year}")
    for line in s.extra_lines:
        doc.add_paragraph(line)
    doc.add_heading("Technical Skills", level=2)
    for items in s.skills.values():
        doc.add_paragraph(", ".join(items))
    doc.save(path)


RENDERERS = {
    "alex_chen_backend": lambda s, p: render_single_column_pdf(s, p),
    "maria_gonzalez_data": render_two_column_pdf,
    "sam_okafor_frontend": render_table_docx,
    "priya_nair_fullstack": render_plain_docx,
    "daniel_weiss_staff": lambda s, p: render_single_column_pdf(s, p, company_first=True),
}


def labels_for(s: Sample) -> dict:
    return {
        "file": f"{s.slug}.{s.kind}",
        "layout": s.layout,
        "seniority": s.seniority,
        "roles": [
            {"title": j.title, "company": j.company, "start": j.start, "end": j.end} for j in s.jobs
        ],
        "education": [asdict(e) for e in s.schools],
        "skills": s.expected_skills,
        "contact": {"email": True, "phone": True, "linkedin": s.linkedin is not None},
        "notes": s.notes,
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for sample in SAMPLES:
        path = OUT / f"{sample.slug}.{sample.kind}"
        RENDERERS[sample.slug](sample, path)
        print(f"wrote {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    labels = [labels_for(s) for s in SAMPLES]
    (OUT / "labels.json").write_text(json.dumps(labels, indent=2) + "\n")
    print(f"wrote labels for {len(labels)} resumes")


if __name__ == "__main__":
    main()
