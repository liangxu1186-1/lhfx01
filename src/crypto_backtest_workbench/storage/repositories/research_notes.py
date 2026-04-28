"""Research note persistence for the local workbench."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

from crypto_backtest_workbench.domain.models import ResearchNote


class ResearchNoteRepository(Protocol):
    """Persistence contract for research notes."""

    def save_note(self, note: ResearchNote) -> Path:
        """Persist a research note."""

    def load_note(self, note_id: str) -> ResearchNote:
        """Load one persisted research note."""

    def list_note_ids(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[str]:
        """List persisted research note identifiers."""

    def list_notes(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[ResearchNote]:
        """List persisted research notes."""

    def delete_note(self, note_id: str) -> None:
        """Delete one persisted research note."""

    def delete_notes(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> int:
        """Delete persisted research notes matching a target filter."""


class FileResearchNoteRepository:
    """Filesystem-backed research note repository."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def save_note(self, note: ResearchNote) -> Path:
        notes_dir = self.base_dir / "research_notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        path = self._note_path(note.note_id)
        path.write_text(
            json.dumps(_json_ready(asdict(note)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load_note(self, note_id: str) -> ResearchNote:
        payload = json.loads(self._note_path(note_id).read_text(encoding="utf-8"))
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        payload["labels"] = tuple(payload.get("labels", ()))
        return ResearchNote(**payload)

    def list_note_ids(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[str]:
        notes_dir = self.base_dir / "research_notes"
        if not notes_dir.exists():
            return []
        note_ids: list[str] = []
        for path in notes_dir.iterdir():
            if not path.is_file() or path.suffix != ".json":
                continue
            note = self.load_note(path.stem)
            if target_type is not None and note.target_type != target_type:
                continue
            if target_id is not None and note.target_id != target_id:
                continue
            note_ids.append(note.note_id)
        return sorted(note_ids)

    def list_notes(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[ResearchNote]:
        notes = [
            self.load_note(note_id)
            for note_id in self.list_note_ids(target_type=target_type, target_id=target_id)
        ]
        return sorted(notes, key=lambda item: item.created_at, reverse=True)

    def delete_note(self, note_id: str) -> None:
        path = self._note_path(note_id)
        if not path.exists():
            raise FileNotFoundError(f"Research note not found: {note_id}")
        path.unlink()

    def delete_notes(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> int:
        note_ids = self.list_note_ids(target_type=target_type, target_id=target_id)
        for note_id in note_ids:
            self.delete_note(note_id)
        return len(note_ids)

    def _note_path(self, note_id: str) -> Path:
        return self.base_dir / "research_notes" / f"{note_id}.json"


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_ready(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, tuple):
        return [_json_ready(inner) for inner in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value
