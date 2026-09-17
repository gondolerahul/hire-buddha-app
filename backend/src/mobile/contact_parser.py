"""
Contact list parsing + validation for campaign uploads (.csv / .xlsx).

Pure functions over bytes — the router handles storage and auth. Shared by
the web frontend and the mobile app (docs 06 §2.2).
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from src.mobile.phone import validate_lead_phone

MAX_ROWS = 50_000
MAX_ERRORS_RETURNED = 1_000
PREVIEW_ROWS = 20

PHONE_COLUMN_ALIASES = (
    "phone", "mobile", "phone_number", "mobile_number", "contact", "number",
    "phone_no", "mobile_no", "contact_number",
)

DUPLICATE = "duplicate"


class ContactFileError(ValueError):
    """The file as a whole can't be used; ``code`` is API-facing."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ParsedSheet:
    file_type: str
    columns: List[str]
    rows: List[Dict[str, str]]  # each row keyed by column, values stripped strings
    row_numbers: List[int]      # 1-based spreadsheet row number of each row


@dataclass
class ValidationReport:
    file_type: str
    columns: List[str]
    phone_column: Optional[str]
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    duplicate_rows: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    valid_contacts: List[Dict[str, str]] = field(default_factory=list)

    @property
    def preview(self) -> List[Dict[str, str]]:
        return self.valid_contacts[:PREVIEW_ROWS]


def detect_file_type(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return "csv"
    if name.endswith(".xlsx"):
        return "xlsx"
    if name.endswith(".xls"):
        raise ContactFileError("xls_not_supported", "Legacy .xls files are not supported; save as .xlsx or .csv")
    raise ContactFileError("unsupported_file_type", "Upload a .csv or .xlsx file")


def _normalize_header(value: Any, index: int) -> str:
    text = _cell_to_str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text or f"column_{index + 1}"


def _dedupe_headers(headers: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out = []
    for h in headers:
        key = h.lower()
        if key in seen:
            seen[key] += 1
            out.append(f"{h}_{seen[key]}")
        else:
            seen[key] = 1
            out.append(h)
    return out


def _cell_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Phone numbers typed into Excel are stored as floats: 9812345678.0
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value).strip()


def _parse_csv(content: bytes) -> ParsedSheet:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = content.decode("latin-1")

    sample = decoded[:4096]
    delimiter = ","
    if sample:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            if ";" in sample and "," not in sample:
                delimiter = ";"

    reader = csv.reader(io.StringIO(decoded), delimiter=delimiter)
    header: Optional[List[str]] = None
    rows: List[Dict[str, str]] = []
    row_numbers: List[int] = []
    for line_no, record in enumerate(reader, start=1):
        if header is None:
            if not any(c.strip() for c in record):
                continue
            header = _dedupe_headers([_normalize_header(c, i) for i, c in enumerate(record)])
            continue
        if not any(c.strip() for c in record):
            continue
        rows.append({header[i]: (record[i].strip() if i < len(record) else "") for i in range(len(header))})
        row_numbers.append(line_no)
        if len(rows) > MAX_ROWS:
            raise ContactFileError("too_many_rows", f"File has more than {MAX_ROWS} rows")
    if header is None:
        raise ContactFileError("empty_file", "The file has no header row")
    return ParsedSheet("csv", header, rows, row_numbers)


def _parse_xlsx(content: bytes) -> ParsedSheet:
    import openpyxl
    from zipfile import BadZipFile

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (BadZipFile, KeyError, OSError, ValueError) as e:
        raise ContactFileError("invalid_xlsx", f"Could not read the Excel file: {e}")
    try:
        ws = wb.worksheets[0] if wb.worksheets else None
        if ws is None:
            raise ContactFileError("empty_file", "The workbook has no sheets")
        header: Optional[List[str]] = None
        rows: List[Dict[str, str]] = []
        row_numbers: List[int] = []
        for row_no, values in enumerate(ws.iter_rows(values_only=True), start=1):
            cells = [_cell_to_str(v) for v in values]
            if header is None:
                if not any(cells):
                    continue
                # Trailing empty header cells are formatting noise, not columns.
                while cells and not cells[-1]:
                    cells.pop()
                header = _dedupe_headers([_normalize_header(c, i) for i, c in enumerate(cells)])
                continue
            if not any(cells):
                continue
            rows.append({header[i]: (cells[i] if i < len(cells) else "") for i in range(len(header))})
            row_numbers.append(row_no)
            if len(rows) > MAX_ROWS:
                raise ContactFileError("too_many_rows", f"File has more than {MAX_ROWS} rows")
        if header is None:
            raise ContactFileError("empty_file", "The first sheet has no header row")
        return ParsedSheet("xlsx", header, rows, row_numbers)
    finally:
        wb.close()


def parse_contact_file(filename: str, content: bytes) -> ParsedSheet:
    file_type = detect_file_type(filename)
    if not content:
        raise ContactFileError("empty_file", "The file is empty")
    return _parse_csv(content) if file_type == "csv" else _parse_xlsx(content)


def find_phone_column(columns: List[str]) -> Optional[str]:
    by_key = {re.sub(r"[\s_\-.]+", "_", c.strip().lower()): c for c in columns}
    for alias in PHONE_COLUMN_ALIASES:
        if alias in by_key:
            return by_key[alias]
    return None


def validate_contacts(sheet: ParsedSheet) -> ValidationReport:
    """Validate rows; valid contacts carry a normalized ``phone`` key.

    The phone alias column (e.g. "Mobile Number") is replaced by ``phone`` so
    the dialer and prompt injection see one consistent key.
    """
    phone_col = find_phone_column(sheet.columns)
    out_columns = ["phone"] + [c for c in sheet.columns if c != phone_col] if phone_col else list(sheet.columns)
    report = ValidationReport(
        file_type=sheet.file_type,
        columns=out_columns,
        phone_column=phone_col,
        total_rows=len(sheet.rows),
    )
    if phone_col is None:
        raise ContactFileError(
            "missing_phone_column",
            "No phone column found. Name one column: " + ", ".join(PHONE_COLUMN_ALIASES[:4]),
        )

    seen = set()
    for row, row_no in zip(sheet.rows, sheet.row_numbers):
        raw = row.get(phone_col, "")
        e164, reason = validate_lead_phone(raw)
        if reason:
            report.invalid_rows += 1
            if len(report.errors) < MAX_ERRORS_RETURNED:
                report.errors.append({"row": row_no, "field": phone_col, "value": raw, "reason": reason})
            continue
        if e164 in seen:
            report.duplicate_rows += 1
            if len(report.errors) < MAX_ERRORS_RETURNED:
                report.errors.append({"row": row_no, "field": phone_col, "value": raw, "reason": DUPLICATE})
            continue
        seen.add(e164)
        contact = {"phone": e164}
        contact.update({k: v for k, v in row.items() if k != phone_col and k.lower() != "phone"})
        report.valid_contacts.append(contact)

    report.valid_rows = len(report.valid_contacts)
    return report
