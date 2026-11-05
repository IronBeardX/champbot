from pathlib import Path

import pytest

from champbot.knowledge.ingest.presentation.cli import main

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


def test_without_dry_run_exits_with_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_doc(tmp_path, "checked-baggage.md", VALID_DOC)

    exit_code = main([str(tmp_path)])

    assert exit_code == 2
    assert "IRO-180" in capsys.readouterr().err


def test_an_invalid_document_exits_with_code_one_and_an_error_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_doc(tmp_path, "broken.md", "no front matter here\n")

    exit_code = main(["--dry-run", str(tmp_path)])

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "broken" in err
