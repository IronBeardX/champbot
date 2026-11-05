import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from champbot.knowledge.ingest.domain.chunker import chunk_document, estimate_tokens
from champbot.knowledge.ingest.domain.document import (
    InvalidPolicyDocumentError,
    parse_policy_document,
)

DEFAULT_CORPUS_DIR = Path("data/policies")


@dataclass(frozen=True)
class _DryRunReport:
    document_count: int
    chunk_count: int
    largest_tokens: int
    largest_tokens_id: str
    largest_metadata_bytes: int
    largest_metadata_id: str


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.dry_run:
        print(
            "only --dry-run is supported until ingestion lands (IRO-180)",
            file=sys.stderr,
        )
        return 2

    try:
        report = _build_report(args.corpus_dir)
    except InvalidPolicyDocumentError as error:
        print(str(error), file=sys.stderr)
        return 1

    print(f"documents: {report.document_count}")
    print(f"chunks: {report.chunk_count}")
    print(f"largest estimated tokens: {report.largest_tokens} ({report.largest_tokens_id})")
    print(f"largest metadata: {report.largest_metadata_bytes} bytes ({report.largest_metadata_id})")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="champbot-ingest")
    parser.add_argument("corpus_dir", type=Path, nargs="?", default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _build_report(corpus_dir: Path) -> _DryRunReport:
    document_count = 0
    chunk_count = 0
    largest_tokens = 0
    largest_tokens_id = ""
    largest_metadata_bytes = 0
    largest_metadata_id = ""

    for path in sorted(corpus_dir.glob("*.md")):
        document_count += 1
        doc = parse_policy_document(path.stem, path.read_text())
        for chunk in chunk_document(doc):
            chunk_count += 1
            tokens = estimate_tokens(chunk.text)
            if tokens > largest_tokens:
                largest_tokens = tokens
                largest_tokens_id = chunk.id
            if chunk.metadata_bytes > largest_metadata_bytes:
                largest_metadata_bytes = chunk.metadata_bytes
                largest_metadata_id = chunk.id

    return _DryRunReport(
        document_count=document_count,
        chunk_count=chunk_count,
        largest_tokens=largest_tokens,
        largest_tokens_id=largest_tokens_id,
        largest_metadata_bytes=largest_metadata_bytes,
        largest_metadata_id=largest_metadata_id,
    )
