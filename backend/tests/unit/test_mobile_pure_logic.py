"""Pure-logic tests for the mobile dialer: phone normalization, DTMF, contact parsing."""
import io

import openpyxl
import pytest

from src.mobile.contact_parser import (
    ContactFileError,
    find_phone_column,
    parse_contact_file,
    validate_contacts,
)
from src.mobile.dtmf import (
    KIND_ATTEMPT_TOKEN,
    KIND_INVALID,
    KIND_MERGE_SIGNAL,
    KIND_VERIFICATION_CODE,
    DtmfCollector,
)
from src.mobile.phone import mask_phone, same_subscriber, to_e164, validate_lead_phone


# ── to_e164 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("+918065251146", "+918065251146"),
    ("918065251146", "+918065251146"),
    ("8065251146", "+918065251146"),
    ("08065251146", "+918065251146"),
    ("+91 98123-45678", "+919812345678"),
    ("0014155550100", "+14155550100"),
    ("", None),
    (None, None),
    ("anonymous", None),
])
def test_to_e164(raw, expected):
    assert to_e164(raw) == expected


# ── validate_lead_phone ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected,reason", [
    ("9812345678", "+919812345678", None),
    ("+91 98123 45678", "+919812345678", None),
    ("09812345678", "+919812345678", None),
    ("919812345678", "+919812345678", None),
    ("9812345678.0", "+919812345678", None),
    ("(981) 234-5678", "+919812345678", None),
    ("+14155550100", "+14155550100", None),
    ("", None, "empty"),
    ("98765", None, "too_short"),
    ("98123456789", None, "too_long"),
    ("5812345678", None, "invalid_indian_mobile"),
    ("+8149603309", None, "missing_country_code"),
    ("9.81234E+09", None, "scientific_notation"),
    ("call me", None, "non_numeric"),
])
def test_validate_lead_phone(raw, expected, reason):
    assert validate_lead_phone(raw) == (expected, reason)


def test_mask_phone():
    assert mask_phone("+919812345678") == "+91******5678"
    assert mask_phone("") == ""


def test_same_subscriber_tolerates_prefixes():
    assert same_subscriber("+919812345678", "919812345678")
    assert same_subscriber("09812345678", "+91 98123 45678")
    assert not same_subscriber("+919812345678", "+919812345679")
    assert not same_subscriber("", "+919812345678")
    assert not same_subscriber("12345", "12345")  # too short to identify anyone


# ── DtmfCollector ───────────────────────────────────────────────────────

def _feed(collector, keys, start=0.0, step=0.25):
    results = []
    t = start
    for k in keys:
        r = collector.feed(k, t)
        if r:
            results.append(r)
        t += step
    return results


def test_dtmf_attempt_token():
    assert _feed(DtmfCollector(), "*4821#")[0].__dict__ == {"kind": KIND_ATTEMPT_TOKEN, "value": "4821"}


def test_dtmf_verification_code():
    r = _feed(DtmfCollector(), "*482913#")
    assert r[0].kind == KIND_VERIFICATION_CODE and r[0].value == "482913"


def test_dtmf_lone_hash_is_merge_signal():
    assert _feed(DtmfCollector(), "#")[0].kind == KIND_MERGE_SIGNAL


def test_dtmf_wrong_length_is_invalid():
    assert _feed(DtmfCollector(), "*12#")[0].kind == KIND_INVALID


def test_dtmf_digits_outside_sequence_ignored():
    assert _feed(DtmfCollector(), "1234") == []


def test_dtmf_restart_on_star():
    r = _feed(DtmfCollector(), "*12*4821#")
    assert [(x.kind, x.value) for x in r] == [(KIND_ATTEMPT_TOKEN, "4821")]


def test_dtmf_partial_sequence_times_out():
    c = DtmfCollector(timeout_seconds=3.0)
    c.feed("*", 0.0)
    c.feed("4", 0.2)
    c.feed("8", 0.4)
    # 5 s gap: the stale "*48" is dropped, so this '#' is a lone merge signal
    assert c.feed("#", 5.4).kind == KIND_MERGE_SIGNAL


def test_dtmf_overlong_sequence_discarded():
    c = DtmfCollector()
    assert _feed(c, "*1234567#")[0].kind == KIND_MERGE_SIGNAL


# ── contact parsing ─────────────────────────────────────────────────────

def _xlsx_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_csv_with_bom_semicolon_and_alias_column():
    content = "﻿Name;Mobile Number;City\nAsha;98123 45678;Pune\nRavi;+8149603309;Mumbai\n;;\nAsha 2;09812345678;Pune\n".encode("utf-8")
    report = validate_contacts(parse_contact_file("leads.csv", content))
    assert report.phone_column == "Mobile Number"
    assert report.columns == ["phone", "Name", "City"]
    assert report.total_rows == 3
    assert report.valid_rows == 1
    assert report.invalid_rows == 1
    assert report.duplicate_rows == 1
    assert report.valid_contacts[0] == {"phone": "+919812345678", "Name": "Asha", "City": "Pune"}
    assert [(e["row"], e["reason"]) for e in report.errors] == [(3, "missing_country_code"), (5, "duplicate")]


def test_xlsx_numeric_phone_cells_and_header_offset():
    content = _xlsx_bytes([
        [None, None],
        ["phone", "name", None],
        [9812345678, "Asha"],
        [9812345679.0, "Ravi"],
        ["98765", "Short"],
    ])
    report = validate_contacts(parse_contact_file("Leads.XLSX", content))
    assert report.file_type == "xlsx"
    assert report.columns == ["phone", "name"]
    assert [c["phone"] for c in report.valid_contacts] == ["+919812345678", "+919812345679"]
    assert report.errors == [{"row": 5, "field": "phone", "value": "98765", "reason": "too_short"}]


def test_missing_phone_column_rejected():
    with pytest.raises(ContactFileError) as exc:
        validate_contacts(parse_contact_file("x.csv", b"name,city\nA,B\n"))
    assert exc.value.code == "missing_phone_column"


@pytest.mark.parametrize("name,code", [("x.xls", "xls_not_supported"), ("x.pdf", "unsupported_file_type")])
def test_unsupported_types(name, code):
    with pytest.raises(ContactFileError) as exc:
        parse_contact_file(name, b"data")
    assert exc.value.code == code


def test_corrupt_xlsx():
    with pytest.raises(ContactFileError) as exc:
        parse_contact_file("x.xlsx", b"not a zip")
    assert exc.value.code == "invalid_xlsx"


def test_duplicate_headers_suffixed():
    sheet = parse_contact_file("x.csv", b"phone,Name,name\n9812345678,A,B\n")
    assert sheet.columns == ["phone", "Name", "name_2"]


def test_find_phone_column_prefers_exact_phone():
    assert find_phone_column(["contact", "Phone"]) == "Phone"
