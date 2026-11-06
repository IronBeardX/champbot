import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from champbot.chat.answer.application.retrieval import DEFAULT_TOP_K, retrieve_policy_chunks
from champbot.chat.answer.infrastructure.settings import load_retrieval_settings
from champbot.chat.answer.presentation.dependencies import (
    POLICY_INDEX_NAME,
    RetrievalPorts,
    open_retrieval_ports,
)
from champbot.common.core.domain.exceptions import ChampBotError
from champbot.common.embeddings.domain.embedder import Embedder
from champbot.common.embeddings.infrastructure.workers_ai import EMBEDDING_MODEL
from champbot.common.vector_store.domain.store import Chunk, ScoredChunk, VectorStore
from evals.git_info import REPO_ROOT, git_sha
from evals.retrieval_metrics import (
    OffTopicResult,
    QuestionResult,
    Summary,
    score_off_topic,
    score_question,
    summarize,
    summarize_by_language,
)
from evals.retrieval_report import ReportHeader, render_report

DEFAULT_OUTPUT = REPO_ROOT / "docs" / "eval" / "retrieval.md"
QUESTIONS_FILE = Path(__file__).parents[1] / "data" / "eval" / "policy_questions.json"

OpenPorts = Callable[[], AbstractAsyncContextManager[RetrievalPorts]]


class _RecordingVectorStore:
    def __init__(self, inner: VectorStore) -> None:
        self._inner = inner
        self.last_matches: list[ScoredChunk] = []

    async def upsert(self, chunks: list[Chunk]) -> list[str]:
        raise NotImplementedError("the retrieval eval never writes to the vector store")

    async def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        self.last_matches = await self._inner.query(vector, top_k)
        return self.last_matches


@dataclass(frozen=True)
class _PolicyQuestion:
    question: str
    language: str
    expected_doc: str


def main(argv: list[str] | None = None, open_ports: OpenPorts = open_retrieval_ports) -> int:
    args = _parse_args(argv)

    try:
        policy_questions, off_topic_queries = _load_questions(QUESTIONS_FILE)
    except (OSError, ValueError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1

    try:
        markdown, overall = asyncio.run(_run(policy_questions, off_topic_queries, open_ports))
    except ChampBotError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown)
    print(f"wrote {args.output}")
    print(
        f"overall: hit@1={overall.hit_at_1_rate:.3f} hit@5={overall.hit_at_5_rate:.3f} "
        f"mrr={overall.mrr:.3f} hit@5-after-threshold={overall.hit_at_5_after_threshold_rate:.3f}"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="champbot-eval-retrieval")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


async def _run(
    policy_questions: list[_PolicyQuestion],
    off_topic_queries: list[str],
    open_ports: OpenPorts,
) -> tuple[str, Summary]:
    min_score = load_retrieval_settings().min_score

    async with open_ports() as ports:
        recorder = _RecordingVectorStore(ports.vector_store)

        question_results: list[QuestionResult] = []
        for question in policy_questions:
            raw, kept = await _retrieve(question.question, ports.embedder, recorder, min_score)
            question_results.append(
                score_question(
                    question.question, question.language, question.expected_doc, raw, kept
                )
            )

        off_topic_results: list[OffTopicResult] = []
        for query in off_topic_queries:
            raw, kept = await _retrieve(query, ports.embedder, recorder, min_score)
            off_topic_results.append(score_off_topic(query, raw, kept))

        header = ReportHeader(
            run_date_utc=datetime.now(UTC),
            commit_sha=git_sha(),
            index_name=POLICY_INDEX_NAME,
            embedding_model=EMBEDDING_MODEL,
            embedder_adapter=type(ports.embedder).__name__,
            vector_store_adapter=type(ports.vector_store).__name__,
            min_score=min_score,
        )

    overall = summarize(question_results)
    by_language = summarize_by_language(question_results)
    markdown = render_report(header, question_results, off_topic_results, overall, by_language)
    return markdown, overall


async def _retrieve(
    query_text: str,
    embedder: Embedder,
    recorder: _RecordingVectorStore,
    min_score: float,
) -> tuple[list[ScoredChunk], list[ScoredChunk]]:
    kept = await retrieve_policy_chunks(
        query_text, embedder, recorder, min_score=min_score, top_k=DEFAULT_TOP_K
    )
    return recorder.last_matches, kept


def _load_questions(path: Path) -> tuple[list[_PolicyQuestion], list[str]]:
    raw: Any = json.loads(path.read_text())
    try:
        policy_questions = [
            _PolicyQuestion(
                question=entry["question"],
                language=entry["language"],
                expected_doc=entry["expected_doc"],
            )
            for entry in raw["policy_questions"]
        ]
        off_topic_queries = [str(query) for query in raw["off_topic_queries"]]
    except (KeyError, TypeError) as error:
        raise ValueError(f"{path}: unexpected shape ({error})") from error
    return policy_questions, off_topic_queries


if __name__ == "__main__":
    sys.exit(main())
