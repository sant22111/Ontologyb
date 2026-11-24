"""Pull plain text out of an uploaded document. The file itself is never stored."""
import io
import re

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 30000


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if len(data) > MAX_BYTES:
        raise ValueError("That file is larger than 10 MB. Upload a smaller part of it.")
    if name.endswith(".csv"):
        return _csv_schema(filename, data)
    if name.endswith((".xlsx", ".xlsm")):
        return _xlsx_schema(filename, data)
    if name.endswith(".xls"):
        raise ValueError("Old .xls files are not supported. Save it as .xlsx and upload again.")
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="ignore")
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in r.pages)
    if name.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    raise ValueError("Upload a PDF, Word (.docx), Excel (.xlsx), CSV or text (.txt, .md) file.")


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def quote_in(text_squashed: str, quote: str) -> bool:
    q = squash(quote)
    return len(q) >= 8 and q in text_squashed


def _kind(values):
    vals = [v for v in values if v not in (None, "")][:50]
    if not vals:
        return "text"
    import datetime
    if all(isinstance(v, (datetime.datetime, datetime.date)) for v in vals):
        return "date"
    if all(isinstance(v, bool) for v in vals):
        return "yes/no"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return "number"
    return "text"


def _sheet_block(title, header, rows, nrows):
    cols = []
    for i, h in enumerate(header[:60]):
        if h in (None, ""):
            continue
        cols.append(f"{str(h).strip()[:60]} ({_kind([r[i] for r in rows if i < len(r)])})")
    if not cols:
        return ""
    return f"SHEET: {title} (about {nrows} rows)\nColumns: " + " | ".join(cols)


def _xlsx_schema(filename, data):
    """Only sheet names, column headings and column types leave this function, never the rows."""
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = [f"SPREADSHEET: {filename} (sheet names, column headings and column types only; no data rows are shared)"]
    for ws in list(wb.worksheets)[:30]:
        header, sample, n = None, [], 0
        for row in ws.iter_rows(values_only=True):
            if header is None:
                if sum(1 for c in row if c not in (None, "")) >= 2:
                    header = list(row)
                continue
            n += 1
            if len(sample) < 50:
                sample.append(list(row))
            if n >= 100000:
                break
        if header:
            b = _sheet_block(ws.title, header, sample, n)
            if b:
                out.append(b)
    return "\n".join(out)


def _csv_schema(filename, data):
    import csv
    text = data.decode("utf-8-sig", errors="ignore")
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    sample = [[_coerce(c) for c in r] for r in rows[1:51]]
    b = _sheet_block(filename, rows[0], sample, len(rows) - 1)
    return f"SPREADSHEET: {filename} (column headings and column types only; no data rows are shared)\n" + b


def _coerce(c):
    c = (c or "").strip()
    if not c:
        return None
    try:
        return float(c.replace(",", ""))
    except ValueError:
        return c
