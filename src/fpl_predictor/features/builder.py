from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fpl_predictor.data.rules import POSITIONS
from fpl_predictor.data.snapshots import Snapshot
from fpl_predictor.features.leakage import assert_no_leakage
from fpl_predictor.models.minutes import availability, expected_minutes
from fpl_predictor.models.points import project_gameweek_points

DEFAULT_WEIGHTS = (1.0, 0.8, 0.6, 0.4)


@dataclass
class PlayerProjection:
    player_id: int
    code: int
    web_name: str
    team_id: int
    team_short: str
    position: str
    element_type: int
    now_cost: int
    status: str
    news: str
    chance_next: float | None
    availability: float
    xmins: float
    ep_next: float
    form: float
    xpts_by_gw: dict[int, float]
    xpts: float
    risk_flags: list[str] = field(default_factory=list)
    can_select: bool = True
    selected_by: float = 0.0

    @property
    def next_xpts(self) -> float:
        if not self.xpts_by_gw:
            return 0.0
        return next(iter(self.xpts_by_gw.values()))


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _upcoming_for_team(
    fixtures: list[dict[str, Any]],
    team_id: int,
    start_event: int,
    horizon: int,
) -> dict[int, list[dict[str, Any]]]:
    end_event = start_event + horizon - 1
    grouped: dict[int, list[dict[str, Any]]] = {}
    for fixture in fixtures:
        event = fixture.get("event")
        if event is None:
            continue
        event = int(event)
        if event < start_event or event > end_event:
            continue
        if int(fixture.get("team_h") or 0) != team_id and int(fixture.get("team_a") or 0) != team_id:
            continue
        grouped.setdefault(event, []).append(fixture)
    return grouped


def build_projections(
    snapshot: Snapshot,
    *,
    horizon: int = 4,
    weights: tuple[float, ...] | None = None,
    model_adjustments: dict[int, float] | None = None,
) -> list[PlayerProjection]:
    nxt = snapshot.next_event() or snapshot.current_event()
    if nxt is None:
        raise RuntimeError("No current or next gameweek in snapshot.")
    start_event = int(nxt["id"])

    weight_row = weights or DEFAULT_WEIGHTS
    teams = snapshot.teams_by_id()
    completed = [
        e for e in snapshot.bootstrap.get("events", []) if e.get("finished") or e.get("data_checked")
    ]
    completed_count = max(1, len(completed))
    adjustments = model_adjustments or {}

    projections: list[PlayerProjection] = []
    for raw in snapshot.players():
        if not raw.get("can_select", True):
            continue
        team_id = int(raw["team"])
        element_type = int(raw["element_type"])
        avail = availability(raw)
        xmins = expected_minutes(raw, completed_gws=completed_count, history=snapshot.histories.get(str(raw["id"])))
        ep_next = _to_float(raw.get("ep_next"))
        form = _to_float(raw.get("form"))
        fixtures_by_gw = _upcoming_for_team(snapshot.fixtures, team_id, start_event, horizon)
        xpts_by_gw: dict[int, float] = {}
        flags: list[str] = []
        if raw.get("status") != "a":
            flags.append(f"status:{raw.get('status')}")
        if raw.get("news"):
            flags.append("news")
        if avail < 0.75:
            flags.append("avail<75")
        if xmins < 45:
            flags.append("minutes-risk")

        for offset in range(horizon):
            event_id = start_event + offset
            fx = fixtures_by_gw.get(event_id, [])
            if not fx:
                xpts_by_gw[event_id] = 0.0
                continue
            gw_points = 0.0
            for fixture in fx:
                home = int(fixture.get("team_h") or 0) == team_id
                fdr = int(fixture["team_h_difficulty"] if home else fixture["team_a_difficulty"])
                first_horizon = offset == 0
                gw_points += project_gameweek_points(
                    ep_next=ep_next,
                    form=form,
                    availability=avail,
                    xmins=xmins,
                    fdr=fdr,
                    home=home,
                    use_official_ep=first_horizon,
                )
            xpts_by_gw[event_id] = gw_points

        weighted = 0.0
        for offset, (event_id, pts) in enumerate(xpts_by_gw.items()):
            w = weight_row[offset] if offset < len(weight_row) else weight_row[-1]
            weighted += w * pts
        weighted *= 1.0 + adjustments.get(int(raw["id"]), 0.0)
        weighted -= 0.35 * (1.0 - avail)

        projections.append(
            PlayerProjection(
                player_id=int(raw["id"]),
                code=int(raw.get("code") or 0),
                web_name=str(raw.get("web_name") or raw.get("second_name") or raw["id"]),
                team_id=team_id,
                team_short=str(teams.get(team_id, {}).get("short_name") or team_id),
                position=POSITIONS.get(element_type, "?"),
                element_type=element_type,
                now_cost=int(raw["now_cost"]),
                status=str(raw.get("status") or "a"),
                news=str(raw.get("news") or ""),
                chance_next=None if raw.get("chance_of_playing_next_round") is None else float(raw["chance_of_playing_next_round"]),
                availability=avail,
                xmins=xmins,
                ep_next=ep_next,
                form=form,
                xpts_by_gw=xpts_by_gw,
                xpts=max(0.0, weighted),
                risk_flags=flags,
                can_select=bool(raw.get("can_select", True)),
                selected_by=_to_float(raw.get("selected_by_percent")),
            )
        )
    return projections


def projections_frame(projections: list[PlayerProjection]) -> pd.DataFrame:
    rows = []
    for item in projections:
        row = {
            "player_id": item.player_id,
            "web_name": item.web_name,
            "team": item.team_short,
            "pos": item.position,
            "cost": item.now_cost / 10,
            "xpts": round(item.xpts, 3),
            "xmins": round(item.xmins, 1),
            "avail": item.availability,
            "ep_next": item.ep_next,
            "form": item.form,
            "status": item.status,
            "news": item.news,
        }
        for gw, pts in item.xpts_by_gw.items():
            row[f"gw{gw}"] = round(pts, 2)
        rows.append(row)
    frame = pd.DataFrame(rows)
    assert_no_leakage(list(frame.columns))
    return frame
