from dataclasses import dataclass
from datetime import date
from typing import Callable, Final, assert_never


@dataclass(frozen=True, slots=True)
class ValidStructuredFactContent:
    content: str


@dataclass(frozen=True, slots=True)
class InvalidStructuredFactContent:
    message: str


StructuredFactValidationResult = ValidStructuredFactContent | InvalidStructuredFactContent
StructuredFactValidator = Callable[[str], StructuredFactValidationResult]


def _invalid(message: str) -> InvalidStructuredFactContent:
    return InvalidStructuredFactContent(message=message)


def _validate_required_text(content: str) -> StructuredFactValidationResult:
    stripped = content.strip()
    if not stripped:
        return _invalid("Structured fact content cannot be blank.")
    return ValidStructuredFactContent(content=stripped)


def _validate_email(content: str) -> StructuredFactValidationResult:
    required = _validate_required_text(content)
    match required:
        case InvalidStructuredFactContent():
            return required
        case ValidStructuredFactContent(content=stripped):
            pass
        case unreachable:
            assert_never(unreachable)
    if stripped.count("@") != 1:
        return _invalid("Email facts require a single @ address.")
    local_part, domain = stripped.split("@", 1)
    normalized_domain = domain.casefold()
    if (
        not local_part
        or not normalized_domain
        or "." not in normalized_domain
        or normalized_domain.startswith(".")
        or normalized_domain.endswith(".")
        or any(character.isspace() for character in stripped)
    ):
        return _invalid("Email facts require a valid address.")
    return ValidStructuredFactContent(content=f"{local_part}@{normalized_domain}")


def _validate_phone(content: str) -> StructuredFactValidationResult:
    required = _validate_required_text(content)
    match required:
        case InvalidStructuredFactContent():
            return required
        case ValidStructuredFactContent(content=stripped):
            pass
        case unreachable:
            assert_never(unreachable)
    digit_count = sum(1 for character in stripped if character.isdecimal())
    if digit_count < 7:
        return _invalid("Phone facts require at least seven digits.")
    return ValidStructuredFactContent(content=stripped)


def _validate_birth_date(content: str) -> StructuredFactValidationResult:
    required = _validate_required_text(content)
    match required:
        case InvalidStructuredFactContent():
            return required
        case ValidStructuredFactContent(content=stripped):
            pass
        case unreachable:
            assert_never(unreachable)
    try:
        parsed = date.fromisoformat(stripped)
    except ValueError:
        return _invalid("Birth date facts require YYYY-MM-DD.")
    if stripped != parsed.isoformat():
        return _invalid("Birth date facts require YYYY-MM-DD.")
    return required


STRUCTURED_FACT_VALIDATORS: Final[dict[str, StructuredFactValidator]] = {
    "legal_name": _validate_required_text,
    "birth_date": _validate_birth_date,
    "phone": _validate_phone,
    "email": _validate_email,
    "address": _validate_required_text,
    "organization": _validate_required_text,
    "role": _validate_required_text,
}


def validate_structured_fact_content(
    fact_type: str,
    content: str,
) -> StructuredFactValidationResult:
    validator = STRUCTURED_FACT_VALIDATORS.get(fact_type)
    if validator is None:
        return ValidStructuredFactContent(content=content)
    return validator(content)


def is_structured_fact_type(fact_type: str) -> bool:
    return fact_type in STRUCTURED_FACT_VALIDATORS


PROFILE_TEXT_FACT_TYPES = frozenset({
    "legal_name", "phone", "email", "address", "organization", "role", "job",
    "external_handle", "location_hint",
})
PROFILE_DATE_FACT_TYPES = frozenset({"birth_date", "birthday"})


def normalize_profile_fact(fact_type: str, content: str, value: dict) -> tuple[str, dict]:
    """Validate the v2 profile value without guessing missing information.

    Legacy generic notes remain readable; new contextual memories use observations.
    Content is the display form of the structured value, not a second claim store.
    """
    if not isinstance(content, str):
        raise ValueError("Profile content must be a string.")
    if not isinstance(value, dict):
        raise ValueError("Profile facts require a structured value object.")
    if fact_type in PROFILE_TEXT_FACT_TYPES:
        if set(value) != {"text"} or not isinstance(value["text"], str):
            raise ValueError("Text profile values must contain only text.")
        normalized = validate_structured_fact_content(fact_type, value["text"].strip())
        if isinstance(normalized, InvalidStructuredFactContent):
            raise ValueError(normalized.message)
        if not normalized.content:
            raise ValueError("Profile text cannot be empty.")
        normalized_content = validate_structured_fact_content(fact_type, content.strip())
        if (
            isinstance(normalized_content, InvalidStructuredFactContent)
            or normalized_content.content != normalized.content
        ):
            raise ValueError("Profile content must match the structured text value.")
        return normalized.content, {"text": normalized.content}
    if fact_type not in PROFILE_DATE_FACT_TYPES:
        raise ValueError("Context, notes and preferences must be observations, not profile facts.")
    if set(value) - {"year", "month", "day", "precision"}:
        raise ValueError("Date value accepts only year, month, day and precision.")
    year, month, day = (value.get(key) for key in ("year", "month", "day"))
    precision = value.get("precision")
    for key, item, lower, upper in (
        ("year", year, 1, 9999), ("month", month, 1, 12), ("day", day, 1, 31),
    ):
        if item is not None and (type(item) is not int or not lower <= item <= upper):
            raise ValueError(f"Invalid date {key}.")
    if precision == "year" and year is not None and month is None and day is None:
        rendered = f"{year:04d}"
    elif precision == "month" and month is not None and day is None:
        if year is None and fact_type != "birthday":
            raise ValueError("birth_date month precision requires a year.")
        rendered = f"{year:04d}-{month:02d}" if year else f"--{month:02d}"
    elif precision == "day" and month is not None and day is not None:
        if year is None and fact_type != "birthday":
            raise ValueError("birth_date day precision requires a year.")
        # A leap year validates an annual birthday without inventing a birth year.
        date(year or 2000, month, day)
        rendered = f"{year:04d}-{month:02d}-{day:02d}" if year else f"--{month:02d}-{day:02d}"
    else:
        raise ValueError("Date components must agree with precision: year, month or day.")
    if content.strip() != rendered:
        raise ValueError(f"Date content must match its structured display form: {rendered}.")
    return rendered, {"year": year, "month": month, "day": day, "precision": precision}
