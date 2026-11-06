"""Remove emails and phone numbers before resume text is stored or sent to an LLM."""

import re
from dataclasses import dataclass

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A run of digits and phone punctuation on one line; filtered further below.
PHONE_CANDIDATE = re.compile(r"(?<![\w/])\+?\(?\d[\d \t().-]{6,}\d(?![\w/])")
LINKEDIN = re.compile(r"linkedin\.com/in/", re.I)
_YEAR = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class Redaction:
    text: str
    emails: int
    phones: int
    has_linkedin: bool


def _is_phone(candidate: str) -> bool:
    groups = re.findall(r"\d+", candidate)
    digits = sum(len(g) for g in groups)
    if not 10 <= digits <= 15:
        return False
    # "2019 - 2021 2022" is a run of years, not a phone number.
    return not all(_YEAR.match(g) for g in groups)


def redact_contacts(text: str) -> Redaction:
    text, emails = EMAIL.subn("[email]", text)
    phones = 0

    def replace_phone(match: re.Match[str]) -> str:
        nonlocal phones
        candidate = match.group(0)
        if not _is_phone(candidate):
            return candidate
        phones += 1
        return "[phone]"

    text = PHONE_CANDIDATE.sub(replace_phone, text)
    return Redaction(
        text=text, emails=emails, phones=phones, has_linkedin=bool(LINKEDIN.search(text))
    )
