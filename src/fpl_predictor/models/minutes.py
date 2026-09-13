from __future__ import annotations

from typing import Any


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
