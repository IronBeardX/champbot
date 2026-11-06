from dataclasses import dataclass
from datetime import datetime

from evals.conversation_metrics import CaseResult, Outcome, RunSummary, truncate_answer

_OUTCOME_ORDER: list[Outcome] = ["pass", "fail", "http_error", "not_run"]


@dataclass(frozen=True)
class ReportHeader:
    run_date_utc: datetime
    commit_sha: str
    base_url: str
    model: str
    case_count: int
    turn_count: int
    pacing_seconds: float
    max_retries: int


def render_report(header: ReportHeader, cases: list[CaseResult], summary: RunSummary) -> str:
    lines: list[str] = [
        "# Conversation evaluation",
        "",
        f"- Run date (UTC): {header.run_date_utc.isoformat()}",
        f"- Commit: {header.commit_sha}",
        f"- Base URL: {header.base_url}",
        f"- Model: {header.model}",
        f"- Cases: {header.case_count} / Turns: {header.turn_count}",
        f"- Pacing: at least {header.pacing_seconds}s between request starts, "
        f"up to {header.max_retries} retries on 429/503",
        "- Note: a later merge makes the recorded commit stale relative to what answered.",
        "",
        "## Summary by outcome",
        "",
        "| Outcome | Count |",
        "|---|---|",
    ]
    lines.extend(
        f"| {outcome} | {summary.outcome_counts.get(outcome, 0)} |" for outcome in _OUTCOME_ORDER
    )

    lines += [
        "",
        "## Summary by category and language",
        "",
        "| Category | Language | pass | fail | http_error | not_run |",
        "|---|---|---|---|---|---|",
    ]
    for category, language in sorted(summary.category_language_counts):
        counts = summary.category_language_counts[(category, language)]
        lines.append(
            f"| {category} | {language} | {counts.get('pass', 0)} | {counts.get('fail', 0)} "
            f"| {counts.get('http_error', 0)} | {counts.get('not_run', 0)} |"
        )

    lines += [
        "",
        "## HTTP statuses",
        "",
        "| Status | Count |",
        "|---|---|",
    ]
    lines.extend(
        f"| {status} | {summary.status_counts[status]} |"
        for status in sorted(summary.status_counts)
    )

    lines += [
        "",
        "## Latency",
        "",
        f"- n: {summary.latency.n}",
        f"- p50: {_fmt_seconds(summary.latency.p50)}",
        f"- p95: {_fmt_seconds(summary.latency.p95)}",
        "",
        "## Per case",
        "",
        "| Case | Language | Category | Turns | Outcome |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {case.id} | {case.language} | {case.category} | {len(case.turns)} | {case.outcome} |"
        for case in cases
    )

    lines += ["", "## Failures", ""]
    failure_lines = list(_failure_lines(cases))
    lines.extend(failure_lines if failure_lines else ["None."])

    return "\n".join(lines) + "\n"


def _failure_lines(cases: list[CaseResult]) -> list[str]:
    lines: list[str] = []
    for case in cases:
        for turn in case.turns:
            failed = [check for check in turn.checks if not check.passed]
            if not failed:
                continue
            lines.append(f"### {case.id} — turn {turn.turn_index}")
            lines.append(f"- Message: {turn.message}")
            for check in failed:
                lines.append(f"- {check.name}: expected `{check.expected}`, got `{check.actual}`")
            if turn.answer is not None:
                lines.append(f"- Answer: {truncate_answer(turn.answer)}")
            lines.append("")
    return lines


def _fmt_seconds(value: float | None) -> str:
    return f"{value:.3f}s" if value is not None else "n/a"
