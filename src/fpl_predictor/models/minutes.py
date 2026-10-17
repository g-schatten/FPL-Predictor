from __future__ import annotations

from typing import Any

from fpl_predictor.models.engine import MinutesProfile

# Recent matches say more about selection than August did.
DECAY_HALF_LIFE = 4.0
CAMEO_MINUTES = 20.0
START_REACHES_60 = 0.85


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def availability(player: dict[str, Any]) -> float:
    status = str(player.get("status") or "a")
    chance = player.get("chance_of_playing_next_round")
    if status in {"u", "s"}:
        return 0.0
    if chance is not None:
        return max(0.0, min(1.0, float(chance) / 100.0))
    if status == "i":
        return 0.0
    if status == "d":
        return 0.25
    return 1.0


def expected_minutes(
    player: dict[str, Any],
    *,
    completed_gws: int,
    history: dict[str, Any] | None = None,
) -> float:
    avail = availability(player)
    if avail <= 0:
        return 0.0

    recent: list[int] = []
    if history:
        rows = list(history.get("history") or [])
        for row in rows[-4:]:
            recent.append(int(row.get("minutes") or 0))
    if recent:
        typical = sum(recent) / len(recent)
    else:
        minutes = _to_float(player.get("minutes"))
        starts = _to_float(player.get("starts"))
        if starts >= 1:
            typical = minutes / max(starts, 1)
        else:
            typical = minutes / max(completed_gws, 1)
    typical = max(0.0, min(90.0, typical))
    if typical == 0 and avail >= 0.75 and _to_float(player.get("now_cost")) >= 45:
        # New or returning player with no minutes yet: do not invent a full 90.
        typical = 50.0
    return typical * avail


def _decayed_history(history: dict[str, Any] | None) -> list[tuple[float, float, bool]]:
    """(weight, minutes, started) per past appearance, newest weighted highest."""
    if not history:
        return []
    rows = list(history.get("history") or [])
    weighted: list[tuple[float, float, bool]] = []
    for offset, row in enumerate(reversed(rows)):
        weight = 0.5 ** (offset / DECAY_HALF_LIFE)
        minutes = _to_float(row.get("minutes"))
        started = bool(row.get("starts")) or minutes >= 60
        weighted.append((weight, minutes, started))
    return weighted


def minutes_profile(
    player: dict[str, Any],
    *,
    team_games: int,
    history: dict[str, Any] | None = None,
) -> MinutesProfile:
    """Expected minutes plus P(appear) and P(60+), which gate appearance and clean-sheet points.

    Season aggregates cannot separate "always plays 20 minutes" from "started once in four",
    so `starts` carries the selection signal and leftover minutes become cameos.
    """
    avail = availability(player)
    if avail <= 0:
        return MinutesProfile(expected=0.0, p_appear=0.0, p_long=0.0)

    rows = _decayed_history(history)
    if rows:
        total_weight = sum(w for w, _, _ in rows)
        start_share = sum(w for w, _, started in rows if started) / total_weight
        appear_share = sum(w for w, minutes, _ in rows if minutes > 0) / total_weight
        long_share = sum(w for w, minutes, _ in rows if minutes >= 60) / total_weight
        expected = sum(w * minutes for w, minutes, _ in rows) / total_weight
    else:
        games = max(1, int(team_games))
        minutes = _to_float(player.get("minutes"))
        starts = _to_float(player.get("starts"))
        start_share = min(1.0, starts / games)
        # Minutes beyond a full game per start must have come off the bench in other matches.
        cameo_minutes = max(0.0, minutes - starts * 90.0)
        cameo_share = min(max(0.0, 1.0 - start_share), (cameo_minutes / CAMEO_MINUTES) / games)
        appear_share = min(1.0, start_share + cameo_share)
        long_share = START_REACHES_60 * start_share
        per_start = min(90.0, (minutes - cameo_minutes) / starts) if starts >= 1 else 0.0
        expected = start_share * per_start + cameo_share * CAMEO_MINUTES
        if expected == 0 and avail >= 0.75 and _to_float(player.get("now_cost")) >= 45:
            # Signing or long-term returnee with no minutes yet: assume a rotation role.
            expected, appear_share, long_share = 45.0, 0.6, 0.4

    return MinutesProfile(
        expected=max(0.0, min(90.0, expected)) * avail,
        p_appear=max(0.0, min(1.0, appear_share)) * avail,
        p_long=max(0.0, min(1.0, min(long_share, appear_share))) * avail,
    )
