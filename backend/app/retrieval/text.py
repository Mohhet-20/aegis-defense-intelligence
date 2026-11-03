"""Text normalisation, safe extraction and chunking.

Chunks keep their character offsets in the NORMALISED text and the nearest
preceding heading, so a citation can point at a real location. Binary data is
never treated as text.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

TEXT_EXTENSIONS = {".txt": "plain_text", ".md": "markdown", ".markdown": "markdown", ".csv": "csv_text", ".json": "json_text", ".log": "plain_text"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")


class ExtractionError(ValueError):
    """Raised for unsupported, binary, empty or malformed input."""


@dataclass(frozen=True)
class Chunk:
    position: int
    section: Optional[str]
    text: str
    char_start: int
    char_end: int


def normalize_text(text: str) -> str:
    """NFKC, strip control characters, normalise newlines/whitespace; keeps paragraph breaks."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data[:8192]:
        return True
    sample = data[:8192]
    bad = sum(1 for b in sample if b < 9 or (13 < b < 32))
    return bad / max(len(sample), 1) > 0.05


def extract_text(data: bytes, filename: str, *, max_bytes: int = 1_000_000) -> tuple[str, str]:
    """Returns (normalised_text, extraction_method). Raises ExtractionError."""
    if len(data) > max_bytes:
        raise ExtractionError(f"file exceeds the {max_bytes}-byte indexing limit")
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    method = TEXT_EXTENSIONS.get(ext)
    if method is None:
        raise ExtractionError(f"unsupported file type '{ext or 'none'}'")
    if looks_binary(data):
        raise ExtractionError("content looks binary; it is not indexed as text")
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError("content is not valid UTF-8 text") from exc
    if method == "json_text":
        try:
            raw = json.dumps(json.loads(raw), indent=1, ensure_ascii=False)
        except ValueError as exc:
            raise ExtractionError("malformed JSON") from exc
    text = normalize_text(raw)
    if not text:
        raise ExtractionError("file contains no text")
    return text, method


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 120) -> list[Chunk]:
    """Splits normalised text into bounded chunks on paragraph/sentence/space
    boundaries when possible, remembering the preceding markdown heading.
    Every chunk text equals text[char_start:char_end]."""
    if max_chars < 100:
        raise ValueError("max_chars too small")
    overlap = max(0, min(overlap, max_chars // 3))
    text = text or ""
    n = len(text)
    out: list[Chunk] = []
    headings: list[tuple[int, str]] = []
    pos = 0
    for line in text.split("\n"):
        m = _HEADING.match(line)
        if m:
            headings.append((pos, m.group(1).strip()[:200]))
        pos += len(line) + 1
    start = 0
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"), window.rfind(" "))
            if cut > max_chars // 2:
                end = start + cut + 1
        raw = text[start:end]
        lead = len(raw) - len(raw.lstrip())
        trail = len(raw.rstrip())
        s, e = start + lead, start + trail
        if e > s:
            section = None
            for hp, ht in headings:
                if hp <= s:
                    section = ht
                else:
                    break
            out.append(Chunk(len(out), section, text[s:e], s, e))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


def body_text(text: str) -> str:
    """The text without markdown heading lines (headings are kept separately as
    `section`). Used for display excerpts; every body line is verbatim."""
    return "\n".join(l for l in text.splitlines() if l.strip() and not _HEADING.match(l))
