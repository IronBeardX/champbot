from dataclasses import dataclass

from champbot.common.vector_store.domain.store import ScoredChunk


def doc_slug(chunk_id: str) -> str:
    return chunk_id.rsplit("-", 1)[0]


@dataclass(frozen=True)
class QuestionResult:
    question: str
    language: str
    expected_doc: str
    first_hit_rank: int | None
    hit_at_1: bool
    hit_at_5: bool
    hit_at_5_after_threshold: bool
    reciprocal_rank: float
    top_score: float | None
    top_doc: str | None


def score_question(
    question: str,
    language: str,
    expected_doc: str,
    raw: list[ScoredChunk],
    kept: list[ScoredChunk],
) -> QuestionResult:
    first_hit_rank = next(
        (rank for rank, chunk in enumerate(raw, start=1) if doc_slug(chunk.id) == expected_doc),
        None,
    )
    return QuestionResult(
        question=question,
        language=language,
        expected_doc=expected_doc,
        first_hit_rank=first_hit_rank,
        hit_at_1=first_hit_rank == 1,
        hit_at_5=first_hit_rank is not None,
        hit_at_5_after_threshold=any(doc_slug(chunk.id) == expected_doc for chunk in kept),
        reciprocal_rank=1 / first_hit_rank if first_hit_rank else 0.0,
        top_score=raw[0].score if raw else None,
        top_doc=doc_slug(raw[0].id) if raw else None,
    )


@dataclass(frozen=True)
class OffTopicResult:
    query: str
    max_score: float | None
    kept_out: bool


def score_off_topic(query: str, raw: list[ScoredChunk], kept: list[ScoredChunk]) -> OffTopicResult:
    # Vectorize returns top-k matches already ranked by score, so raw[0] holds the max.
    return OffTopicResult(query=query, max_score=raw[0].score if raw else None, kept_out=not kept)


@dataclass(frozen=True)
class Summary:
    n: int
    hit_at_1_rate: float
    hit_at_5_rate: float
    mrr: float
    hit_at_5_after_threshold_rate: float
    mean_top_score: float | None
    min_top_score: float | None


def summarize(results: list[QuestionResult]) -> Summary:
    n = len(results)
    if n == 0:
        return Summary(
            n=0,
            hit_at_1_rate=0.0,
            hit_at_5_rate=0.0,
            mrr=0.0,
            hit_at_5_after_threshold_rate=0.0,
            mean_top_score=None,
            min_top_score=None,
        )

    top_scores = [result.top_score for result in results if result.top_score is not None]
    return Summary(
        n=n,
        hit_at_1_rate=sum(result.hit_at_1 for result in results) / n,
        hit_at_5_rate=sum(result.hit_at_5 for result in results) / n,
        mrr=sum(result.reciprocal_rank for result in results) / n,
        hit_at_5_after_threshold_rate=sum(result.hit_at_5_after_threshold for result in results)
        / n,
        mean_top_score=sum(top_scores) / len(top_scores) if top_scores else None,
        min_top_score=min(top_scores) if top_scores else None,
    )


def summarize_by_language(results: list[QuestionResult]) -> dict[str, Summary]:
    languages = sorted({result.language for result in results})
    return {
        language: summarize([result for result in results if result.language == language])
        for language in languages
    }
