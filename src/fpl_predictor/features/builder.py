from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fpl_predictor.data.rules import POSITIONS
from fpl_predictor.data.snapshots import Snapshot
from fpl_predictor.features.leakage import assert_no_leakage
from fpl_predictor.models.engine import PointsBreakdown, project_fixture
from fpl_predictor.models.minutes import availability, minutes_profile
from fpl_predictor.models.rates import (
    accum_from_element,
    build_position_priors,
    build_rates,
    cap_match_outliers,
)
from fpl_predictor.models.team_strength import (
    build_league_context,
    fdr_priors,
    team_games_from_fixtures,
    team_xg_from_players,
)

# The upcoming gameweek is what the user is actually picking for. Later gameweeks only
# break ties when a longer horizon is requested.
DEFAULT_WEIGHTS = (1.0, 0.55, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1)


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
    breakdown: dict[str, float] = field(default_factory=dict)
    opponents: list[str] = field(default_factory=list)

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


def build_league_view(snapshot: Snapshot):
    """Team attack / defence strength for the current snapshot.

    Official `teams[].strength` is null this season, so strength is estimated from finished
    results and aggregated player xG, shrunk toward an FDR-based prior while samples are small.
    """
    players = snapshot.players()
    teams = snapshot.teams_by_id()
    games = team_games_from_fixtures(snapshot.fixtures)
    played = Counter(game.team_id for game in games)
    return build_league_context(
        games,
        xg_per_game=team_xg_from_players(players, dict(played)),
        priors=fdr_priors(snapshot.fixtures, teams.keys()),
    )


def build_projections(
    snapshot: Snapshot,
    *,
    horizon: int = 1,
    weights: tuple[float, ...] | None = None,
    model_adjustments: dict[int, float] | None = None,
) -> list[PlayerProjection]:
    nxt = snapshot.next_event() or snapshot.current_event()
    if nxt is None:
        raise RuntimeError("No current or next gameweek in snapshot.")
    start_event = int(nxt["id"])

    weight_row = weights or DEFAULT_WEIGHTS
    teams = snapshot.teams_by_id()
    league = build_league_view(snapshot)
    adjustments = model_adjustments or {}

    raw_players = snapshot.players()
    team_games = Counter(game.team_id for game in team_games_from_fixtures(snapshot.fixtures))
    accums = {
        int(raw["id"]): cap_match_outliers(
            accum_from_element(raw, team_games=team_games.get(int(raw["team"]), 0)),
            snapshot.histories.get(str(raw["id"])),
        )
        for raw in raw_players
    }
    priors = build_position_priors(accums.values())

    projections: list[PlayerProjection] = []
    for raw in raw_players:
        if not raw.get("can_select", True):
            continue
        player_id = int(raw["id"])
        team_id = int(raw["team"])
        element_type = int(raw["element_type"])
        avail = availability(raw)
        rates = build_rates(accums[player_id], priors)
        minutes = minutes_profile(
            raw,
            team_games=team_games.get(team_id, 0),
            history=snapshot.histories.get(str(player_id)),
        )

        fixtures_by_gw = _upcoming_for_team(snapshot.fixtures, team_id, start_event, horizon)
        xpts_by_gw: dict[int, float] = {}
        next_breakdown: dict[str, float] = {}
        opponents: list[str] = []

        for offset in range(horizon):
            event_id = start_event + offset
            gw_points = 0.0
            for fixture in fixtures_by_gw.get(event_id, []):
                home = int(fixture.get("team_h") or 0) == team_id
                opponent_id = int(fixture["team_a"] if home else fixture["team_h"])
                result = project_fixture(
                    rates,
                    minutes,
                    league,
                    team_id=team_id,
                    opponent_id=opponent_id,
                    home=home,
                )
                gw_points += result.total
                if offset == 0:
                    opponents.append(
                        f"{teams.get(opponent_id, {}).get('short_name', opponent_id)}"
                        f"{' (H)' if home else ' (A)'}"
                    )
                    next_breakdown = result.as_dict()
            xpts_by_gw[event_id] = gw_points

        weighted = 0.0
        for offset, pts in enumerate(xpts_by_gw.values()):
            weight = weight_row[offset] if offset < len(weight_row) else weight_row[-1]
            weighted += weight * pts
        weighted *= 1.0 + adjustments.get(player_id, 0.0)

        flags: list[str] = []
        if raw.get("status") != "a":
            flags.append(f"status:{raw.get('status')}")
        if raw.get("news"):
            flags.append("news")
        if avail < 0.75:
            flags.append("avail<75")
        if minutes.p_long < 0.5:
            flags.append("minutes-risk")
        if not fixtures_by_gw.get(start_event):
            flags.append("blank")

        projections.append(
            PlayerProjection(
                player_id=player_id,
                code=int(raw.get("code") or 0),
                web_name=str(raw.get("web_name") or raw.get("second_name") or raw["id"]),
                team_id=team_id,
                team_short=str(teams.get(team_id, {}).get("short_name") or team_id),
                position=POSITIONS.get(element_type, "?"),
                element_type=element_type,
                now_cost=int(raw["now_cost"]),
                status=str(raw.get("status") or "a"),
                news=str(raw.get("news") or ""),
                chance_next=None
                if raw.get("chance_of_playing_next_round") is None
                else float(raw["chance_of_playing_next_round"]),
                availability=avail,
                xmins=minutes.expected,
                ep_next=_to_float(raw.get("ep_next")),
                form=_to_float(raw.get("form")),
                xpts_by_gw=xpts_by_gw,
                xpts=max(0.0, weighted),
                risk_flags=flags,
                can_select=bool(raw.get("can_select", True)),
                selected_by=_to_float(raw.get("selected_by_percent")),
                breakdown=next_breakdown,
                opponents=opponents,
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
            "opponents": ", ".join(item.opponents),
        }
        for key, value in item.breakdown.items():
            row[f"x_{key}"] = value
        for gw, pts in item.xpts_by_gw.items():
            row[f"gw{gw}"] = round(pts, 2)
        rows.append(row)
    frame = pd.DataFrame(rows)
    assert_no_leakage(list(frame.columns))
    return frame
