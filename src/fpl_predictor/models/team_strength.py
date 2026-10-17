from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

# Long-run Premier League baselines, used as shrinkage targets while a season is young.
LEAGUE_GOALS_PER_TEAM = 1.42
HOME_ATTACK_MULT = 1.09
AWAY_ATTACK_MULT = 0.92

# Both values come from the walk-forward sweep in docs/EVAL.md, not from taste.
# xG-weighted strength beat goals-only strength by 0.010 NDCG@20 (0.389 vs 0.379); the
# shrinkage weight was flat across 0-8 team-games, so this keeps early-season estimates safe.
PRIOR_GAMES = 3.0
XG_WEIGHT = 0.8


@dataclass
class TeamGame:
    """One observed team-match, from the perspective of `team_id`."""

    team_id: int
    opponent_id: int
    home: bool
    goals_for: float
    goals_against: float


@dataclass
class TeamStrength:
    team_id: int
    attack: float  # 1.0 = league-average goals scored
    defence: float  # 1.0 = league-average goals conceded; lower is better
    games: int

    @property
    def summary(self) -> str:
        return f"attack {self.attack:.2f} · defence {self.defence:.2f} ({self.games} games)"


@dataclass
class LeagueContext:
    """Team strengths plus the league-wide scoring rate they are indexed against."""

    teams: dict[int, TeamStrength] = field(default_factory=dict)
    goals_per_team: float = LEAGUE_GOALS_PER_TEAM
    home_mult: float = HOME_ATTACK_MULT
    away_mult: float = AWAY_ATTACK_MULT

    def strength(self, team_id: int) -> TeamStrength:
        return self.teams.get(int(team_id), TeamStrength(int(team_id), 1.0, 1.0, 0))

    def expected_goals(self, team_id: int, opponent_id: int, *, home: bool) -> tuple[float, float]:
        """(goals for, goals against) for one fixture, from `team_id`'s perspective."""
        mine = self.strength(team_id)
        theirs = self.strength(opponent_id)
        venue_for = self.home_mult if home else self.away_mult
        venue_against = self.away_mult if home else self.home_mult
        scored = self.goals_per_team * mine.attack * theirs.defence * venue_for
        conceded = self.goals_per_team * theirs.attack * mine.defence * venue_against
        return max(0.15, scored), max(0.15, conceded)

    def attack_scale(self, team_id: int, opponent_id: int, *, home: bool) -> float:
        """How much better or worse than this team's typical game the fixture looks.

        1.0 means an average opponent at a neutral venue, so player per-90 rates
        (which are already averaged over their own fixtures) need no adjustment.
        """
        scored, _ = self.expected_goals(team_id, opponent_id, home=home)
        baseline = self.goals_per_team * self.strength(team_id).attack
        if baseline <= 0:
            return 1.0
        return max(0.55, min(1.75, scored / baseline))


def _index(value: float, league_mean: float) -> float:
    if league_mean <= 0:
        return 1.0
    return value / league_mean


def build_league_context(
    games: Iterable[TeamGame],
    *,
    xg_per_game: dict[int, tuple[float, float]] | None = None,
    priors: dict[int, TeamStrength] | None = None,
    prior_games: float = PRIOR_GAMES,
    xg_weight: float = XG_WEIGHT,
) -> LeagueContext:
    """Attack / defence indices from observed team-matches, shrunk toward a prior.

    `xg_per_game` maps team id -> (xG for, xG against) per game and is blended with the
    goals-based index. With four gameweeks played, raw per-team rates are mostly noise, so
    every index is pulled toward the prior (FDR or league average) by `prior_games`.
    """
    per_team: dict[int, list[TeamGame]] = defaultdict(list)
    for game in games:
        per_team[int(game.team_id)].append(game)

    if not per_team:
        return LeagueContext(teams=dict(priors or {}))

    all_games = [g for rows in per_team.values() for g in rows]
    league_goals = sum(g.goals_for for g in all_games) / len(all_games)

    home_rows = [g for g in all_games if g.home]
    away_rows = [g for g in all_games if not g.home]
    home_mult, away_mult = HOME_ATTACK_MULT, AWAY_ATTACK_MULT
    if home_rows and away_rows and league_goals > 0:
        observed_home = (sum(g.goals_for for g in home_rows) / len(home_rows)) / league_goals
        observed_away = (sum(g.goals_for for g in away_rows) / len(away_rows)) / league_goals
        # Venue effects are stable across seasons; trust the long-run number most.
        home_mult = 0.7 * HOME_ATTACK_MULT + 0.3 * observed_home
        away_mult = 0.7 * AWAY_ATTACK_MULT + 0.3 * observed_away

    xg_table = xg_per_game or {}
    xg_values = [v for v in xg_table.values() if v]
    league_xg = sum(v[0] for v in xg_values) / len(xg_values) if xg_values else league_goals

    teams: dict[int, TeamStrength] = {}
    for team_id, rows in per_team.items():
        n = float(len(rows))
        attack_obs = _index(sum(g.goals_for for g in rows) / n, league_goals)
        defence_obs = _index(sum(g.goals_against for g in rows) / n, league_goals)

        team_xg = xg_table.get(int(team_id))
        if team_xg and league_xg > 0:
            attack_obs = xg_weight * _index(team_xg[0], league_xg) + (1 - xg_weight) * attack_obs
            defence_obs = xg_weight * _index(team_xg[1], league_xg) + (1 - xg_weight) * defence_obs

        prior = (priors or {}).get(int(team_id))
        prior_attack = prior.attack if prior else 1.0
        prior_defence = prior.defence if prior else 1.0
        weight = n / (n + prior_games)
        teams[int(team_id)] = TeamStrength(
            team_id=int(team_id),
            attack=weight * attack_obs + (1 - weight) * prior_attack,
            defence=weight * defence_obs + (1 - weight) * prior_defence,
            games=int(n),
        )

    for team_id, prior in (priors or {}).items():
        teams.setdefault(int(team_id), prior)

    played = len(all_games)
    goals_per_team = (played * league_goals + 40.0 * LEAGUE_GOALS_PER_TEAM) / (played + 40.0)
    return LeagueContext(teams=teams, goals_per_team=goals_per_team, home_mult=home_mult, away_mult=away_mult)


