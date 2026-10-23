from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable

# A player with 120 minutes and one goal is not a 0.75 xG90 striker. Attacking rates are
# pulled toward the position median by this many pseudo-minutes of prior.
#
# Rates are deliberately season-long rather than recency weighted: in the walk-forward test
# (docs/EVAL.md) a 4-match half-life cost 0.009 NDCG@20 versus weighting every completed
# match equally. Recent form is the noisiest way to rank players.
PRIOR_MINUTES = {
    "attack": 320.0,
    "defence": 220.0,
    "bonus": 260.0,
}
# No single match may add more than this much xG (or xA) to a player's season total. One
# penalty-laden game otherwise dominates a short season: walk-forward NDCG and squad points
# improved on both 2025-26 and 2024-25 (docs/EVAL.md).
MATCH_CAP = 1.0
MIN_MINUTES_FOR_PRIOR = 450  # who counts as an established player when building priors


@dataclass
class PlayerAccum:
    """Everything the engine needs about one player's completed matches."""

    element_type: int
    minutes: float
    appearances: float
    starts: float
    xg: float
    xa: float
    bonus: float
    dc: float  # qualifying defensive actions, not points
    saves: float
    yellow_cards: float
    long_starts: float = 0.0  # matches with 60+ minutes
    xgc: float = 0.0

    def per_90(self, total: float) -> float:
        if self.minutes <= 0:
            return 0.0
        return total * 90.0 / self.minutes


@dataclass
class PlayerRates:
    element_type: int
    xg90: float
    xa90: float
    bonus90: float
    dc90: float
    saves90: float
    yc90: float
    minutes: float
    start_share: float
    long_share: float

    @property
    def sample_note(self) -> str:
        return f"{self.minutes:.0f} min played"


PositionPriors = dict[int, dict[str, float]]


def build_position_priors(accums: Iterable[PlayerAccum]) -> PositionPriors:
    """Median per-90 rates among established players, per position.

    Medians, not means: a handful of elite scorers should not drag the prior up for
    every squad player at the same position.
    """
    buckets: dict[int, dict[str, list[float]]] = {}
    for accum in accums:
        if accum.minutes < MIN_MINUTES_FOR_PRIOR:
            continue
        bucket = buckets.setdefault(int(accum.element_type), {})
        for key, total in (
            ("xg90", accum.xg),
            ("xa90", accum.xa),
            ("bonus90", accum.bonus),
            ("dc90", accum.dc),
            ("saves90", accum.saves),
            ("yc90", accum.yellow_cards),
        ):
            bucket.setdefault(key, []).append(accum.per_90(total))

    priors: PositionPriors = {}
    for element_type, stats in buckets.items():
        priors[element_type] = {key: float(median(values)) for key, values in stats.items() if values}
    return priors


_FALLBACK_PRIORS: PositionPriors = {
    1: {"xg90": 0.0, "xa90": 0.01, "bonus90": 0.35, "dc90": 0.4, "saves90": 2.6, "yc90": 0.06},
    2: {"xg90": 0.05, "xa90": 0.06, "bonus90": 0.35, "dc90": 6.5, "saves90": 0.0, "yc90": 0.16},
    3: {"xg90": 0.15, "xa90": 0.13, "bonus90": 0.40, "dc90": 6.0, "saves90": 0.0, "yc90": 0.14},
    4: {"xg90": 0.35, "xa90": 0.12, "bonus90": 0.45, "dc90": 3.0, "saves90": 0.0, "yc90": 0.12},
}


def _prior_value(priors: PositionPriors, element_type: int, key: str) -> float:
    table = priors.get(int(element_type)) or _FALLBACK_PRIORS.get(int(element_type), {})
    if key in table:
        return float(table[key])
    return float(_FALLBACK_PRIORS.get(int(element_type), {}).get(key, 0.0))


def _shrink(observed_total: float, minutes: float, prior_rate: float, prior_minutes: float) -> float:
    """Per-90 rate with a prior worth `prior_minutes` of average play."""
    if minutes + prior_minutes <= 0:
        return prior_rate
    return (observed_total + prior_rate * prior_minutes / 90.0) * 90.0 / (minutes + prior_minutes)


def build_rates(accum: PlayerAccum, priors: PositionPriors) -> PlayerRates:
    element_type = int(accum.element_type)
    minutes = max(0.0, accum.minutes)
    appearances = max(1.0, accum.appearances)
    return PlayerRates(
        element_type=element_type,
        xg90=_shrink(accum.xg, minutes, _prior_value(priors, element_type, "xg90"), PRIOR_MINUTES["attack"]),
        xa90=_shrink(accum.xa, minutes, _prior_value(priors, element_type, "xa90"), PRIOR_MINUTES["attack"]),
        bonus90=_shrink(accum.bonus, minutes, _prior_value(priors, element_type, "bonus90"), PRIOR_MINUTES["bonus"]),
        dc90=_shrink(accum.dc, minutes, _prior_value(priors, element_type, "dc90"), PRIOR_MINUTES["defence"]),
        saves90=_shrink(accum.saves, minutes, _prior_value(priors, element_type, "saves90"), PRIOR_MINUTES["defence"]),
        yc90=_shrink(accum.yellow_cards, minutes, _prior_value(priors, element_type, "yc90"), PRIOR_MINUTES["defence"]),
        minutes=minutes,
        start_share=min(1.0, accum.starts / appearances) if accum.appearances else 0.0,
        long_share=min(1.0, accum.long_starts / appearances) if accum.appearances else 0.0,
    )


def _float(raw: Any, default: float = 0.0) -> float:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def accum_from_element(player: dict[str, Any], *, team_games: int) -> PlayerAccum:
    """Season-to-date accumulator from a `bootstrap-static` element."""
    minutes = _float(player.get("minutes"))
    starts = _float(player.get("starts"))
    # bootstrap has no appearance count; starts plus a cameo allowance is the best proxy.
    appearances = max(starts, min(float(team_games), minutes / 45.0 if minutes else 0.0))
    return PlayerAccum(
        element_type=int(player.get("element_type") or 3),
        minutes=minutes,
        appearances=appearances,
        starts=starts,
        xg=_float(player.get("expected_goals")),
        xa=_float(player.get("expected_assists")),
        bonus=_float(player.get("bonus")),
        dc=_float(player.get("defensive_contribution")),
        saves=_float(player.get("saves")),
        yellow_cards=_float(player.get("yellow_cards")),
        long_starts=starts,  # bootstrap cannot tell a 60' start from a 90'; starts is the signal
        xgc=_float(player.get("expected_goals_conceded")),
    )


def cap_match_outliers(accum: PlayerAccum, history: dict[str, Any] | None, cap: float = MATCH_CAP) -> PlayerAccum:
    """Remove each match's xG and xA above `cap` from season totals built from `bootstrap-static`."""
    rows = (history or {}).get("history") or []
    accum.xg = max(0.0, accum.xg - sum(max(0.0, _float(row.get("xg")) - cap) for row in rows))
    accum.xa = max(0.0, accum.xa - sum(max(0.0, _float(row.get("xa")) - cap) for row in rows))
    return accum
