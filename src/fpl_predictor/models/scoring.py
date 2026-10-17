from __future__ import annotations

import math
from dataclasses import dataclass, field

# FPL publishes squad and transfer rules in `bootstrap-static.game_settings`, but not the
# points table. These are the 2025/26+ values, including defensive contribution.
GOAL_POINTS = {1: 6, 2: 6, 3: 5, 4: 4}
CLEAN_SHEET_POINTS = {1: 4, 2: 4, 3: 1, 4: 0}
ASSIST_POINTS = 3
SAVES_PER_POINT = 3
CONCEDED_PER_PENALTY = 2  # -1 per 2 goals conceded, GKP and DEF only
YELLOW_CARD_POINTS = -1

# Defensive contribution: +2 once per match at the position threshold.
# DEF count clearances + blocks + interceptions + tackles; MID/FWD add recoveries.
DC_POINTS = 2
DC_THRESHOLD = {1: None, 2: 10, 3: 12, 4: 12}


@dataclass(frozen=True)
class Poisson:
    """Small Poisson helpers. FPL points are counts, so exact tails beat point estimates."""

    lam: float
    max_n: int = field(default=16)

    def pmf(self, n: int) -> float:
        if self.lam <= 0:
            return 1.0 if n == 0 else 0.0
        return math.exp(-self.lam + n * math.log(self.lam) - math.lgamma(n + 1))

    def p_zero(self) -> float:
        return math.exp(-self.lam) if self.lam > 0 else 1.0

    def p_at_least(self, threshold: int) -> float:
        if threshold <= 0:
            return 1.0
        if self.lam <= 0:
            return 0.0
        below = sum(self.pmf(n) for n in range(threshold))
        return max(0.0, min(1.0, 1.0 - below))

    def expected_floor_div(self, divisor: int) -> float:
        """E[floor(X / divisor)] — how FPL pays saves and charges goals conceded."""
        if self.lam <= 0 or divisor <= 0:
            return 0.0
        return sum(self.pmf(n) * (n // divisor) for n in range(self.max_n + 1))


def goal_points(element_type: int) -> int:
    return GOAL_POINTS.get(int(element_type), 4)


def clean_sheet_points(element_type: int) -> int:
    return CLEAN_SHEET_POINTS.get(int(element_type), 0)


def dc_threshold(element_type: int) -> int | None:
    return DC_THRESHOLD.get(int(element_type))


def concedes_goal_penalty(element_type: int) -> bool:
    return int(element_type) in {1, 2}
