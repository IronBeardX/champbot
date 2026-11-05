import argparse
import asyncio
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path

from champbot.common.core.domain.exceptions import ChampBotError
from champbot.knowledge.ingest.application.ingest import IngestReport, ingest_chunks
from champbot.knowledge.ingest.domain.chunker import (
    DocumentChunk,
    chunk_document,
    estimate_tokens,
)
from champbot.knowledge.ingest.domain.document import (
    InvalidPolicyDocumentError,
    parse_policy_document,
)
from champbot.knowledge.ingest.presentation.dependencies import IngestPorts, open_ingest_ports

DEFAULT_CORPUS_DIR = Path("data/policies")

OpenPorts = Callable[[], AbstractAsyncContextManager[IngestPorts]]


@dataclass(frozen=True)
class _DryRunReport:
    document_count: int
    chunk_count: int
    largest_tokens: int
    largest_tokens_id: str
    largest_metadata_bytes: int
    largest_metadata_id: str


def main(argv: list[str] | None = None, open_ports: OpenPorts = open_ingest_ports) -> int:
    args = _parse_args(argv)

    try:
        document_count, chunks = _load_corpus(args.corpus_dir)
    except InvalidPolicyDocumentError as error:
        print(str(error), file=sys.stderr)
        return 1

    if args.dry_run:
        _print_dry_run_report(document_count, chunks)
        return 0

    try:
        report = asyncio.run(_ingest(chunks, open_ports))
    except ChampBotError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print(f"documents: {document_count}")
    print(f"chunks: {report.chunk_count}")
    print(f"upserted: {report.chunk_count}")
    print(f"mutation ids: {', '.join(report.mutation_ids)}")
    print("Vectorize applies the upsert asynchronously; check the dashboard count shortly.")
    return 0


async def _ingest(chunks: list[DocumentChunk], open_ports: OpenPorts) -> IngestReport:
    async with open_ports() as ports:
        return await ingest_chunks(chunks, ports.embedder, ports.vector_store)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="champbot-ingest")
    parser.add_argument("corpus_dir", type=Path, nargs="?", default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _load_corpus(corpus_dir: Path) -> tuple[int, list[DocumentChunk]]:
    document_count = 0
    chunks: list[DocumentChunk] = []
    for path in sorted(corpus_dir.glob("*.md")):
        document_count += 1
        doc = parse_policy_document(path.stem, path.read_text())
        chunks.extend(chunk_document(doc))
    return document_count, chunks


def _print_dry_run_report(document_count: int, chunks: list[DocumentChunk]) -> None:
    report = _summarize(document_count, chunks)
    print(f"documents: {report.document_count}")
    print(f"chunks: {report.chunk_count}")
    print(f"largest estimated tokens: {report.largest_tokens} ({report.largest_tokens_id})")
    print(f"largest metadata: {report.largest_metadata_bytes} bytes ({report.largest_metadata_id})")


def _summarize(document_count: int, chunks: list[DocumentChunk]) -> _DryRunReport:
    largest_tokens = 0
    largest_tokens_id = ""
    largest_metadata_bytes = 0
    largest_metadata_id = ""

    for chunk in chunks:
        tokens = estimate_tokens(chunk.text)
        if tokens > largest_tokens:
            largest_tokens = tokens
            largest_tokens_id = chunk.id
        if chunk.metadata_bytes > largest_metadata_bytes:
            largest_metadata_bytes = chunk.metadata_bytes
            largest_metadata_id = chunk.id

    return _DryRunReport(
        document_count=document_count,
        chunk_count=len(chunks),
        largest_tokens=largest_tokens,
        largest_tokens_id=largest_tokens_id,
        largest_metadata_bytes=largest_metadata_bytes,
        largest_metadata_id=largest_metadata_id,
    )
