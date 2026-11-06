from dataclasses import dataclass
from datetime import datetime

from evals.retrieval_metrics import OffTopicResult, QuestionResult, Summary


@dataclass(frozen=True)
class ReportHeader:
    run_date_utc: datetime
    commit_sha: str
    index_name: str
    embedding_model: str
    embedder_adapter: str
    vector_store_adapter: str
    min_score: float


def render_report(
    header: ReportHeader,
    results: list[QuestionResult],
    off_topic: list[OffTopicResult],
    overall: Summary,
    by_language: dict[str, Summary],
) -> str:
    lines: list[str] = [
        "# Retrieval evaluation",
        "",
        f"- Run date (UTC): {header.run_date_utc.isoformat()}",
        f"- Commit: {header.commit_sha}",
        f"- Index: {header.index_name}",
        f"- Embedding model: {header.embedding_model}",
        f"- Adapters: {header.embedder_adapter} / {header.vector_store_adapter}",
        f"- Threshold (RETRIEVAL_MIN_SCORE): {header.min_score}",
        "",
        "## Summary",
        "",
        "| Group | n | hit@1 | hit@5 | MRR | hit@5 after threshold "
        "| Mean top score | Min top score |",
        "|---|---|---|---|---|---|---|---|",
        _summary_row("overall", overall),
    ]
    lines.extend(_summary_row(language, by_language[language]) for language in sorted(by_language))

    lines += [
        "",
        "## Per question",
        "",
        "| Language | Question | Expected doc | First hit rank | hit@1 | hit@5 "
        "| hit@5 after threshold | Top score | Top doc |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    lines.extend(_question_row(result) for result in results)

    lines += [
        "",
        "## Off-topic queries",
        "",
        "| Query | Max score | Kept out |",
        "|---|---|---|",
    ]
    lines.extend(_off_topic_row(item) for item in off_topic)

    lowest_policy_top_score = min(
        (result.top_score for result in results if result.top_score is not None), default=None
    )
    highest_off_topic_score = max(
        (item.max_score for item in off_topic if item.max_score is not None), default=None
    )
    lines += [
        "",
        "## Calibration",
        "",
        f"- Lowest policy top score: {_fmt(lowest_policy_top_score)}",
        f"- Highest off-topic max score: {_fmt(highest_off_topic_score)}",
        f"- Threshold: {header.min_score}",
    ]
    return "\n".join(lines) + "\n"


def _summary_row(label: str, summary: Summary) -> str:
    return (
        f"| {label} | {summary.n} | {_fmt(summary.hit_at_1_rate)} | {_fmt(summary.hit_at_5_rate)} "
        f"| {_fmt(summary.mrr)} | {_fmt(summary.hit_at_5_after_threshold_rate)} "
        f"| {_fmt(summary.mean_top_score)} | {_fmt(summary.min_top_score)} |"
    )


def _question_row(result: QuestionResult) -> str:
    rank = result.first_hit_rank if result.first_hit_rank is not None else "—"
    return (
        f"| {result.language} | {result.question} | {result.expected_doc} | {rank} "
        f"| {_mark(result.hit_at_1)} | {_mark(result.hit_at_5)} "
        f"| {_mark(result.hit_at_5_after_threshold)} | {_fmt(result.top_score)} "
        f"| {result.top_doc or '—'} |"
    )


def _off_topic_row(item: OffTopicResult) -> str:
    status = "kept out" if item.kept_out else "LEAKED"
    return f"| {item.query} | {_fmt(item.max_score)} | {status} |"


def _mark(value: bool) -> str:
    return "✓" if value else "✗"


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "—"
