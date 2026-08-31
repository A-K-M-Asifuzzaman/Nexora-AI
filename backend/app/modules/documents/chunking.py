"""Text extraction and chunking.

Chunking is paragraph-aware with a character overlap. The overlap exists so a
sentence split across a boundary is still retrievable from one side or the
other; without it, the single most useful passage in a document can be the one
passage no query matches.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader

SUPPORTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/markdown": "text",
    "text/csv": "text",
}

_HEADING = re.compile(r"^\s{0,3}(#{1,6}\s+\S.*|[A-Z][A-Z0-9 \-/&,()]{5,80})\s*$")


class ExtractionError(RuntimeError):
    """The bytes could not be turned into text. Surfaced to the uploader."""


class ContentTypeMismatch(RuntimeError):
    """The declared `content_type` does not match what the bytes actually are."""


_PDF_MAGIC = b"%PDF-"


def sniff_and_validate(content_type: str, data: bytes) -> None:
    """Reject a declared content type the bytes contradict.

    `Content-Type` is attacker-controlled — trusting it alone proves nothing
    about what was actually uploaded. This is not full MIME sniffing (that is
    not achievable for the three text types here: a CSV file, a Markdown file
    and a plain-text file are byte-for-byte indistinguishable in general, so
    no signature check can tell them apart). What it does catch, reliably: a
    PDF magic-number mismatch, and binary/non-UTF-8 content wearing a
    `text/*` label — the case that matters, since that is how an attacker
    would smuggle an arbitrary binary past the declared-type allowlist.
    """
    if content_type == "application/pdf":
        if not data.startswith(_PDF_MAGIC):
            raise ContentTypeMismatch("The file is not a PDF (missing %PDF- signature).")
        return
    if SUPPORTED_CONTENT_TYPES.get(content_type) == "text":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContentTypeMismatch(
                f"The file is not valid UTF-8 text, but was declared as {content_type}."
            ) from error


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    content: str
    page: int | None
    heading: str | None


@dataclass(frozen=True, slots=True)
class Page:
    number: int | None
    text: str


def extract(content_type: str, data: bytes) -> list[Page]:
    kind = SUPPORTED_CONTENT_TYPES.get(content_type)
    if kind is None:
        raise ExtractionError(f"{content_type} is not a supported document type.")
    if kind == "text":
        try:
            return [Page(number=None, text=data.decode("utf-8"))]
        except UnicodeDecodeError as error:
            raise ExtractionError("The file is not valid UTF-8 text.") from error
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [
            Page(number=i + 1, text=page.extract_text() or "")
            for i, page in enumerate(reader.pages)
        ]
    except ExtractionError:
        raise
    except Exception as error:  # pypdf raises a wide range of parse errors.
        raise ExtractionError("The PDF could not be read.") from error
    if not any(page.text.strip() for page in pages):
        # A scanned PDF parses cleanly and yields nothing. Indexing it would
        # produce a document that is INDEXED, empty, and never retrievable —
        # a failure the uploader would have no way to notice.
        raise ExtractionError("No text could be extracted; the PDF may be a scan needing OCR.")
    return pages


def _heading_of(block: str) -> str | None:
    first = block.strip().splitlines()[0] if block.strip() else ""
    return first.strip("# ").strip()[:500] if _HEADING.match(first) else None


def chunk_pages(pages: list[Page], size: int, overlap: int) -> list[Chunk]:
    if overlap >= size:  # Guarded here as well as in Settings: a caller that
        raise ValueError(
            "overlap must be smaller than size"
        )  # slips past both would not terminate.
    chunks: list[Chunk] = []
    for page in pages:
        heading: str | None = None
        blocks = [block.strip() for block in re.split(r"\n\s*\n", page.text) if block.strip()]
        buffer = ""
        for block in blocks:
            heading = _heading_of(block) or heading
            candidate = f"{buffer}\n\n{block}".strip() if buffer else block
            if len(candidate) <= size:
                buffer = candidate
                continue
            if buffer:
                chunks.append(Chunk(len(chunks), buffer, page.number, heading))
                buffer = buffer[-overlap:] if overlap else ""
            # A single block longer than the window is split on the window.
            while len(block) > size:
                head, block = block[:size], block[size - overlap :] if overlap else block[size:]
                chunks.append(Chunk(len(chunks), head, page.number, heading))
            buffer = f"{buffer}\n\n{block}".strip() if buffer else block
        if buffer.strip():
            chunks.append(Chunk(len(chunks), buffer.strip(), page.number, heading))
    return chunks
