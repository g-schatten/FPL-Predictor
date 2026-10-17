from __future__ import annotations

from dataclasses import dataclass, field

from fpl_predictor.models.rates import PlayerRates
from fpl_predictor.models.scoring import (
    ASSIST_POINTS,
    CONCEDED_PER_PENALTY,
    DC_POINTS,
    SAVES_PER_POINT,
    YELLOW_CARD_POINTS,
    Poisson,
    clean_sheet_points,
    concedes_goal_penalty,
    dc_threshold,
    goal_points,
)
from fpl_predictor.models.team_strength import LeagueContext

# Bonus goes to whoever plays well, which correlates with the team playing well.
BONUS_FIXTURE_SENSITIVITY = 0.35


@dataclass
class MinutesProfile:
    """What we expect from a player's minutes, before any points are scored."""

    expected: float  # expected minutes
    p_appear: float  # P(any minutes)
    p_long: float  # P(60+ minutes), which gates the second appearance point and clean sheets

    @property
    def share(self) -> float:
        return max(0.0, min(1.0, self.expected / 90.0))


@dataclass
class PointsBreakdown:
    """Expected points split by source, so a projection can be explained, not just trusted."""

    appearance: float = 0.0
    goals: float = 0.0
    assists: float = 0.0
    clean_sheet: float = 0.0
    saves: float = 0.0
    defensive_contribution: float = 0.0
    bonus: float = 0.0
    conceded: float = 0.0
    cards: float = 0.0
    context: dict[str, float] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return max(
            0.0,
            self.appearance
            + self.goals
            + self.assists
            + self.clean_sheet
            + self.saves
            + self.defensive_contribution
            + self.bonus
            + self.conceded
            + self.cards,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "appearance": round(self.appearance, 3),
            "goals": round(self.goals, 3),
            "assists": round(self.assists, 3),
            "clean_sheet": round(self.clean_sheet, 3),
            "saves": round(self.saves, 3),
            "defensive_contribution": round(self.defensive_contribution, 3),
            "bonus": round(self.bonus, 3),
            "conceded": round(self.conceded, 3),
            "cards": round(self.cards, 3),
            "total": round(self.total, 3),
            **{k: round(v, 3) for k, v in self.context.items()},
        }


def project_fixture(
    rates: PlayerRates,
    minutes: MinutesProfile,
    league: LeagueContext,
    *,
    team_id: int,
    opponent_id: int,
    home: bool,
) -> PointsBreakdown:
    """Expected points for one player in one fixture.

    Attacking output scales with how much the team is expected to create in this specific
    fixture; clean sheets, saves and goals conceded come from the expected goals against.
    """
    element_type = int(rates.element_type)
    share = minutes.share
    if minutes.p_appear <= 0 or share <= 0:
        return PointsBreakdown(context={"xmins": round(minutes.expected, 1)})

    goals_for, goals_against = league.expected_goals(team_id, opponent_id, home=home)
    attack_scale = league.attack_scale(team_id, opponent_id, home=home)

    xg = rates.xg90 * share * attack_scale
    xa = rates.xa90 * share * attack_scale

    breakdown = PointsBreakdown()
    breakdown.appearance = minutes.p_appear + minutes.p_long
    breakdown.goals = xg * goal_points(element_type)
    breakdown.assists = xa * ASSIST_POINTS

    cs_points = clean_sheet_points(element_type)
    if cs_points:
        breakdown.clean_sheet = Poisson(goals_against).p_zero() * minutes.p_long * cs_points

    if concedes_goal_penalty(element_type):
        conceded_while_on = goals_against * share
        breakdown.conceded = -Poisson(conceded_while_on).expected_floor_div(CONCEDED_PER_PENALTY)

    if rates.saves90 > 0:
        # More shots against means more saves: scale the rate by this fixture's danger.
        team_baseline = league.goals_per_team * league.strength(team_id).defence
        danger = goals_against / team_baseline if team_baseline > 0 else 1.0
        expected_saves = rates.saves90 * share * max(0.5, min(1.8, danger))
        breakdown.saves = Poisson(expected_saves).expected_floor_div(SAVES_PER_POINT)

    threshold = dc_threshold(element_type)
    if threshold and rates.dc90 > 0:
        # +2 at 10 or 12 actions is a step. Score it on the minutes he plays when he plays, then
        # weight by P(appear): a threshold applied to average minutes understates the tail.
        expected_actions = rates.dc90 * min(1.0, share / minutes.p_appear)
        breakdown.defensive_contribution = (
            minutes.p_appear * Poisson(expected_actions).p_at_least(threshold) * DC_POINTS
        )

    fixture_bonus = 1.0 + BONUS_FIXTURE_SENSITIVITY * (attack_scale - 1.0)
    breakdown.bonus = rates.bonus90 * share * max(0.5, fixture_bonus)
    breakdown.cards = rates.yc90 * share * YELLOW_CARD_POINTS

    breakdown.context = {
        "xmins": round(minutes.expected, 1),
        "team_goals_for": round(goals_for, 2),
        "team_goals_against": round(goals_against, 2),
        "attack_scale": round(attack_scale, 3),
        "clean_sheet_odds": round(Poisson(goals_against).p_zero(), 3),
    }
    return breakdown
