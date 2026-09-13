from datetime import datetime, timezone
from pathlib import Path

from fpl_predictor.data.snapshots import Snapshot


def test_pre_deadline_uses_pulled_at() -> None:
    snapshot = Snapshot(
        path=Path("."),
        meta={"pulled_at": "2026-09-13T10:00:00Z"},
        bootstrap={
            "events": [{"id": 5, "deadline_time": "2026-09-18T17:30:00Z"}],
            "elements": [],
            "teams": [],
        },
        fixtures=[],
        event_status={},
        set_piece_notes={},
        histories={},
    )
    assert snapshot.is_pre_deadline(5)
    snapshot.meta["pulled_at"] = "2026-09-18T18:00:00Z"
    assert snapshot.pulled_at == datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    assert not snapshot.is_pre_deadline(5)
