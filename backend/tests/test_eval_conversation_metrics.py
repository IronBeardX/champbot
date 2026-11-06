from datetime import date

import pytest

from champbot.chat.answer.presentation.serializers import ChatRequest
from evals.conversation_metrics import (
    CaseResult,
    CheckResult,
    TurnExpectation,
    TurnResult,
    build_history,
    check_cited_url,
    check_flights_presence,
    check_intent,
    check_language,
    check_off_topic_shape,
    classify_case,
    devanagari_share,
    percentile,
    render_message,
    run_checks,
    summarize,
    summarize_latency,
    truncate_answer,
)

# --- render_message ---


def test_render_message_resolves_positive_and_negative_offsets_across_a_month_boundary() -> None:
    today = date(2026, 11, 30)

    assert render_message("fly on {date+1}", today) == "fly on 2026-12-01"
    assert render_message("fly on {date-1}", today) == "fly on 2026-11-29"


def test_render_message_resolves_several_placeholders_in_one_message() -> None:
    today = date(2026, 1, 10)

    rendered = render_message("from {date+1} to {date+3}", today)

    assert rendered == "from 2026-01-11 to 2026-01-13"


def test_render_message_raises_on_a_malformed_placeholder() -> None:
    with pytest.raises(ValueError, match="unrendered date placeholder"):
        render_message("fly on {dateX}", date(2026, 1, 1))


def test_render_message_leaves_plain_text_unchanged() -> None:
    assert render_message("Hello there!", date(2026, 1, 1)) == "Hello there!"


# --- build_history ---


def test_build_history_of_no_pairs_is_empty() -> None:
    assert build_history([]) == []


def test_build_history_alternates_user_assistant_starting_with_user() -> None:
    history = build_history([("hi", "hello"), ("bye", "goodbye")])

    roles = [item["role"] for item in history]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_build_history_keeps_only_the_newest_pairs_under_the_item_cap() -> None:
    pairs = [(f"q{i}", f"a{i}") for i in range(15)]

    history = build_history(pairs)

    assert len(history) == 20
    assert history[0] == {"role": "user", "text": "q5"}
    assert history[-1] == {"role": "assistant", "text": "a14"}


def test_build_history_drops_the_oldest_pairs_first_under_the_char_cap() -> None:
    # Each pair is 9,800 chars (within the per-role caps); five pairs (49,000 chars)
    # exceed the 40,000 total, so only the newest four (39,200 chars) are kept.
    pairs = [(f"q{i} " + "q" * 1895, "a" * 7900) for i in range(5)]

    history = build_history(pairs)

    assert len(history) == 8
    assert sum(len(item["text"]) for item in history) <= 40_000
    assert history[0]["text"].startswith("q1 ")


def test_build_history_drops_a_pair_that_alone_breaks_a_per_role_cap() -> None:
    pairs = [("fine", "fine"), ("x" * 2001, "fine too")]

    history = build_history(pairs)

    assert history == [{"role": "user", "text": "fine"}, {"role": "assistant", "text": "fine"}]


def test_build_history_drops_a_blank_pair() -> None:
    history = build_history([("   ", "fine"), ("fine", "fine")])

    assert history == [{"role": "user", "text": "fine"}, {"role": "assistant", "text": "fine"}]


def test_build_history_counts_devanagari_text_in_code_points() -> None:
    history = build_history([("नमस्ते", "नमस्ते")])

    assert history[0]["text"] == "नमस्ते"


def test_build_history_result_always_validates_through_chat_request() -> None:
    pairs = [(f"q{i}", f"a{i}") for i in range(25)]

    history = build_history(pairs)
    request = ChatRequest.model_validate({"message": "final", "history": history})

    assert len(request.history) == len(history)


# --- check_intent ---


def test_check_intent_passes_on_match() -> None:
    result = check_intent("policy", "policy")

    assert result.passed
    assert result.expected == "policy"
    assert result.actual == "policy"


def test_check_intent_fails_with_expected_vs_actual_on_mismatch() -> None:
    result = check_intent("policy", "general")

    assert not result.passed
    assert result.expected == "policy"
    assert result.actual == "general"


# --- check_cited_url ---


def test_check_cited_url_passes_when_url_is_among_several_sources() -> None:
    result = check_cited_url("https://x/cab", ["https://x/other", "https://x/cab"])

    assert result.passed


def test_check_cited_url_fails_when_only_the_sibling_url_is_cited() -> None:
    result = check_cited_url(
        "https://www.airindia.com/in/en/travel-information/baggage-guidelines/cabin-baggage.html",
        [
            "https://www.airindia.com/in/en/travel-information/baggage-guidelines/checked-baggage-allowance.html"
        ],
    )

    assert not result.passed


def test_check_cited_url_fails_on_empty_sources() -> None:
    result = check_cited_url("https://x/cab", [])

    assert not result.passed
    assert result.actual == "(none)"


# --- check_flights_presence ---


@pytest.mark.parametrize(
    ("expected", "count", "passed"),
    [
        (True, 2, True),
        (True, 0, False),
        (False, 0, True),
        (False, 3, False),
    ],
)
def test_check_flights_presence_all_combinations(expected: bool, count: int, passed: bool) -> None:
    result = check_flights_presence(expected, count)

    assert result.passed is passed


# --- devanagari_share / check_language ---


def test_devanagari_share_of_pure_hindi_is_one() -> None:
    assert devanagari_share("नमस्ते") == 1.0


def test_devanagari_share_of_pure_english_is_zero() -> None:
    assert devanagari_share("hello there") == 0.0


