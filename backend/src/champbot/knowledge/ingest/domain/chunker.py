import json
import math
import re
from dataclasses import dataclass

from champbot.knowledge.ingest.domain.document import InvalidPolicyDocumentError, PolicyDocument

MAX_CHUNK_TOKENS = 500
MAX_ID_BYTES = 64
MAX_METADATA_BYTES = 10 * 1024

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
SOURCE_OVERRIDE_PATTERN = re.compile(r"^<!--\s*source_url:\s*(\S+)\s*-->$")


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    title: str
    source_url: str
    section: str
    text: str

    @property
    def embedding_text(self) -> str:
        return f"{self.title} > {self.section}\n\n{self.text}"

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "title": self.title,
            "source_url": self.source_url,
            "section": self.section,
            "text": self.text,
        }

    @property
    def metadata_bytes(self) -> int:
        return len(json.dumps(self.metadata, ensure_ascii=False).encode())


@dataclass(frozen=True)
class _Section:
    heading: str
    source_url: str
    text: str


def chunk_document(doc: PolicyDocument) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    pack: list[_Section] = []

    def flush_pack() -> None:
        if pack:
            chunks.append(_build_chunk(doc, len(chunks) + 1, pack))
            pack.clear()

    for section in _split_sections(doc.body, doc.source_url):
        if estimate_tokens(section.text) > MAX_CHUNK_TOKENS:
            flush_pack()
            for piece_text in _fit_to_limit(section.text):
                piece = _Section(section.heading, section.source_url, piece_text)
                chunks.append(_build_chunk(doc, len(chunks) + 1, [piece]))
            continue

        if pack and (
            pack[-1].source_url != section.source_url
            or estimate_tokens(_joined_text([*pack, section])) > MAX_CHUNK_TOKENS
        ):
            flush_pack()
        pack.append(section)

    flush_pack()

    for chunk in chunks:
        _check_limits(doc.slug, chunk)

    return chunks


def _build_chunk(doc: PolicyDocument, n: int, sections: list[_Section]) -> DocumentChunk:
    return DocumentChunk(
        id=f"{doc.slug}-{n}",
        title=doc.title,
        source_url=sections[0].source_url,
        section="; ".join(section.heading for section in sections if section.heading),
        text=_joined_text(sections),
    )


def _joined_text(sections: list[_Section]) -> str:
    return "\n\n".join(section.text for section in sections)


def _split_sections(body: str, default_source_url: str) -> list[_Section]:
    sections: list[_Section] = []
    current_source = default_source_url
    heading = ""
    buffer: list[str] = []
    just_saw_heading = False

    def flush_buffer() -> None:
        if buffer:
            sections.append(
                _Section(heading=heading, source_url=current_source, text="\n".join(buffer))
            )

    for line in body.splitlines():
        heading_match = HEADING_PATTERN.match(line)
        if heading_match:
            flush_buffer()
            heading = heading_match.group(2).strip()
            buffer = [line]
            just_saw_heading = True
            continue

        override_match = SOURCE_OVERRIDE_PATTERN.match(line.strip())
        if override_match and just_saw_heading:
            current_source = override_match.group(1)
            just_saw_heading = False
            continue

        buffer.append(line)
        just_saw_heading = False

    flush_buffer()
    return sections


def _fit_to_limit(text: str) -> list[str]:
    if estimate_tokens(text) <= MAX_CHUNK_TOKENS:
        return [text]

    paragraphs = text.split("\n\n")
    if len(paragraphs) > 1:
        return [piece for group in _pack(paragraphs, "\n\n") for piece in _fit_to_limit(group)]

    lines = text.split("\n")
    if len(lines) > 1:
        return [piece for group in _pack(lines, "\n") for piece in _fit_to_limit(group)]

    return _hard_cut(text)


def _pack(items: list[str], joiner: str) -> list[str]:
    groups: list[str] = []
    current: list[str] = []
    for item in items:
        candidate = [*current, item]
        if current and estimate_tokens(joiner.join(candidate)) > MAX_CHUNK_TOKENS:
            groups.append(joiner.join(current))
            current = [item]
        else:
            current = candidate
    if current:
        groups.append(joiner.join(current))
    return groups


def _hard_cut(text: str) -> list[str]:
    max_chars = MAX_CHUNK_TOKENS * 4
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)] or [text]


def _check_limits(slug: str, chunk: DocumentChunk) -> None:
    id_bytes = len(chunk.id.encode())
    if id_bytes > MAX_ID_BYTES:
        raise InvalidPolicyDocumentError(
            slug, f"chunk id '{chunk.id}' is {id_bytes} bytes, over the {MAX_ID_BYTES} limit"
        )
    if chunk.metadata_bytes > MAX_METADATA_BYTES:
        raise InvalidPolicyDocumentError(
            slug,
            f"chunk '{chunk.id}' metadata is {chunk.metadata_bytes} bytes, "
            f"over the {MAX_METADATA_BYTES} limit",
        )
