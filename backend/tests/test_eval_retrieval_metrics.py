from champbot.common.vector_store.domain.store import ScoredChunk
from evals.retrieval_metrics import (
    doc_slug,
    score_off_topic,
    score_question,
    summarize,
    summarize_by_language,
)


def _chunk(chunk_id: str, score: float) -> ScoredChunk:
    return ScoredChunk(id=chunk_id, score=score, metadata={})


def test_doc_slug_strips_the_trailing_chunk_index() -> None:
    assert doc_slug("checked-and-cabin-baggage-3") == "checked-and-cabin-baggage"


def test_doc_slug_handles_a_two_digit_index() -> None:
    assert doc_slug("check-in-12") == "check-in"


def test_doc_slug_keeps_internal_hyphens() -> None:
    assert doc_slug("delayed-and-lost-baggage-1") == "delayed-and-lost-baggage"


def test_hit_at_1_is_true_when_the_top_match_is_correct() -> None:
    raw = [_chunk("check-in-1", 0.9), _chunk("baggage-faq-1", 0.5)]

    result = score_question("q", "en", "check-in", raw, raw)

    assert result.hit_at_1 is True
    assert result.hit_at_5 is True


def test_hit_at_1_is_false_when_the_correct_doc_is_only_at_rank_two() -> None:
    raw = [_chunk("baggage-faq-1", 0.9), _chunk("check-in-1", 0.5)]

    result = score_question("q", "en", "check-in", raw, raw)

    assert result.hit_at_1 is False
    assert result.hit_at_5 is True
    assert result.first_hit_rank == 2


def test_hit_at_5_is_false_when_the_correct_doc_is_absent() -> None:
    raw = [_chunk("baggage-faq-1", 0.9)]

    result = score_question("q", "en", "check-in", raw, raw)

    assert result.hit_at_5 is False
    assert result.first_hit_rank is None
    assert result.reciprocal_rank == 0.0


def test_reciprocal_rank_uses_the_first_matching_chunk() -> None:
    raw = [
        _chunk("baggage-faq-1", 0.9),
        _chunk("baggage-faq-2", 0.8),
        _chunk("check-in-1", 0.7),
        _chunk("check-in-2", 0.6),
        _chunk("special-assistance-1", 0.5),
    ]

    result = score_question("q", "en", "check-in", raw, raw)

    assert result.first_hit_rank == 3
    assert result.reciprocal_rank == 1 / 3


def test_hit_at_5_after_threshold_excludes_a_match_the_threshold_dropped() -> None:
    raw = [_chunk("check-in-1", 0.4), _chunk("baggage-faq-1", 0.9)]
    kept = [_chunk("baggage-faq-1", 0.9)]

    result = score_question("q", "en", "check-in", raw, kept)

    assert result.hit_at_5 is True
    assert result.hit_at_5_after_threshold is False


def test_top_score_is_the_first_raw_match() -> None:
    raw = [_chunk("check-in-1", 0.42)]

    result = score_question("q", "en", "check-in", raw, raw)

    assert result.top_score == 0.42
    assert result.top_doc == "check-in"


def test_an_empty_raw_list_scores_everything_as_a_miss() -> None:
    result = score_question("q", "en", "check-in", [], [])

    assert result.top_score is None
    assert result.top_doc is None
    assert result.hit_at_1 is False
    assert result.hit_at_5 is False
    assert result.hit_at_5_after_threshold is False


def test_off_topic_kept_out_when_nothing_survives_the_threshold() -> None:
    raw = [_chunk("check-in-1", 0.4)]

    result = score_off_topic("q", raw, [])

    assert result.kept_out is True
    assert result.max_score == 0.4


def test_off_topic_leaked_when_a_chunk_survives_the_threshold() -> None:
    raw = [_chunk("check-in-1", 0.6)]

    result = score_off_topic("q", raw, raw)

    assert result.kept_out is False


def test_summarize_computes_rates_and_mrr_over_mixed_results() -> None:
    results = [
        score_question(
            "q1", "en", "check-in", [_chunk("check-in-1", 0.9)], [_chunk("check-in-1", 0.9)]
        ),
        score_question(
            "q2",
            "en",
            "check-in",
            [_chunk("baggage-faq-1", 0.9), _chunk("check-in-1", 0.5)],
            [_chunk("baggage-faq-1", 0.9)],
        ),
    ]

    summary = summarize(results)

    assert summary.n == 2
    assert summary.hit_at_1_rate == 0.5
    assert summary.hit_at_5_rate == 1.0
    assert summary.mrr == (1.0 + 0.5) / 2
    assert summary.hit_at_5_after_threshold_rate == 0.5
    assert summary.mean_top_score == 0.9
    assert summary.min_top_score == 0.9


def test_summarize_of_an_empty_list_has_no_score_statistics() -> None:
    summary = summarize([])

    assert summary.n == 0
    assert summary.mean_top_score is None
    assert summary.min_top_score is None


def test_summarize_by_language_splits_and_scores_each_group_independently() -> None:
    results = [
        score_question(
            "q1", "en", "check-in", [_chunk("check-in-1", 0.9)], [_chunk("check-in-1", 0.9)]
        ),
        score_question("q2", "hi", "check-in", [_chunk("baggage-faq-1", 0.9)], []),
    ]

    by_language = summarize_by_language(results)

    assert set(by_language) == {"en", "hi"}
    assert by_language["en"].hit_at_1_rate == 1.0
    assert by_language["hi"].hit_at_1_rate == 0.0
