"""
file_ingestor.py
----------------
Parse a faculty-uploaded file (Excel / PDF / text / docx / image / audio) into
a structured payload that the LLM can reason about, plus a best-effort
attendee extraction.

Image OCR (Tesseract) and audio transcription (faster-whisper) live in
src/services/media_transcriber.py — both run locally, no external API.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


_DOC_EXTS   = {".xlsx", ".xls", ".pdf", ".txt", ".md", ".docx"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_AUDIO_EXTS = {".ogg", ".oga", ".mp3", ".m4a", ".wav", ".aac", ".amr"}

SUPPORTED_EXTS = _DOC_EXTS | _IMAGE_EXTS | _AUDIO_EXTS


# ---------------------------------------------------------------------------
# Format-specific parsers
# ---------------------------------------------------------------------------

def _parse_excel(path: Path) -> Dict:
    import pandas as pd

    sheets = pd.read_excel(path, sheet_name=None)
    out_sheets = []
    for sheet_name, df in sheets.items():
        df = df.fillna("")
        rows = df.to_dict(orient="records")
        out_sheets.append({
            "sheet": sheet_name,
            "columns": [str(c) for c in df.columns],
            "rows": [{str(k): _coerce(v) for k, v in r.items()} for r in rows],
        })
    return {"kind": "excel", "sheets": out_sheets}


def _parse_pdf(path: Path) -> Dict:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return {"kind": "pdf", "pages": len(pages), "text": "\n\n".join(pages).strip()}


def _parse_text(path: Path) -> Dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    kind = "markdown" if path.suffix.lower() == ".md" else "text"
    return {"kind": kind, "text": text.strip()}


def _parse_docx(path: Path) -> Dict:
    import docx  # python-docx

    doc = docx.Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return {"kind": "docx", "text": "\n".join(paragraphs).strip()}


def _parse_image(path: Path) -> Dict:
    """OCR an image to text via Tesseract."""
    from src.services.media_transcriber import ocr_image
    result = ocr_image(path)
    return {
        "kind": "image",
        "text": result["text"],
        "ocr_confidence": result.get("ocr_confidence"),
    }


def _parse_audio(path: Path) -> Dict:
    """Transcribe an audio clip via faster-whisper."""
    from src.services.media_transcriber import transcribe_audio
    result = transcribe_audio(path)
    return {
        "kind": "audio",
        "text": result["text"],
        "language": result.get("language"),
        "duration": result.get("duration"),
    }


def _coerce(value):
    """Make pandas cell values JSON-serializable."""
    import datetime as _dt
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_file(path: str) -> Dict:
    """
    Parse a file from disk into a structured dict. Raises ValueError for
    unsupported formats so callers can echo a clear message back to the user.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Upload not found: {path}")

    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported file type: {ext}. Supported: {sorted(SUPPORTED_EXTS)}."
        )

    if ext in (".xlsx", ".xls"):
        return _parse_excel(p)
    if ext == ".pdf":
        return _parse_pdf(p)
    if ext == ".docx":
        return _parse_docx(p)
    if ext in _IMAGE_EXTS:
        return _parse_image(p)
    if ext in _AUDIO_EXTS:
        return _parse_audio(p)
    return _parse_text(p)


# ---------------------------------------------------------------------------
# Attendee extraction
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")

_NAME_KEYS  = {"name", "full name", "fullname", "student name", "student", "participant"}
_EMAIL_KEYS = {"email", "e-mail", "mail", "email id", "email address"}
_PHONE_KEYS = {"phone", "mobile", "whatsapp", "contact", "phone number", "mobile number"}
_ROLE_KEYS  = {"role", "type", "designation"}
_DEPT_KEYS  = {"department", "dept", "branch"}


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(k).lower()).strip()


