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


class _FakeClient:
    def __init__(self, payloads: dict) -> None:
        self.payloads, self.calls = payloads, []

    def event_live(self, event_id: int) -> dict:
        self.calls.append(event_id)
        return self.payloads[event_id]


def _live(minutes_per_fixture: list[int]) -> dict:
    explain = [
        {"fixture": i, "stats": [{"identifier": "minutes", "value": m}]} for i, m in enumerate(minutes_per_fixture)
    ]
    return {"elements": [{"id": 7, "explain": explain}]}


def test_live_minutes_feed_the_same_model_the_backtest_scores(tmp_path, monkeypatch) -> None:
    import math

    import pandas as pd

    from fpl_predictor.data.snapshots import live_histories
    from fpl_predictor.eval.backtest import minutes_from_history
    from fpl_predictor.models.minutes import minutes_profile

    monkeypatch.setenv("FPL_HOME", str(tmp_path))
    events = [
        {"id": gw, "finished": gw < 4, "data_checked": gw < 4, "deadline_time": "2026-08-21T17:30:00Z"}
        for gw in (1, 2, 3, 4)
    ]
    client = _FakeClient({1: _live([90]), 2: _live([0]), 3: _live([25])})
    histories = live_histories(client, {"events": events})
    assert [row["minutes"] for row in histories["7"]["history"]] == [90, 0, 25]

    live = minutes_profile({"status": "a"}, team_games=3, history=histories["7"])
    archive = pd.DataFrame({"element": [7, 7, 7], "gw": [1, 2, 3], "minutes": [90.0, 0.0, 25.0]})
    backtest = minutes_from_history(archive)[7]
    for field in ("expected", "p_appear", "p_long"):
        assert math.isclose(getattr(live, field), getattr(backtest, field))

    live_histories(client, {"events": events})
    assert client.calls == [1, 2, 3]  # finished, checked gameweeks come from the cache


def test_double_gameweek_gives_one_row_per_fixture(tmp_path, monkeypatch) -> None:
    from fpl_predictor.data.snapshots import live_histories

    monkeypatch.setenv("FPL_HOME", str(tmp_path))
    events = [{"id": 1, "finished": True, "data_checked": False, "deadline_time": "2026-08-21T17:30:00Z"}]
    histories = live_histories(_FakeClient({1: _live([90, 30])}), {"events": events})
    assert [row["minutes"] for row in histories["7"]["history"]] == [90, 30]


def test_a_truncated_cache_file_is_fetched_again(tmp_path, monkeypatch) -> None:
    from fpl_predictor.data.snapshots import live_histories

    monkeypatch.setenv("FPL_HOME", str(tmp_path))
    cache = tmp_path / "data" / "snapshots" / "live"
    cache.mkdir(parents=True)
    (cache / "2026-gw01.json").write_text('{"7": [9', encoding="utf-8")  # Ctrl+C mid-write
    events = [{"id": 1, "finished": True, "data_checked": True, "deadline_time": "2026-08-21T17:30:00Z"}]
    client = _FakeClient({1: _live([90])})
    assert live_histories(client, {"events": events})["7"]["history"] == [{"round": 1, "minutes": 90}]
    assert client.calls == [1]


def test_a_new_signing_without_minutes_keeps_the_rotation_guess() -> None:
    from fpl_predictor.models.minutes import minutes_profile

    player = {"status": "a", "now_cost": 60, "minutes": 0, "starts": 0}
    signed = minutes_profile(player, team_games=21, history={"history": [{"round": 21, "minutes": 0}]})
    unused = minutes_profile(player, team_games=21, history={"history": [{"round": gw, "minutes": 0} for gw in (19, 20, 21)]})
    assert signed.expected == 45.0  # one blank row since registering: today's guess
    assert unused.expected == 0.0  # three blanks while fit: he is not being picked
