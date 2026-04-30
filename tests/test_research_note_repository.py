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
        decision_status="observing",
        decision_reason="样本外还不足，先观察。",
        confidence_score=72.5,
        linked_batch_id="batch-001",
        linked_parameter_group="batch-001:f2:s5:l1",
        created_at=datetime(2026, 4, 26, 11, 0, tzinfo=UTC),
    )

    repository.save_note(first)
    repository.save_note(second)

    loaded = repository.load_note("note-001")
    run_notes = repository.list_notes(target_type="run", target_id="run-001")

    assert loaded.labels == ("candidate", "review")
    assert loaded.decision_status == "candidate"
    second_loaded = repository.load_note("note-002")
    assert second_loaded.decision_status == "observing"
    assert second_loaded.decision_reason == "样本外还不足，先观察。"
    assert second_loaded.confidence_score == 72.5
    assert second_loaded.linked_batch_id == "batch-001"
    assert second_loaded.linked_parameter_group == "batch-001:f2:s5:l1"
    assert [note.note_id for note in run_notes] == ["note-001"]
    assert repository.list_note_ids(target_type="run") == ["note-001"]
    assert repository.list_note_ids(target_type="parameter_group") == ["note-002"]
    assert repository.list_note_ids(decision_status="observing") == ["note-002"]
    assert repository.list_note_ids(label="review") == ["note-001"]
    assert repository.list_note_ids(linked_batch_id="batch-001") == ["note-002"]
    assert repository.list_note_ids(linked_parameter_group="batch-001:f2:s5:l1") == ["note-002"]
    assert repository.list_notes(target_type="parameter_group", decision_status="observing")[0].note_id == "note-002"
