from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

from fpl_predictor.data.rules import GameRules
from fpl_predictor.features.builder import PlayerProjection
from fpl_predictor.models.engine import MinutesProfile, project_fixture
from fpl_predictor.models.minutes import DECAY_HALF_LIFE
from fpl_predictor.models.points import project_gameweek_points
from fpl_predictor.models.rates import (
    PlayerAccum,
    MATCH_CAP,
    PositionPriors,
    build_position_priors,
    build_rates,
)
from fpl_predictor.models.team_strength import (
    PRIOR_GAMES,
    XG_WEIGHT,
    LeagueContext,
    TeamGame,
    build_league_context,
)
from fpl_predictor.optimize.wildcard import WildcardPlan, solve_wildcard

POSITION_TO_TYPE = {"GK": 1, "GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
MIN_HISTORY_GWS = 3  # a player needs some past before any method can rank them

_TEAM_KEYS: dict[str, int] = {}


def _team_key(name: str) -> int:
    key = str(name)
    if key not in _TEAM_KEYS:
        _TEAM_KEYS[key] = len(_TEAM_KEYS) + 1
    return _TEAM_KEYS[key]


@dataclass
class EngineConfig:
    """Every free parameter the projection engine has, so they can be tuned, not guessed.

    Defaults mirror the constants the live engine uses, so a backtest run always scores
    what actually ships.
    """

    prior_games: float = PRIOR_GAMES
    xg_weight: float = XG_WEIGHT
    rate_half_life: float | None = None  # None = weight every completed match equally
    match_cap: float | None = MATCH_CAP  # per-match xG/xA cap; None = no cap
    minutes_half_life: float = DECAY_HALF_LIFE
    points_blend: float = 0.0  # weight on the player's own recent points per 90
    name: str | None = None

    def label(self) -> str:
        if self.name:
            return self.name
        return (
            f"engine(prior={self.prior_games:g},xg={self.xg_weight:g},"
            f"rate_hl={self.rate_half_life or 0:g},min_hl={self.minutes_half_life:g},"
            f"pblend={self.points_blend:g})"
        )


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalise a vaastav `merged_gw` season into the columns the engine needs."""
    # 2024-25 and earlier have no defensive_contribution column; a missing column becomes 0.
    frame = frame.reindex(columns=frame.columns.union(["defensive_contribution"], sort=False))
    out = pd.DataFrame(
        {
            "element": pd.to_numeric(frame["element"], errors="coerce").astype("Int64"),
            "gw": pd.to_numeric(frame["GW"] if "GW" in frame else frame["round"], errors="coerce").astype("Int64"),
            "fixture": pd.to_numeric(frame.get("fixture"), errors="coerce").astype("Int64"),
            "team": frame["team"].astype(str),
            "element_type": frame["position"].map(POSITION_TO_TYPE).fillna(3).astype(int),
            "home": pd.to_numeric(frame["was_home"], errors="coerce").fillna(0).astype(bool),
            "minutes": pd.to_numeric(frame["minutes"], errors="coerce").fillna(0.0),
            "starts": pd.to_numeric(frame.get("starts"), errors="coerce").fillna(0.0),
            "points": pd.to_numeric(frame["total_points"], errors="coerce").fillna(0.0),
            "xg": pd.to_numeric(frame["expected_goals"], errors="coerce").fillna(0.0),
            "xa": pd.to_numeric(frame["expected_assists"], errors="coerce").fillna(0.0),
            "xgc": pd.to_numeric(frame["expected_goals_conceded"], errors="coerce").fillna(0.0),
            "bonus": pd.to_numeric(frame["bonus"], errors="coerce").fillna(0.0),
            "dc": pd.to_numeric(frame.get("defensive_contribution"), errors="coerce").fillna(0.0),
            "saves": pd.to_numeric(frame["saves"], errors="coerce").fillna(0.0),
            "yellow_cards": pd.to_numeric(frame["yellow_cards"], errors="coerce").fillna(0.0),
            "value": pd.to_numeric(frame["value"], errors="coerce").fillna(45.0),
            "official_xp": pd.to_numeric(frame.get("xP"), errors="coerce").fillna(0.0),
            "home_score": pd.to_numeric(frame["team_h_score"], errors="coerce"),
            "away_score": pd.to_numeric(frame["team_a_score"], errors="coerce"),
        }
    ).dropna(subset=["element", "gw"])
    out["element"] = out["element"].astype(int)
    out["gw"] = out["gw"].astype(int)
    out["goals_for"] = np.where(out["home"], out["home_score"], out["away_score"])
    out["goals_against"] = np.where(out["home"], out["away_score"], out["home_score"])

    # Opponent comes from the other side of the same fixture, so no team-id mapping is needed.
    opponent: dict[tuple[int, str], str] = {}
    for fixture_id, sides in out.dropna(subset=["fixture"]).groupby("fixture")["team"].unique().items():
        if len(sides) == 2:
            opponent[(int(fixture_id), sides[0])] = sides[1]
            opponent[(int(fixture_id), sides[1])] = sides[0]
    out["opponent"] = [
        opponent.get((int(f), t), "") if pd.notna(f) else "" for f, t in zip(out["fixture"], out["team"])
    ]
    return out[out["opponent"] != ""].reset_index(drop=True)


def _decay_weights(count: int, half_life: float | None = DECAY_HALF_LIFE) -> np.ndarray:
    """Newest match weighted 1.0, halving every `half_life` matches back. None = flat."""
    if not half_life:
        return np.ones(count)
    offsets = np.arange(count - 1, -1, -1, dtype=float)
    return 0.5 ** (offsets / half_life)


def accums_from_history(
    history: pd.DataFrame, *, half_life: float | None = None, match_cap: float | None = None
) -> dict[int, PlayerAccum]:
    """Per-player accumulators over completed matches, optionally recency weighted.

    Weights are renormalised to keep the sample size at "matches played", so recency
    changes the mix of evidence without pretending we have more or less of it.
    """
    accums: dict[int, PlayerAccum] = {}
    for element, rows in history.groupby("element", sort=False):
        rows = rows.sort_values("gw")
        weights = _decay_weights(len(rows), half_life)
        weights = weights * (len(rows) / (weights.sum() or 1.0))
        minutes = rows["minutes"].to_numpy()

        def wtotal(column: str) -> float:
            return float(np.sum(weights * rows[column].to_numpy()))

        accums[int(element)] = PlayerAccum(
            element_type=int(rows["element_type"].iloc[-1]),
            minutes=wtotal("minutes"),
            appearances=float(np.sum(weights * (minutes > 0))),
            starts=wtotal("starts"),
            xg=float(np.sum(weights * rows["xg"].clip(upper=match_cap).to_numpy())),
            xa=float(np.sum(weights * rows["xa"].clip(upper=match_cap).to_numpy())),
            bonus=wtotal("bonus"),
            dc=wtotal("dc"),
            saves=wtotal("saves"),
            yellow_cards=wtotal("yellow_cards"),
            long_starts=float(np.sum(weights * (minutes >= 60))),
            xgc=wtotal("xgc"),
        )
    return accums


def minutes_from_history(
    history: pd.DataFrame, *, half_life: float = DECAY_HALF_LIFE
) -> dict[int, MinutesProfile]:
    profiles: dict[int, MinutesProfile] = {}
    for element, rows in history.groupby("element", sort=False):
        rows = rows.sort_values("gw")
        weights = _decay_weights(len(rows), half_life)
        total = float(weights.sum()) or 1.0
        minutes = rows["minutes"].to_numpy()
        profiles[int(element)] = MinutesProfile(
            expected=float(np.sum(weights * minutes) / total),
            p_appear=float(np.sum(weights * (minutes > 0)) / total),
            p_long=float(np.sum(weights * (minutes >= 60)) / total),
        )
    return profiles


def league_context_from_history(
    history: pd.DataFrame, *, prior_games: float, xg_weight: float
) -> LeagueContext:
    """Team strength from completed matches only, keyed by team name."""
    team_matches = history.drop_duplicates(subset=["fixture", "team"])
    games = [
        TeamGame(
            team_id=_team_key(row.team),
            opponent_id=_team_key(row.opponent),
            home=bool(row.home),
            goals_for=float(row.goals_for),
            goals_against=float(row.goals_against),
        )
        for row in team_matches.itertuples()
        if not (pd.isna(row.goals_for) or pd.isna(row.goals_against))
    ]

    per_fixture = history.groupby(["fixture", "team"], dropna=True)["xg"].sum().reset_index()
    xg_for: dict[int, list[float]] = defaultdict(list)
    for row in per_fixture.itertuples():
        xg_for[_team_key(row.team)].append(float(row.xg))

    # Team xG conceded uses the goalkeepers' xGC per 90, mirroring the live path.
    keepers = history[history["element_type"] == 1]
    xgc_rows = keepers.groupby(["fixture", "team"]).agg(xgc=("xgc", "sum"), minutes=("minutes", "sum")).reset_index()
    xgc_against: dict[int, list[float]] = defaultdict(list)
    for row in xgc_rows.itertuples():
        if row.minutes and row.minutes > 0:
            xgc_against[_team_key(row.team)].append(float(row.xgc) * 90.0 / float(row.minutes))

    xg_per_game = {
        key: (float(np.mean(values)), float(np.mean(xgc_against[key])))
        for key, values in xg_for.items()
        if xgc_against.get(key)
    }
    return build_league_context(games, xg_per_game=xg_per_game, prior_games=prior_games, xg_weight=xg_weight)


@dataclass
class GameweekState:
    """Everything derivable from gameweeks before `gw`, computed once and shared."""

    gw: int
    history: pd.DataFrame
    target: pd.DataFrame
    _accums: dict[tuple, dict[int, PlayerAccum]] = field(default_factory=dict)
    _priors: dict[tuple, PositionPriors] = field(default_factory=dict)
    _leagues: dict[tuple[float, float], LeagueContext] = field(default_factory=dict)
    _minutes: dict[float, dict[int, MinutesProfile]] = field(default_factory=dict)
    _points90: dict[int, float] | None = None

    def accums(self, half_life: float | None, match_cap: float | None = None) -> dict[int, PlayerAccum]:
        key = (half_life, match_cap)
        if key not in self._accums:
            self._accums[key] = accums_from_history(self.history, half_life=half_life, match_cap=match_cap)
        return self._accums[key]

    def priors(self, half_life: float | None, match_cap: float | None = None) -> PositionPriors:
        key = (half_life, match_cap)
        if key not in self._priors:
            self._priors[key] = build_position_priors(self.accums(half_life, match_cap).values())
        return self._priors[key]

    def league(self, prior_games: float, xg_weight: float) -> LeagueContext:
        key = (prior_games, xg_weight)
        if key not in self._leagues:
            self._leagues[key] = league_context_from_history(
                self.history, prior_games=prior_games, xg_weight=xg_weight
            )
        return self._leagues[key]

    def minutes(self, half_life: float = DECAY_HALF_LIFE) -> dict[int, MinutesProfile]:
        if half_life not in self._minutes:
            self._minutes[half_life] = minutes_from_history(self.history, half_life=half_life)
        return self._minutes[half_life]

    def points_per_90(self) -> dict[int, float]:
        """Recency-weighted points per 90 — the signal the old engine leaned on."""
        if self._points90 is None:
            table: dict[int, float] = {}
            for element, rows in self.history.groupby("element", sort=False):
                rows = rows.sort_values("gw")
                weights = _decay_weights(len(rows))
                minutes = float(np.sum(weights * rows["minutes"].to_numpy()))
                points = float(np.sum(weights * rows["points"].to_numpy()))
                table[int(element)] = (points * 90.0 / minutes) if minutes > 0 else 0.0
            self._points90 = table
        return self._points90


def engine_predictions(state: GameweekState, config: EngineConfig) -> np.ndarray:
    league = state.league(config.prior_games, config.xg_weight)
    accums = state.accums(config.rate_half_life, config.match_cap)
    priors = state.priors(config.rate_half_life, config.match_cap)
    minutes = state.minutes(config.minutes_half_life)
    points90 = state.points_per_90() if config.points_blend > 0 else {}

    predictions = np.zeros(len(state.target))
    for index, row in enumerate(state.target.itertuples()):
        accum = accums.get(int(row.element))
        profile = minutes.get(int(row.element))
        if accum is None or profile is None:
            continue
        rates = build_rates(accum, priors)
        team_id, opponent_id = _team_key(row.team), _team_key(row.opponent)
        result = project_fixture(
            rates, profile, league, team_id=team_id, opponent_id=opponent_id, home=bool(row.home)
        )
        value = result.total
        if config.points_blend > 0:
            scale = league.attack_scale(team_id, opponent_id, home=bool(row.home))
            form_points = points90.get(int(row.element), 0.0) * profile.share * scale
            value = (1 - config.points_blend) * value + config.points_blend * form_points
        predictions[index] = value
    return predictions


def legacy_predictions(state: GameweekState) -> np.ndarray:
    """The shipped heuristic: recent points × an FDR-style fixture multiplier × minutes.

    Historical FDR and `ep_next` are not published, so opponent difficulty is bucketed from
    the same league context the new engine uses. That keeps the comparison about the model.
    """
    league = state.league(5.0, 0.65)
    defences = sorted(s.defence for s in league.teams.values()) or [1.0]
    cuts = np.quantile(defences, [0.2, 0.4, 0.6, 0.8])
    recent = state.history[state.history["gw"] >= state.history["gw"].max() - 2]
    form = recent.groupby("element")["points"].mean().to_dict()
    mins = recent.groupby("element")["minutes"].mean().to_dict()

    predictions = np.zeros(len(state.target))
    for index, row in enumerate(state.target.itertuples()):
        opponent = league.strength(_team_key(row.opponent))
        # Strong defence (low index) means a hard fixture, i.e. a high FDR.
        fdr = int(5 - np.searchsorted(cuts, opponent.defence))
        predictions[index] = project_gameweek_points(
            ep_next=0.0,
            form=float(form.get(int(row.element), 0.0)),
            availability=1.0,
            xmins=float(mins.get(int(row.element), 0.0)),
            fdr=max(1, min(5, fdr)),
            home=bool(row.home),
            use_official_ep=False,
        )
    return predictions


def baseline_predictions(state: GameweekState) -> dict[str, np.ndarray]:
    recent = state.history[state.history["gw"] >= state.history["gw"].max() - 3]
    minutes = recent.groupby("element")["minutes"].sum().to_dict()
    points = recent.groupby("element")["points"].sum().to_dict()
    mean_minutes = recent.groupby("element")["minutes"].mean().to_dict()
    elements = state.target["element"].to_numpy()
    per90 = {
        e: (points.get(e, 0.0) * 90.0 / minutes[e]) if minutes.get(e, 0.0) > 0 else 0.0 for e in minutes
    }
    return {
        "form_per90": np.array(
            [per90.get(int(e), 0.0) * mean_minutes.get(int(e), 0.0) / 90.0 for e in elements]
        ),
        "price": state.target["value"].to_numpy(dtype=float),
    }


def _ndcg(actual: np.ndarray, predicted: np.ndarray, k: int) -> float:
    if len(actual) <= 1:
        return float("nan")
    gains = np.clip(actual, 0, None)
    order = np.argsort(-predicted, kind="stable")
    discounts = 1.0 / np.log2(np.arange(2, min(k, len(actual)) + 2))
    dcg = float(np.sum(gains[order][: len(discounts)] * discounts))
    ideal = float(np.sum(np.sort(gains)[::-1][: len(discounts)] * discounts))
    return dcg / ideal if ideal > 0 else float("nan")


def _top_capture(actual: np.ndarray, predicted: np.ndarray, k: int) -> float:
    """Share of the gameweek's actual top-k points that the predicted top-k captured."""
    if len(actual) <= k:
        return float("nan")
    best = float(np.sort(actual)[::-1][:k].sum())
    picked = float(actual[np.argsort(-predicted, kind="stable")[:k]].sum())
    return picked / best if best > 0 else float("nan")


def _spearman(actual: np.ndarray, predicted: np.ndarray) -> float:
    if len(actual) <= 2:
        return float("nan")
    a = pd.Series(actual).rank().to_numpy()
    b = pd.Series(predicted).rank().to_numpy()
    if np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def score_predictions(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "ndcg@10": _ndcg(actual, predicted, 10),
        "ndcg@20": _ndcg(actual, predicted, 20),
        "top10_capture": _top_capture(actual, predicted, 10),
        "top20_capture": _top_capture(actual, predicted, 20),
        "spearman": _spearman(actual, predicted),
        "mae": float(np.mean(np.abs(actual - predicted))),
    }


def _as_projection(row: Any, predicted: float) -> PlayerProjection:
    return PlayerProjection(
        player_id=int(row.element),
        code=0,
        web_name=str(int(row.element)),
        team_id=_team_key(row.team),
        team_short=str(row.team)[:3].upper(),
        position="",
        element_type=int(row.element_type),
        now_cost=int(row.value),
        status="a",
        news="",
        chance_next=None,
        availability=1.0,
        xmins=0.0,
        ep_next=0.0,
        form=0.0,
        xpts_by_gw={},
        xpts=max(0.0, float(predicted)),
        can_select=True,
    )


def squad_points(state: GameweekState, predicted: np.ndarray, rules: GameRules) -> dict[str, float]:
    """Solve a legal 15 on this gameweek's prices, then count the points it actually scored.

    This is the metric that matches how the tool is used: the projection only matters
    through the squad the solver builds from it.
    """
    frame = state.target.assign(predicted=predicted)
    # A double gameweek is one squad slot with two fixtures.
    grouped = frame.groupby("element").agg(
        predicted=("predicted", "sum"),
        points=("points", "sum"),
        minutes=("minutes", "sum"),
        value=("value", "max"),
        element_type=("element_type", "first"),
        team=("team", "first"),
    )
    pool = [
        _as_projection(row, float(row.predicted))
        for row in grouped.reset_index().rename(columns={"element": "element"}).itertuples()
    ]
    actual = {int(row.Index): float(row.points) for row in grouped.itertuples()}
    minutes = {int(row.Index): float(row.minutes) for row in grouped.itertuples()}
    plan = solve_wildcard(pool, rules, time_limit=6)
    starters = [pick for pick in plan.picks if pick.starter]
    captain = max(starters, key=lambda pick: pick.player.xpts)
    xi = sum(actual.get(pick.player.player_id, 0.0) for pick in starters)
    return {
        "xi_points": xi,
        "xi_plus_captain": xi + actual.get(captain.player.player_id, 0.0),
        "squad_autosub": autosub_points(plan, minutes, actual, rules),
    }


def autosub_points(
    plan: WildcardPlan, minutes: dict[int, float], points: dict[int, float], rules: GameRules
) -> float:
    """What the 15 really scores: FPL automatic substitutions, then captain or vice doubled.

    A starter with no minutes is replaced by the first bench player who played, in bench
    order, if the XI still meets every position minimum. Keepers only replace keepers.
    """

    def played(pick) -> bool:
        return minutes.get(pick.player.player_id, 0.0) > 0

    xi = list(plan.starters)
    used: set[int] = set()
    for out in [pick for pick in plan.starters if not played(pick)]:
        for sub in plan.bench:
            if sub.player.player_id in used or not played(sub):
                continue
            if (sub.player.element_type == 1) != (out.player.element_type == 1):
                continue
            trial = [pick for pick in xi if pick is not out] + [sub]
            if all(
                sum(pick.player.element_type == pos for pick in trial) >= rule.min_play
                for pos, rule in rules.positions.items()
            ):
                xi = trial
                used.add(sub.player.player_id)
                break
    captain = next(pick for pick in plan.picks if pick.captain)
    vice = next(pick for pick in plan.picks if pick.vice)
    armband = captain if played(captain) else vice if played(vice) else None
    total = sum(points.get(pick.player.player_id, 0.0) for pick in xi)
    return total + (points.get(armband.player.player_id, 0.0) if armband else 0.0)


def walk_forward(
    data: pd.DataFrame,
    *,
    configs: Iterable[EngineConfig] | None = None,
    include_baselines: bool = True,
    start_gw: int | None = None,
    rules: GameRules | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rebuild every projection from scratch each gameweek, using only earlier gameweeks.

    Returns (summary by method, per-gameweek rows).
    """
    configs = list(configs or [EngineConfig()])
    gameweeks = sorted(data["gw"].unique())
    first = start_gw or (gameweeks[0] + MIN_HISTORY_GWS)

    rows: list[dict[str, Any]] = []
    for gw in gameweeks:
        if gw < first:
            continue
        history = data[data["gw"] < gw]
        target = data[data["gw"] == gw]
        target = target[target["element"].isin(set(history["element"].unique()))]
        if len(target) < 50:
            continue

        state = GameweekState(gw=int(gw), history=history, target=target)
        actual = target["points"].to_numpy(dtype=float)

        predictions: dict[str, np.ndarray] = {c.label(): engine_predictions(state, c) for c in configs}
        if include_baselines:
            # Historical `xP` is deliberately absent here: it is leaked (official_ep_leakage).
            predictions["legacy_heuristic"] = legacy_predictions(state)
            predictions.update(baseline_predictions(state))

        for method, values in predictions.items():
            entry = {"gameweek": int(gw), "method": method, "rows": len(target)}
            entry.update(score_predictions(actual, values))
            if rules is not None:
                entry.update(squad_points(state, values, rules))
            rows.append(entry)

    per_gw = pd.DataFrame(rows)
    summary = (
        per_gw.drop(columns=["gameweek"])
        .groupby("method")
        .mean(numeric_only=True)
        .sort_values("ndcg@20", ascending=False)
    )
    return summary, per_gw


PAIRED_METRICS = ("ndcg@10", "ndcg@20", "top20_capture", "mae", "xi_plus_captain", "squad_autosub")


def paired_report(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """after − before, gameweek by gameweek, for every method both runs share.

    Squad points move by whole hauls, so a mean without its standard error over-claims.
    For mae a negative diff is the improvement.
    """
    merged = after.merge(before, on=["gameweek", "method"], suffixes=("", "_before"))
    rows = []
    for method, group in merged.groupby("method"):
        for metric in PAIRED_METRICS:
            if metric not in group or f"{metric}_before" not in group:
                continue
            diff = (group[metric] - group[f"{metric}_before"]).dropna().round(6)  # CSV float noise
            if len(diff) < 2:
                continue
            rows.append(
                {
                    "method": method,
                    "metric": metric,
                    "diff": diff.mean(),
                    "se": diff.std(ddof=1) / np.sqrt(len(diff)),
                    "win/tie/loss": f"{(diff > 0).sum()}/{(diff == 0).sum()}/{(diff < 0).sum()}",
                }
            )
    return pd.DataFrame(rows)


def official_ep_leakage(data: pd.DataFrame) -> dict[str, Any]:
    """Check whether the historical `xP` column can be used as an honest baseline.

    A real pre-deadline projection ranks some players who then do not play. If nobody in
    the top of the `xP` ranking recorded zero minutes, the column knows the lineups and
    cannot be compared against — see docs/EVAL.md.
    """
    rows = data[data["official_xp"] != 0]
    if rows.empty:
        return {"usable": False, "reason": "column is zero for every gameweek"}
    top = rows.nlargest(min(200, len(rows)), "official_xp")
    blank_share = float((top["minutes"] == 0).mean())
    correlation = float(np.corrcoef(rows["official_xp"], rows["points"])[0, 1])
    usable = blank_share > 0.02 and correlation < 0.55
    return {
        "usable": usable,
        "gameweeks_present": int(rows["gw"].nunique()),
        "rows": int(len(rows)),
        "correlation_with_actual": round(correlation, 4),
        "top200_zero_minutes_share": round(blank_share, 4),
        "reason": ""
        if usable
        else "correlates too strongly with realised points and never ranks a player who sat out",
    }


def calibration_report(data: pd.DataFrame, *, gw_from: int = 8) -> dict[str, Any]:
    """Are the engine's probabilities honest? Checks defensive contribution and clean sheets."""
    from fpl_predictor.models.scoring import Poisson, dc_threshold

    rows: list[dict[str, float]] = []
    for gw in sorted(data["gw"].unique()):
        if gw < gw_from:
            continue
        history = data[data["gw"] < gw]
        target = data[(data["gw"] == gw) & (data["minutes"] >= 60)]
        if history.empty or target.empty:
            continue
        state = GameweekState(gw=int(gw), history=history, target=target)
        accums, priors = state.accums(None), state.priors(None)
        league = state.league(5.0, 0.65)
        for row in target.itertuples():
            accum = accums.get(int(row.element))
            if accum is None:
                continue
            rates = build_rates(accum, priors)
            threshold = dc_threshold(int(row.element_type))
            share = min(1.0, float(row.minutes) / 90.0)
            _, goals_against = league.expected_goals(
                _team_key(row.team), _team_key(row.opponent), home=bool(row.home)
            )
            rows.append(
                {
                    "element_type": int(row.element_type),
                    "dc_predicted": Poisson(rates.dc90 * share).p_at_least(threshold) if threshold else np.nan,
                    "dc_actual": float(row.dc >= threshold) if threshold else np.nan,
                    "cs_predicted": Poisson(goals_against).p_zero(),
                    "cs_actual": float(row.goals_against == 0),
                }
            )

    table = pd.DataFrame(rows)
    if table.empty:
        return {}
    dc = table.dropna(subset=["dc_predicted"])
    return {
        "n": int(len(table)),
        "dc_predicted_rate": float(dc["dc_predicted"].mean()),
        "dc_actual_rate": float(dc["dc_actual"].mean()),
        "dc_by_position": {
            int(pos): {
                "predicted": round(float(group["dc_predicted"].mean()), 4),
                "actual": round(float(group["dc_actual"].mean()), 4),
                "n": int(len(group)),
            }
            for pos, group in dc.groupby("element_type")
        },
        "cs_predicted_rate": float(table["cs_predicted"].mean()),
        "cs_actual_rate": float(table["cs_actual"].mean()),
    }
