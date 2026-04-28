from datetime import UTC, datetime
from pathlib import Path

from crypto_backtest_workbench.domain.models import ResearchNote
from crypto_backtest_workbench.storage.repositories import FileResearchNoteRepository


def test_file_research_note_repository_persists_and_filters_notes(tmp_path: Path) -> None:
    repository = FileResearchNoteRepository(tmp_path)
    first = ResearchNote(
        note_id="note-001",
        target_type="run",
        target_id="run-001",
        content="first note",
        author="alice",
        labels=("candidate", "review"),
        created_at=datetime(2026, 4, 26, 10, 0, tzinfo=UTC),
    )
    second = ResearchNote(
        note_id="note-002",
        target_type="parameter_group",
        target_id="batch-001:f2:s5:l1",
        content="second note",
        author="bob",
        labels=("candidate",),
        created_at=datetime(2026, 4, 26, 11, 0, tzinfo=UTC),
    )

    repository.save_note(first)
    repository.save_note(second)

    loaded = repository.load_note("note-001")
    run_notes = repository.list_notes(target_type="run", target_id="run-001")

    assert loaded.labels == ("candidate", "review")
    assert [note.note_id for note in run_notes] == ["note-001"]
    assert repository.list_note_ids(target_type="run") == ["note-001"]
    assert repository.list_note_ids(target_type="parameter_group") == ["note-002"]
