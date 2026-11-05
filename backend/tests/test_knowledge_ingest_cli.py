from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from champbot.common.embeddings.domain.embedder import Embedder, EmbeddingError
from champbot.common.vector_store.domain.store import (
    Chunk,
    ScoredChunk,
    VectorStore,
    VectorStoreError,
)
from champbot.knowledge.ingest.presentation.cli import OpenPorts, main
from champbot.knowledge.ingest.presentation.dependencies import IngestPorts

VALID_DOC = (
    "---\n"
    "title: Checked Baggage\n"
    "source_url: https://www.airindia.com/checked.html\n"
    "retrieved_at: 2026-11-04\n"
    "---\n"
    "# Checked baggage\n"
    "Some policy text.\n"
)


def write_doc(directory: Path, name: str, content: str) -> None:
    (directory / name).write_text(content)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]


class FailingEmbedder:
    def __init__(self, error: EmbeddingError) -> None:
        self._error = error

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise self._error


class FakeVectorStore:
    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        return ["mutation-1"]

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        raise NotImplementedError


class FailingVectorStore:
    def __init__(self, error: VectorStoreError) -> None:
        self._error = error

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        raise self._error

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        raise self._error


def fake_open_ports(
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
    calls: list[bool] | None = None,
) -> OpenPorts:
    @asynccontextmanager
    async def opener() -> AsyncGenerator[IngestPorts]:
        if calls is not None:
            calls.append(True)
        yield IngestPorts(
            embedder=embedder if embedder is not None else FakeEmbedder(),
            vector_store=vector_store if vector_store is not None else FakeVectorStore(),
        )

    return opener


def test_dry_run_reports_counts_for_a_small_corpus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_doc(tmp_path, "checked-baggage.md", VALID_DOC)
    write_doc(
        tmp_path,
        "check-in.md",
        VALID_DOC.replace("Checked Baggage", "Check-in").replace("# Checked baggage", "# Check-in"),
    )

    exit_code = main(["--dry-run", str(tmp_path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "documents: 2" in out
    assert "chunks: 2" in out
    assert "largest estimated tokens:" in out
    assert "largest metadata:" in out


def test_an_invalid_document_exits_with_code_one_and_an_error_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_doc(tmp_path, "broken.md", "no front matter here\n")

    exit_code = main(["--dry-run", str(tmp_path)])

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "broken" in err


def test_write_path_success_prints_counts_and_mutation_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_doc(tmp_path, "checked-baggage.md", VALID_DOC)

    exit_code = main([str(tmp_path)], open_ports=fake_open_ports())

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "documents: 1" in out
    assert "chunks: 1" in out
    assert "upserted: 1" in out
    assert "mutation-1" in out


def test_an_embedding_error_exits_one_with_the_error_on_stderr_and_no_policy_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_doc(tmp_path, "checked-baggage.md", VALID_DOC)
    opener = fake_open_ports(embedder=FailingEmbedder(EmbeddingError("boom")))

    exit_code = main([str(tmp_path)], open_ports=opener)

    out, err = capsys.readouterr()
    assert exit_code == 1
    assert "EmbeddingError: boom" in err
    assert "Some policy text" not in out
    assert "Some policy text" not in err


def test_a_vector_store_error_exits_one_with_the_error_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_doc(tmp_path, "checked-baggage.md", VALID_DOC)
    opener = fake_open_ports(vector_store=FailingVectorStore(VectorStoreError("boom")))

    exit_code = main([str(tmp_path)], open_ports=opener)

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "VectorStoreError: boom" in err


def test_an_invalid_document_exits_before_the_opener_is_entered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_doc(tmp_path, "broken.md", "no front matter here\n")
    calls: list[bool] = []

    exit_code = main([str(tmp_path)], open_ports=fake_open_ports(calls=calls))

    capsys.readouterr()
    assert exit_code == 1
    assert calls == []


def test_missing_settings_exits_one_naming_the_missing_variable_with_no_network_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_doc(tmp_path, "checked-baggage.md", VALID_DOC)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CF_INGEST_API_TOKEN", raising=False)

    exit_code = main([str(tmp_path)])

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "MissingSettingError" in err
    assert "CLOUDFLARE_ACCOUNT_ID" in err