def fdr_priors(fixtures: list[dict[str, Any]], team_ids: Iterable[int]) -> dict[int, TeamStrength]:
    """Preseason-ish prior from FPL's own fixture difficulty ratings.

    `team_h_difficulty` is how hard the home team's fixture is, i.e. a rating of the away
    team. Averaging the difficulty each opponent is given when facing a team is a usable
    strength proxy before enough matches exist. `teams[].strength` is null in this
    season's payload, so FDR is the only official prior available.
    """
    faced: dict[int, list[int]] = defaultdict(list)
    for fixture in fixtures:
        home_id, away_id = fixture.get("team_h"), fixture.get("team_a")
        home_diff, away_diff = fixture.get("team_h_difficulty"), fixture.get("team_a_difficulty")
        if not home_id or not away_id or not home_diff or not away_diff:
            continue
        # Difficulty given to the home team describes the away team's strength.
        faced[int(away_id)].append(int(home_diff))
        faced[int(home_id)].append(int(away_diff))

    if not faced:
        return {}
    means = {tid: sum(vals) / len(vals) for tid, vals in faced.items() if vals}
    league_mean = sum(means.values()) / len(means)
    priors: dict[int, TeamStrength] = {}
    for team_id in team_ids:
        rating = means.get(int(team_id))
        if rating is None:
            priors[int(team_id)] = TeamStrength(int(team_id), 1.0, 1.0, 0)
            continue
        # A 3.5-rated side (hard to play) attacks better and concedes less than a 2.5 side.
        edge = (rating - league_mean) / max(league_mean, 1e-6)
        priors[int(team_id)] = TeamStrength(
            team_id=int(team_id),
            attack=max(0.6, min(1.5, 1.0 + 0.9 * edge)),
            defence=max(0.6, min(1.5, 1.0 - 0.9 * edge)),
            games=0,
        )
    return priors


def team_games_from_fixtures(fixtures: list[dict[str, Any]]) -> list[TeamGame]:
    """Observed team-matches from finished official fixtures."""
    games: list[TeamGame] = []
    for fixture in fixtures:
        if not fixture.get("finished"):
            continue
        home_id, away_id = fixture.get("team_h"), fixture.get("team_a")
        home_score, away_score = fixture.get("team_h_score"), fixture.get("team_a_score")
        if home_id is None or away_id is None or home_score is None or away_score is None:
            continue
        games.append(
            TeamGame(int(home_id), int(away_id), True, float(home_score), float(away_score))
        )
        games.append(
            TeamGame(int(away_id), int(home_id), False, float(away_score), float(home_score))
        )
    return games


def team_xg_from_players(players: list[dict[str, Any]], games_played: dict[int, int]) -> dict[int, tuple[float, float]]:
    """Team xG for / against per game from official per-player season aggregates.

    xG for sums every player's `expected_goals`. xG against uses the goalkeepers'
    `expected_goals_conceded` per 90, which is the team's own rate while they were on the
    pitch — outfield players would double count it.
    """
    xg_for: dict[int, float] = defaultdict(float)
    gk_xgc: dict[int, float] = defaultdict(float)
    gk_minutes: dict[int, float] = defaultdict(float)
    for player in players:
        team_id = int(player.get("team") or 0)
        if not team_id:
            continue
        try:
            xg_for[team_id] += float(player.get("expected_goals") or 0.0)
        except (TypeError, ValueError):
            pass
        if int(player.get("element_type") or 0) == 1:
            try:
                gk_xgc[team_id] += float(player.get("expected_goals_conceded") or 0.0)
                gk_minutes[team_id] += float(player.get("minutes") or 0.0)
            except (TypeError, ValueError):
                pass

    table: dict[int, tuple[float, float]] = {}
    for team_id, played in games_played.items():
        if played <= 0:
            continue
        per_game_for = xg_for.get(team_id, 0.0) / played
        minutes = gk_minutes.get(team_id, 0.0)
        per_game_against = (gk_xgc.get(team_id, 0.0) / (minutes / 90.0)) if minutes > 0 else None
        if per_game_against is None:
            continue
        table[team_id] = (per_game_for, per_game_against)
    return table
