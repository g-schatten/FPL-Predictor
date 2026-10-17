from __future__ import annotations

import math

from fpl_predictor.models.engine import MinutesProfile, project_fixture
from fpl_predictor.models.rates import PlayerAccum, build_rates
from fpl_predictor.models.scoring import Poisson, dc_threshold
from fpl_predictor.models.team_strength import (
    LeagueContext,
    TeamGame,
    TeamStrength,
    build_league_context,
    fdr_priors,
)


def _rates(element_type: int, **overrides):
    accum = PlayerAccum(
        element_type=element_type,
        minutes=overrides.pop("minutes", 1800.0),
        appearances=20.0,
        starts=20.0,
        xg=overrides.pop("xg", 8.0),
        xa=overrides.pop("xa", 4.0),
        bonus=overrides.pop("bonus", 10.0),
        dc=overrides.pop("dc", 140.0),
        saves=overrides.pop("saves", 0.0),
        yellow_cards=overrides.pop("yellow_cards", 2.0),
        long_starts=20.0,
    )
    return build_rates(accum, {})


FULL_TIME = MinutesProfile(expected=90.0, p_appear=1.0, p_long=1.0)


def _league(attack_strong: float = 1.4, defence_weak: float = 1.4) -> LeagueContext:
    return LeagueContext(
        teams={
            1: TeamStrength(1, attack=attack_strong, defence=0.7, games=10),
            2: TeamStrength(2, attack=0.8, defence=defence_weak, games=10),
            3: TeamStrength(3, attack=1.0, defence=1.0, games=10),
        },
        goals_per_team=1.42,
    )


def test_poisson_tails_match_closed_form() -> None:
    poisson = Poisson(2.0)
    assert math.isclose(poisson.p_zero(), math.exp(-2.0), rel_tol=1e-9)
    assert math.isclose(poisson.p_at_least(1), 1 - math.exp(-2.0), rel_tol=1e-9)
    # E[floor(X/3)] is strictly below E[X]/3 because part-filled triples score nothing.
    assert 0 < poisson.expected_floor_div(3) < 2.0 / 3.0


def test_easier_opponent_raises_attacking_points() -> None:
    league = _league()
    striker = _rates(4)
    weak = project_fixture(striker, FULL_TIME, league, team_id=1, opponent_id=2, home=True)
    strong = project_fixture(striker, FULL_TIME, league, team_id=1, opponent_id=1, home=True)
    assert weak.goals > strong.goals
    assert weak.total > strong.total


def test_home_fixture_beats_the_same_fixture_away() -> None:
    league = _league()
    mid = _rates(3)
    home = project_fixture(mid, FULL_TIME, league, team_id=1, opponent_id=3, home=True)
    away = project_fixture(mid, FULL_TIME, league, team_id=1, opponent_id=3, home=False)
    assert home.total > away.total


def test_defenders_get_clean_sheet_value_and_concede_penalty() -> None:
    league = _league()
    defender = _rates(2, xg=1.0, xa=1.0)
    tough_opponent = project_fixture(defender, FULL_TIME, league, team_id=2, opponent_id=1, home=False)
    easy_opponent = project_fixture(defender, FULL_TIME, league, team_id=1, opponent_id=2, home=True)
    assert easy_opponent.clean_sheet > tough_opponent.clean_sheet
    assert tough_opponent.conceded < 0
    assert easy_opponent.conceded > tough_opponent.conceded


def test_midfield_clean_sheet_is_worth_less_than_a_defenders() -> None:
    league = _league()
    same = dict(team_id=1, opponent_id=2, home=True)
    defender = project_fixture(_rates(2), FULL_TIME, league, **same)
    midfielder = project_fixture(_rates(3), FULL_TIME, league, **same)
    assert defender.clean_sheet > midfielder.clean_sheet > 0


def test_defensive_contribution_needs_the_position_threshold() -> None:
    league = _league()
    # 12 actions per 90 clears the defender threshold of 10 but not a midfielder's 12.
    busy = PlayerAccum(
        element_type=2, minutes=900.0, appearances=10.0, starts=10.0, xg=0.0, xa=0.0,
        bonus=0.0, dc=120.0, saves=0.0, yellow_cards=0.0, long_starts=10.0,
    )
    defender = build_rates(busy, {})
    midfielder = build_rates(PlayerAccum(**{**busy.__dict__, "element_type": 3}), {})
    same = dict(team_id=1, opponent_id=2, home=True)
    dc_def = project_fixture(defender, FULL_TIME, league, **same).defensive_contribution
    dc_mid = project_fixture(midfielder, FULL_TIME, league, **same).defensive_contribution
    assert dc_threshold(2) == 10 and dc_threshold(3) == 12
    assert dc_def > dc_mid
    assert 0.0 <= dc_def <= 2.0


