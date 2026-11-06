from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from champbot.chat.answer.presentation.dependencies import RetrievalPorts
from champbot.common.vector_store.domain.store import Chunk, ScoredChunk, VectorStoreError
from evals.retrieval import OpenPorts, main


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]


class FakeVectorStore:
    def __init__(self, matches: list[ScoredChunk]) -> None:
        self._matches = matches

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        raise NotImplementedError

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        return self._matches


class FailingVectorStore:
    def __init__(self, error: VectorStoreError) -> None:
        self._error = error

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        raise self._error

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        raise self._error


def fake_open_ports(vector_store: FakeVectorStore | FailingVectorStore) -> OpenPorts:
    @asynccontextmanager
    async def opener() -> AsyncGenerator[RetrievalPorts]:
        yield RetrievalPorts(embedder=FakeEmbedder(), vector_store=vector_store)

    return opener


def test_cli_runs_end_to_end_against_the_real_question_file_and_writes_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "0.6")
    matches = [
        ScoredChunk(id="checked-and-cabin-baggage-1", score=0.9, metadata={}),
        ScoredChunk(id="baggage-faq-1", score=0.4, metadata={}),
    ]
    output = tmp_path / "retrieval.md"

    exit_code = main(
        ["--output", str(output)], open_ports=fake_open_ports(FakeVectorStore(matches))
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "wrote" in out
    report = output.read_text()
    assert "Threshold (RETRIEVAL_MIN_SCORE): 0.6" in report
    assert "champbot-policies" in report
    assert "@cf/baai/bge-m3" in report
    assert "FakeEmbedder" in report
    assert "FakeVectorStore" in report
    assert "| en |" in report
    assert "| hi |" in report
    assert "## Off-topic queries" in report
    assert "## Calibration" in report


def test_a_vector_store_error_exits_one_with_the_error_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "0.6")
    opener = fake_open_ports(FailingVectorStore(VectorStoreError("boom")))

    exit_code = main(["--output", str(tmp_path / "r.md")], open_ports=opener)

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "VectorStoreError: boom" in err
