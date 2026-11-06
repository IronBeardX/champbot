import re
from datetime import date
from pathlib import Path

from champbot.chat.answer.presentation.serializers import ChatRequest
from champbot.knowledge.ingest.domain.chunker import chunk_document
from champbot.knowledge.ingest.domain.document import parse_policy_document
from evals.conversation_metrics import CaseSpec, build_history, load_cases, render_message

CASES_FILE = Path(__file__).parents[1] / "data" / "eval" / "conversations.json"
POLICIES_DIR = Path(__file__).parents[1] / "data" / "policies"
_ABSOLUTE_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def real_cases() -> list[CaseSpec]:
    return load_cases(CASES_FILE)


def real_corpus_source_urls() -> set[str]:
    urls: set[str] = set()
    for path in sorted(POLICIES_DIR.glob("*.md")):
        doc = parse_policy_document(path.stem, path.read_text())
        urls.update(chunk.source_url for chunk in chunk_document(doc))
    return urls


def test_case_ids_are_unique() -> None:
    cases = real_cases()
    ids = [case.id for case in cases]

    assert len(ids) == len(set(ids))


def test_case_and_turn_counts_are_in_range() -> None:
    cases = real_cases()
    turn_count = sum(len(case.turns) for case in cases)

    assert 20 <= len(cases) <= 30
    assert turn_count <= 40


def test_at_least_five_hindi_cases() -> None:
    cases = real_cases()
    hindi_cases = [case for case in cases if case.language == "hi"]

    assert len(hindi_cases) >= 5


def test_every_intent_and_off_topic_and_multi_turn_appear() -> None:
    cases = real_cases()
    intents = {turn.intent for case in cases for turn in case.turns}
    off_topic_count = sum(1 for case in cases for turn in case.turns if turn.off_topic)
    multi_turn_count = sum(1 for case in cases if len(case.turns) > 1)

    assert intents == {"policy", "flight_search", "general"}
    assert off_topic_count >= 1
    assert multi_turn_count >= 1


def test_every_cited_url_is_a_real_corpus_source_url() -> None:
    cases = real_cases()
    real_urls = real_corpus_source_urls()

    for case in cases:
        for turn in case.turns:
            if turn.cited_url is not None:
                assert turn.cited_url in real_urls, f"{case.id}: {turn.cited_url} not in corpus"


def test_no_message_contains_an_absolute_iso_date() -> None:
    cases = real_cases()

    for case in cases:
        for turn in case.turns:
            assert not _ABSOLUTE_DATE_PATTERN.search(turn.message), (
                f"{case.id}: message has an absolute date, use {{date+N}}/{{date-N}}"
            )


def test_every_rendered_message_validates_through_chat_request() -> None:
    cases = real_cases()
    today = date(2026, 11, 6)

    for case in cases:
        pairs: list[tuple[str, str]] = []
        for turn in case.turns:
            rendered = render_message(turn.message, today)
            request = ChatRequest.model_validate(
                {"message": rendered, "history": build_history(pairs)}
            )
            pairs.append((rendered, "placeholder answer"))
            assert request.message == rendered
