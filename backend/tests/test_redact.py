import pytest

from app.parsing.redact import redact_contacts


@pytest.mark.parametrize(
    "phone",
    [
        "(206) 555-0147",
        "+1 512.555.0198",
        "+1 416 555 0182",
        "07700 900123",
        "+91 98765 43210",
        "+44 20 7946 0958",
        "555-123-4567",
    ],
)
def test_phone_formats_are_redacted(phone: str) -> None:
    result = redact_contacts(f"Call me on {phone} any time")
    assert result.text == "Call me on [phone] any time"
    assert result.phones == 1


@pytest.mark.parametrize(
    "text",
    [
        "Engineer 2019 - 2021",
        "2015 – 2019 2019 – 2021",
        "2019-2021 2022",
        "Raised $1,200,000 in 2021",
        "Served 3,000 requests per second",
        "Order 12345",
    ],
)
def test_dates_and_numbers_are_kept(text: str) -> None:
    assert redact_contacts(text).text == text


def test_emails_redacted_and_linkedin_detected() -> None:
    result = redact_contacts(
        "jane.doe+jobs@mail.example.co.uk | linkedin.com/in/janedoe | (206) 555-0147"
    )
    assert result.text == "[email] | linkedin.com/in/janedoe | [phone]"
    assert (result.emails, result.phones, result.has_linkedin) == (1, 1, True)


def test_phone_regex_does_not_span_lines() -> None:
    text = "Room 12345\n67890 is next door"  # ten digits, but on two lines
    assert redact_contacts(text).text == text
