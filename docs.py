"""Pull plain text out of an uploaded document. The file itself is never stored."""
import io
import re

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 30000


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if len(data) > MAX_BYTES:
        raise ValueError("That file is larger than 10 MB. Upload a smaller part of it.")
    if name.endswith((".txt", ".md", ".csv")):
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
    raise ValueError("Upload a PDF, Word (.docx), or text (.txt, .md) file.")


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def quote_in(text_squashed: str, quote: str) -> bool:
    q = squash(quote)
    return len(q) >= 8 and q in text_squashed
