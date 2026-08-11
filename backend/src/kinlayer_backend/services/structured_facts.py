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