def _attendees_from_excel(parsed: Dict) -> List[Dict]:
    out: List[Dict] = []
    for sheet in parsed.get("sheets", []):
        # Build a key map from normalized header → original column
        col_map = {_norm_key(c): c for c in sheet.get("columns", [])}

        def first_match(candidates):
            for cand in candidates:
                if cand in col_map:
                    return col_map[cand]
            return None

        name_col  = first_match(_NAME_KEYS)
        email_col = first_match(_EMAIL_KEYS)
        phone_col = first_match(_PHONE_KEYS)
        role_col  = first_match(_ROLE_KEYS)
        dept_col  = first_match(_DEPT_KEYS)

        for row in sheet.get("rows", []):
            name  = str(row.get(name_col, "")).strip()  if name_col  else ""
            email = str(row.get(email_col, "")).strip() if email_col else ""
            phone = str(row.get(phone_col, "")).strip() if phone_col else ""
            role  = str(row.get(role_col, "")).strip()  if role_col  else None
            dept  = str(row.get(dept_col, "")).strip()  if dept_col  else None

            # Fallback: scan any cell for an email/phone if the column wasn't named.
            if not email:
                for v in row.values():
                    m = _EMAIL_RE.search(str(v))
                    if m:
                        email = m.group(0)
                        break
            if not phone:
                for v in row.values():
                    m = _PHONE_RE.search(str(v))
                    if m:
                        phone = re.sub(r"[\s().-]", "", m.group(0))
                        break

            if name or email or phone:
                out.append({
                    "name":  name or None,
                    "email": email or None,
                    "phone": phone or None,
                    "role":  (role or "STUDENT").upper() if role else "STUDENT",
                    "department": dept or None,
                })
    return out


def _attendees_from_text(text: str) -> List[Dict]:
    """
    Last-resort heuristic: scan free-form text for email/phone hits and
    return one row per email found. Names are not reliably extractable
    without an LLM, so we leave them blank.
    """
    out: List[Dict] = []
    seen = set()
    for m in _EMAIL_RE.finditer(text):
        email = m.group(0)
        if email in seen:
            continue
        seen.add(email)
        # Look for a phone within the same line as the email.
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end   = text.find("\n", m.end())
        line = text[line_start: line_end if line_end != -1 else len(text)]
        phone_match = _PHONE_RE.search(line)
        phone = re.sub(r"[\s().-]", "", phone_match.group(0)) if phone_match else None
        out.append({
            "name": None,
            "email": email,
            "phone": phone,
            "role": "STUDENT",
            "department": None,
        })
    return out


def extract_attendees(parsed: Dict) -> List[Dict]:
    """
    Best-effort structured-list extraction from a parsed file. Returns a list
    of {name, email, phone, role, department} dicts. Empty list if nothing
    could be found.
    """
    if parsed.get("kind") == "excel":
        rows = _attendees_from_excel(parsed)
        if rows:
            return rows
        # Fall through if header detection failed → search raw text.
        text = json.dumps(parsed, default=str)
        return _attendees_from_text(text)

    text = parsed.get("text") or ""
    return _attendees_from_text(text)


# ---------------------------------------------------------------------------
# Meeting-metadata extraction (LLM-driven, best-effort)
# ---------------------------------------------------------------------------

_MEETING_EXTRACT_SYSTEM = """\
You read a document a faculty member uploaded and identify whether it
describes a single meeting (faculty meeting, class, exam briefing, etc).

Output ONLY a JSON object — no markdown, no commentary — with keys:
  title       string|null   short meeting title (e.g. "Faculty meeting")
  start_time  string|null   ISO 8601 datetime when the meeting starts
  end_time    string|null   ISO 8601 datetime when the meeting ends
  location    string|null   room / hall / link mentioned
  agenda      string|null   one-sentence summary of the agenda
  found       boolean       true only if you saw a clear date+time

Rules:
- Convert relative dates (e.g. "next Tuesday at 4pm") using the provided
  current reference time.
- If the document is just a list of people with no meeting details, return
  found=false and all other fields null.
- Times must be ISO 8601 (YYYY-MM-DDTHH:MM:SS). No time zone suffix needed.
"""


