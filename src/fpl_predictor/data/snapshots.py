from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fpl_predictor.data.fpl_api import FplClient
from fpl_predictor.data.rules import GameRules, parse_rules
from fpl_predictor.paths import current_pointer, snapshots_dir


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ")


@dataclass
class Snapshot:
    path: Path
    meta: dict[str, Any]
    bootstrap: dict[str, Any]
    fixtures: list[dict[str, Any]]
    event_status: dict[str, Any]
    set_piece_notes: Any
    histories: dict[str, Any]

    @property
    def rules(self) -> GameRules:
        return parse_rules(self.bootstrap)

    @property
    def pulled_at(self) -> datetime:
        raw = self.meta["pulled_at"]
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    def current_event(self) -> dict[str, Any] | None:
        return next((e for e in self.bootstrap.get("events", []) if e.get("is_current")), None)

    def next_event(self) -> dict[str, Any] | None:
        return next((e for e in self.bootstrap.get("events", []) if e.get("is_next")), None)

    def previous_event(self) -> dict[str, Any] | None:
        return next((e for e in self.bootstrap.get("events", []) if e.get("is_previous")), None)

    def teams_by_id(self) -> dict[int, dict[str, Any]]:
        return {int(t["id"]): t for t in self.bootstrap.get("teams", [])}

    def players(self) -> list[dict[str, Any]]:
        return list(self.bootstrap.get("elements", []))

    def deadline_for(self, event_id: int) -> datetime | None:
        for event in self.bootstrap.get("events", []):
            if int(event["id"]) != event_id:
                continue
            raw = event.get("deadline_time")
            if not raw:
                return None
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return None

    def is_pre_deadline(self, event_id: int) -> bool:
        deadline = self.deadline_for(event_id)
        if deadline is None:
            return True
        return self.pulled_at < deadline


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_snapshot(
    *,
    bootstrap: dict[str, Any],
    fixtures: list[dict[str, Any]],
    event_status: dict[str, Any],
    set_piece_notes: Any,
    histories: dict[str, Any] | None = None,
    pulled_at: datetime | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> Snapshot:
    pulled_at = pulled_at or _utc_now()
    dest = snapshots_dir() / _stamp(pulled_at)
    dest.mkdir(parents=True, exist_ok=True)
    current = next((e for e in bootstrap.get("events", []) if e.get("is_current")), {})
    nxt = next((e for e in bootstrap.get("events", []) if e.get("is_next")), {})
    meta = {
        "pulled_at": pulled_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "current_event": current.get("id"),
        "next_event": nxt.get("id"),
        "next_deadline": nxt.get("deadline_time"),
        "n_players": len(bootstrap.get("elements", [])),
        "n_fixtures": len(fixtures),
        "n_histories": len(histories or {}),
        **(extra_meta or {}),
    }
    _write_json(dest / "meta.json", meta)
    _write_json(dest / "bootstrap.json", bootstrap)
    _write_json(dest / "fixtures.json", fixtures)
    _write_json(dest / "event_status.json", event_status)
    _write_json(dest / "set_piece_notes.json", set_piece_notes)
    _write_json(dest / "histories.json", histories or {})
    current_pointer().write_text(str(dest), encoding="utf-8")
    return Snapshot(
        path=dest,
        meta=meta,
        bootstrap=bootstrap,
        fixtures=fixtures,
        event_status=event_status,
        set_piece_notes=set_piece_notes,
        histories=histories or {},
    )


def load_snapshot(path: Path) -> Snapshot:
    path = path.resolve()
    return Snapshot(
        path=path,
        meta=_read_json(path / "meta.json"),
        bootstrap=_read_json(path / "bootstrap.json"),
        fixtures=_read_json(path / "fixtures.json"),
        event_status=_read_json(path / "event_status.json"),
        set_piece_notes=_read_json(path / "set_piece_notes.json"),
        histories=_read_json(path / "histories.json") if (path / "histories.json").exists() else {},
    )


def load_current() -> Snapshot:
    pointer = current_pointer()
    if not pointer.exists():
        raise FileNotFoundError("No snapshot yet. Run `fpl refresh` first.")
    return load_snapshot(Path(pointer.read_text(encoding="utf-8").strip()))


def refresh_snapshot(client: FplClient | None = None, *, full: bool = False) -> Snapshot:
    own_client = client is None
    client = client or FplClient()
    try:
        bootstrap = client.bootstrap()
        fixtures = client.fixtures()
        try:
            event_status = client.event_status()
        except RuntimeError:
            event_status = {}
        try:
            set_piece_notes = client.set_piece_notes()
        except RuntimeError:
            set_piece_notes = {}
        histories: dict[str, Any] = {}
        if full:
            from rich.progress import Progress

            selectable = [
                int(p["id"])
                for p in bootstrap.get("elements", [])
                if p.get("can_select", True) and p.get("status") != "u"
            ]
            with Progress() as progress:
                task = progress.add_task("Player histories", total=len(selectable))
                for player_id in selectable:
                    try:
                        histories[str(player_id)] = client.element_summary(player_id)
                    except RuntimeError:
                        pass
                    progress.advance(task)
        return save_snapshot(
            bootstrap=bootstrap,
            fixtures=fixtures,
            event_status=event_status,
            set_piece_notes=set_piece_notes,
            histories=histories,
            extra_meta={"full": full},
        )
    finally:
        if own_client:
            client.close()