def test_devanagari_share_of_hindi_with_air_india_stays_above_half() -> None:
    share = devanagari_share("आप Air India से यात्रा कर सकते हैं")

    assert share > 0.5


def test_devanagari_share_counts_matras_as_devanagari() -> None:
    # "कि" = KA + vowel sign I (U+093F), a combining mark that str.isalpha() rejects.
    assert devanagari_share("कि") == 1.0


def test_devanagari_share_ignores_digits_and_punctuation() -> None:
    assert devanagari_share("12, 34!") == 0.0


def test_devanagari_share_of_empty_text_is_zero() -> None:
    assert devanagari_share("") == 0.0


def test_check_language_thresholds() -> None:
    assert check_language("hi", "नमस्ते " * 10).passed
    assert check_language("en", "hello there, friend").passed
    assert not check_language("hi", "hello there").passed
    assert not check_language("en", "नमस्ते दोस्त").passed


def test_check_language_is_skipped_for_flight_search_turns() -> None:
    expectation = TurnExpectation(message="m", intent="flight_search", flights=True)

    checks = run_checks(expectation, "hi", "flight_search", [], 1, "All English, as always.")

    assert all(check.name != "language" for check in checks)


# --- check_off_topic_shape ---


def test_check_off_topic_shape_passes_only_on_general_no_sources_no_flights() -> None:
    assert check_off_topic_shape("general", [], 0).passed
    assert not check_off_topic_shape("policy", [], 0).passed
    assert not check_off_topic_shape("general", ["https://x"], 0).passed
    assert not check_off_topic_shape("general", [], 1).passed


def test_check_off_topic_shape_names_each_violation() -> None:
    result = check_off_topic_shape("policy", ["https://x"], 2)

    assert "intent=policy" in result.actual
    assert "sources=1" in result.actual
    assert "flights=2" in result.actual


# --- classify_case ---


def _check(passed: bool) -> CheckResult:
    return CheckResult("intent", passed, "x", "y")


def test_classify_case_all_pass_is_pass() -> None:
    turns = [TurnResult(0, "m", "200", [_check(True)], "answer", 0.1)]

    assert classify_case(turns) == "pass"


def test_classify_case_any_failed_check_is_fail() -> None:
    turns = [TurnResult(0, "m", "200", [_check(False)], "answer", 0.1)]

    assert classify_case(turns) == "fail"


def test_classify_case_any_http_error_turn_is_http_error_even_after_a_failed_check() -> None:
    turns = [
        TurnResult(0, "m", "200", [_check(False)], "answer", 0.1),
        TurnResult(1, "m2", "502", [], None, 0.1),
    ]

    assert classify_case(turns) == "http_error"


def test_classify_case_a_contract_failure_is_fail() -> None:
    turns = [TurnResult(0, "m", "200", [CheckResult("contract", False, "x", "y")], None, 0.1)]

    assert classify_case(turns) == "fail"


def test_classify_case_with_no_turns_is_not_run() -> None:
    assert classify_case([]) == "not_run"


# --- percentile / summarize_latency ---


def test_percentile_with_a_single_value() -> None:
    assert percentile([5.0], 50) == 5.0
    assert percentile([5.0], 95) == 5.0


def test_percentile_with_twenty_values_hand_checked() -> None:
    values = [float(n) for n in range(1, 21)]

    assert percentile(values, 50) == 10.0
    assert percentile(values, 95) == 19.0


def test_percentile_sorts_unsorted_input() -> None:
    assert percentile([3.0, 1.0, 2.0], 50) == 2.0


def test_percentile_of_empty_input_is_none() -> None:
    assert percentile([], 50) is None


def test_summarize_latency_of_empty_input() -> None:
    summary = summarize_latency([])

    assert summary.n == 0
    assert summary.p50 is None
    assert summary.p95 is None


# --- summarize ---


def test_summarize_counts_outcomes_statuses_and_category_language() -> None:
    cases = [
        CaseResult(
            "a", "en", "policy", [TurnResult(0, "m", "200", [_check(True)], "x", 0.1)], "pass"
        ),
        CaseResult("b", "en", "policy", [TurnResult(0, "m", "502", [], None, 0.1)], "http_error"),
        CaseResult("c", "hi", "general", [], "not_run"),
    ]

    summary = summarize(cases)

    assert summary.outcome_counts == {"pass": 1, "http_error": 1, "not_run": 1}
    assert summary.status_counts == {"200": 1, "502": 1}
    assert summary.category_language_counts[("policy", "en")] == {"pass": 1, "http_error": 1}
    assert summary.category_language_counts[("general", "hi")] == {"not_run": 1}


def test_summarize_status_counts_include_transport() -> None:
    cases = [
        CaseResult(
            "a", "en", "policy", [TurnResult(0, "m", "transport", [], None, None)], "http_error"
        )
    ]

    summary = summarize(cases)

    assert summary.status_counts == {"transport": 1}


# --- truncate_answer ---


def test_truncate_answer_under_the_limit_is_unchanged() -> None:
    assert truncate_answer("short answer") == "short answer"


def test_truncate_answer_exactly_at_the_limit_is_unchanged() -> None:
    text = "x" * 300

    assert truncate_answer(text) == text


def test_truncate_answer_over_the_limit_is_cut_with_an_ellipsis() -> None:
    text = "x" * 301

    truncated = truncate_answer(text)

    assert truncated == "x" * 300 + "…"


def test_truncate_answer_escapes_pipes_and_newlines() -> None:
    truncated = truncate_answer("a | b\nc")

    assert truncated == "a \\| b c"