def _text_for_extraction(parsed: Dict, max_chars: int = 6000) -> str:
    """Reduce a parsed payload to a single text blob the LLM can read."""
    if parsed.get("kind") == "excel":
        chunks: List[str] = []
        for sheet in parsed.get("sheets", []):
            chunks.append(f"# Sheet: {sheet.get('sheet')}")
            chunks.append("Columns: " + ", ".join(sheet.get("columns", [])))
            for row in (sheet.get("rows", []) or [])[:25]:
                chunks.append(" | ".join(f"{k}={v}" for k, v in row.items()))
        text = "\n".join(chunks)
    else:
        text = parsed.get("text") or ""
    return text[:max_chars]


def extract_meeting_metadata(parsed: Dict) -> Dict:
    """
    Best-effort meeting extraction. Returns a dict with the same keys as the
    LLM contract above; on any failure returns {found: False}.
    """
    from datetime import datetime as _dt
    text = _text_for_extraction(parsed)
    if not text.strip():
        return {"found": False}

    try:
        from src.utils.config_loader import get_llm_client
        client = get_llm_client()
        user_prompt = (
            f"Current reference time: {_dt.now().isoformat(timespec='seconds')}\n\n"
            f"Document:\n---\n{text}\n---"
        )
        raw = client.generate(_MEETING_EXTRACT_SYSTEM, user_prompt)
    except Exception as e:
        logger.warning("LLM meeting extraction failed: %s", e)
        return {"found": False}

    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(json)?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
    except Exception:
        logger.warning("LLM meeting extraction returned non-JSON: %r", raw[:200])
        return {"found": False}

    # Coerce to expected shape.
    return {
        "found":      bool(data.get("found")) and bool(data.get("start_time")),
        "title":      data.get("title"),
        "start_time": data.get("start_time"),
        "end_time":   data.get("end_time"),
        "location":   data.get("location"),
        "agenda":     data.get("agenda"),
    }


def summarize(parsed: Dict, attendees: List[Dict]) -> str:
    """
    Build a short, human-readable summary string suitable for echoing back
    over WhatsApp.
    """
    kind = parsed.get("kind", "file")
    if kind == "excel":
        sheets = parsed.get("sheets", [])
        n_rows = sum(len(s.get("rows", [])) for s in sheets)
        head = f"Excel file with {len(sheets)} sheet(s), {n_rows} row(s) total."
    elif kind == "pdf":
        head = f"PDF with {parsed.get('pages', 0)} page(s)."
    elif kind == "image":
        text = parsed.get("text") or ""
        conf = parsed.get("ocr_confidence")
        conf_label = f" (OCR ~{conf}% confidence)" if conf is not None else ""
        head = f"Image scanned{conf_label}, ~{len(text.split())} words extracted."
    elif kind == "audio":
        text = parsed.get("text") or ""
        dur = parsed.get("duration") or 0
        head = f"Audio transcribed ({dur:.0f}s), ~{len(text.split())} words."
    else:
        text = parsed.get("text") or ""
        head = f"{kind.upper()} document, ~{len(text.split())} words."

    if attendees:
        sample = ", ".join(
            (a.get("name") or a.get("email") or a.get("phone") or "?")
            for a in attendees[:5]
        )
        more = f" (+{len(attendees) - 5} more)" if len(attendees) > 5 else ""
        head += f"\nFound {len(attendees)} contact(s): {sample}{more}."
    else:
        head += "\nNo contact rows detected automatically."
    return head


def summarize_meeting(meeting: Dict) -> str:
    """Pretty-print the LLM-extracted meeting metadata for echoing to the user."""
    if not meeting or not meeting.get("found"):
        return ""
    lines = []
    if meeting.get("title"):
        lines.append(f"Title : {meeting['title']}")
    if meeting.get("start_time"):
        end = meeting.get("end_time") or "?"
        lines.append(f"When  : {meeting['start_time']} → {end}")
    if meeting.get("location"):
        lines.append(f"Where : {meeting['location']}")
    if meeting.get("agenda"):
        lines.append(f"Agenda: {meeting['agenda']}")
    return "\n".join(lines)
