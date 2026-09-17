"""
Phone number normalization for the mobile dialer.

Two jobs:
  * ``to_e164`` — canonical form used for every stored/compared number
    (device caller IDs, DIDs, webhook from/to). Smartflo sends numbers with
    or without ``+``/country code, so equality only works after this.
  * ``validate_lead_phone`` — strict validation of uploaded contact numbers,
    returning a machine-readable reason on failure (shown row-by-row in the
    upload report).
"""
import re
from typing import Optional, Tuple

from src.common.config import settings

_STRIP_CHARS = re.compile(r"[\s\-().]")


def _default_cc() -> str:
    return (settings.DEFAULT_PHONE_COUNTRY_CODE or "91").lstrip("+")


def to_e164(raw: Optional[str]) -> Optional[str]:
    """Best-effort canonical E.164 for a number presented by a provider.

    Lenient by design (never raises): used for matching, not validation.
    Returns None when the input has no digits.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if text.startswith("+"):
        return f"+{digits}"
    cc = _default_cc()
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if len(digits) == 10:
        return f"+{cc}{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+{cc}{digits[1:]}"
    return f"+{digits}"


# Reasons surfaced in the upload report (docs 06 §2.2).
EMPTY = "empty"
NON_NUMERIC = "non_numeric"
SCIENTIFIC_NOTATION = "scientific_notation"
TOO_SHORT = "too_short"
TOO_LONG = "too_long"
MISSING_COUNTRY_CODE = "missing_country_code"
INVALID_INDIAN_MOBILE = "invalid_indian_mobile"

_SCIENTIFIC = re.compile(r"^\+?\d+(\.\d+)?[eE]\+?\d+$")


def validate_lead_phone(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Validate and normalize a lead's phone number from an uploaded file.

    Returns ``(e164, None)`` when valid, else ``(None, reason)``.
    Indian numbers (+91) must be 10-digit mobiles starting 6-9.
    """
    if raw is None:
        return None, EMPTY
    text = str(raw).strip()
    if not text:
        return None, EMPTY
    if _SCIENTIFIC.match(text):
        # Excel's "9.81234E+09" display form has already lost digits.
        return None, SCIENTIFIC_NOTATION
    if text.endswith(".0") and text[:-2].lstrip("+").isdigit():
        text = text[:-2]  # float-typed cell exported as text
    compact = _STRIP_CHARS.sub("", text)
    has_plus = compact.startswith("+")
    digits = compact[1:] if has_plus else compact
    if not digits.isdigit():
        return None, NON_NUMERIC

    cc = _default_cc()
    if has_plus:
        if digits.startswith(cc):
            national = digits[len(cc):]
        elif len(digits) == 10:
            # "+8149603309": a plus sign but no country code. Tata rejects it.
            return None, MISSING_COUNTRY_CODE
        else:
            if len(digits) < 8:
                return None, TOO_SHORT
            if len(digits) > 15:
                return None, TOO_LONG
            return f"+{digits}", None
    else:
        if digits.startswith("00"):
            return validate_lead_phone(f"+{digits[2:]}")
        if len(digits) == 11 and digits.startswith("0"):
            national = digits[1:]
        elif len(digits) == 10 + len(cc) and digits.startswith(cc):
            national = digits[len(cc):]
        else:
            national = digits

    if len(national) < 10:
        return None, TOO_SHORT
    if len(national) > 10:
        return None, TOO_LONG
    if cc == "91" and national[0] not in "6789":
        return None, INVALID_INDIAN_MOBILE
    return f"+{cc}{national}", None


def mask_phone(e164: Optional[str]) -> str:
    """'+919812345678' -> '+91******5678' for lists shown to reps."""
    if not e164:
        return ""
    if len(e164) <= 4:
        return e164
    keep_prefix = 3 if e164.startswith("+") else 0
    return e164[:keep_prefix] + "*" * (len(e164) - keep_prefix - 4) + e164[-4:]