def test_defensive_contribution_scales_with_the_chance_of_playing() -> None:
    same = dict(team_id=1, opponent_id=2, home=True)
    coin_flip = MinutesProfile(expected=45.0, p_appear=0.5, p_long=0.5)  # 90 minutes or none
    full = project_fixture(_rates(2), FULL_TIME, _league(), **same).defensive_contribution
    half = project_fixture(_rates(2), coin_flip, _league(), **same).defensive_contribution
    assert full > 0 and math.isclose(half, 0.5 * full)  # today's code gives far less than half


def test_no_minutes_means_no_points() -> None:
    bench = MinutesProfile(expected=0.0, p_appear=0.0, p_long=0.0)
    result = project_fixture(_rates(4), bench, _league(), team_id=1, opponent_id=2, home=True)
    assert result.total == 0.0


def test_rates_shrink_small_samples_toward_the_position_prior() -> None:
    priors = {4: {"xg90": 0.35, "xa90": 0.12, "bonus90": 0.45, "dc90": 3.0, "saves90": 0.0, "yc90": 0.12}}
    one_game_hero = PlayerAccum(
        element_type=4, minutes=90.0, appearances=1.0, starts=1.0, xg=1.5, xa=0.0,
        bonus=3.0, dc=2.0, saves=0.0, yellow_cards=0.0, long_starts=1.0,
    )
    season_long = PlayerAccum(
        element_type=4, minutes=2700.0, appearances=30.0, starts=30.0, xg=45.0, xa=0.0,
        bonus=90.0, dc=60.0, saves=0.0, yellow_cards=0.0, long_starts=30.0,
    )
    hero = build_rates(one_game_hero, priors)
    proven = build_rates(season_long, priors)
    assert hero.xg90 < 0.65  # 1.5 xG in one match must not become a 1.5 xG90 rate
    assert proven.xg90 > 1.2  # 30 matches of the same rate should survive shrinkage


def test_team_strength_shrinks_toward_prior_and_respects_xg() -> None:
    # Team 1 wins 3-0 twice; teams 2 and 3 record the other side of those matches.
    games = [
        TeamGame(1, 2, True, 3.0, 0.0),
        TeamGame(2, 1, False, 0.0, 3.0),
        TeamGame(1, 3, False, 3.0, 0.0),
        TeamGame(3, 1, True, 0.0, 3.0),
    ]
    context = build_league_context(games, prior_games=5.0)
    strong, weak = context.strength(1), context.strength(2)
    assert strong.attack > 1.0 > weak.attack
    assert strong.defence < 1.0 < weak.defence
    # Two thrashings are not proof of a 2x league-average attack.
    assert strong.attack < 1.6
    assert strong.games == 2


def test_xg_overrides_a_lucky_scoreline() -> None:
    games = [
        TeamGame(1, 2, True, 3.0, 0.0),
        TeamGame(2, 1, False, 0.0, 3.0),
        TeamGame(1, 3, False, 3.0, 0.0),
        TeamGame(3, 1, True, 0.0, 3.0),
    ]
    # Team 1 scored six goals from very little xG; strength should mostly ignore the goals.
    flattered = build_league_context(games, xg_per_game={1: (0.6, 1.8), 2: (1.5, 0.9), 3: (1.5, 0.9)})
    honest = build_league_context(games)
    assert flattered.strength(1).attack < honest.strength(1).attack
    assert flattered.strength(1).defence > honest.strength(1).defence


def test_fdr_priors_rate_strong_teams_higher() -> None:
    fixtures = [
        {"team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 5},
        {"team_h": 2, "team_a": 1, "team_h_difficulty": 5, "team_a_difficulty": 2},
        {"team_h": 1, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 5},
        {"team_h": 3, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3},
    ]
    priors = fdr_priors(fixtures, [1, 2, 3])
    # Team 1 is rated a hard fixture (opponents get difficulty 5), team 2 an easy one.
    assert priors[1].attack > priors[2].attack
    assert priors[1].defence < priors[2].defence
