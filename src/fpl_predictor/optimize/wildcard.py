from __future__ import annotations

from dataclasses import dataclass

import pulp

from fpl_predictor.data.rules import GameRules
from fpl_predictor.features.builder import PlayerProjection
from fpl_predictor.optimize.solver import make_solver, require_optimal


@dataclass
class SquadPick:
    player: PlayerProjection
    starter: bool
    captain: bool
    vice: bool
    bench_order: int | None


@dataclass
class WildcardPlan:
    status: str
    objective: float
    bank: float
    picks: list[SquadPick]
    horizon_xpts: float

    @property
    def starters(self) -> list[SquadPick]:
        return [p for p in self.picks if p.starter]

    @property
    def bench(self) -> list[SquadPick]:
        return sorted([p for p in self.picks if not p.starter], key=lambda p: p.bench_order or 99)


def solve_lineup(
    projections: list[PlayerProjection],
    rules: GameRules,
    *,
    time_limit: int = 8,
) -> float:
    """Best XI + captain from a fixed 15. Does not re-check club or budget limits."""
    if len(projections) < rules.squad_play:
        return sum(p.xpts for p in projections)
    problem = pulp.LpProblem("fpl_lineup", pulp.LpMaximize)
    start = pulp.LpVariable.dicts("start", [p.player_id for p in projections], cat="Binary")
    captain = pulp.LpVariable.dicts("cap", [p.player_id for p in projections], cat="Binary")
    problem += pulp.lpSum(start[p.player_id] * p.xpts + captain[p.player_id] * p.xpts for p in projections)
    problem += pulp.lpSum(start[p.player_id] for p in projections) == rules.squad_play
    problem += pulp.lpSum(captain[p.player_id] for p in projections) == 1
    for p in projections:
        problem += captain[p.player_id] <= start[p.player_id]
    for pos_id, pos_rule in rules.positions.items():
        members = [p for p in projections if p.element_type == pos_id]
        if members:
            problem += pulp.lpSum(start[p.player_id] for p in members) >= pos_rule.min_play
            problem += pulp.lpSum(start[p.player_id] for p in members) <= min(pos_rule.max_play, len(members))
    status = problem.solve(make_solver(time_limit))
    if status != pulp.LpStatusOptimal:
        ranked = sorted(projections, key=lambda p: -p.xpts)
        return sum(p.xpts for p in ranked[:11]) + ranked[0].xpts
    return float(pulp.value(problem.objective) or 0.0)


def solve_wildcard(
    projections: list[PlayerProjection],
    rules: GameRules,
    *,
    budget: int | None = None,
    time_limit: int = 20,
) -> WildcardPlan:
    pool = [p for p in projections if p.can_select and p.availability > 0]
    budget = budget if budget is not None else rules.budget
    problem = pulp.LpProblem("fpl_wildcard", pulp.LpMaximize)
    squad = pulp.LpVariable.dicts("squad", [p.player_id for p in pool], cat="Binary")
    start = pulp.LpVariable.dicts("start", [p.player_id for p in pool], cat="Binary")
    captain = pulp.LpVariable.dicts("cap", [p.player_id for p in pool], cat="Binary")
    by_id = {p.player_id: p for p in pool}

    problem += pulp.lpSum(
        start[p.player_id] * p.xpts + captain[p.player_id] * p.xpts for p in pool
    )

    problem += pulp.lpSum(squad[p.player_id] for p in pool) == rules.squad_size
    problem += pulp.lpSum(start[p.player_id] for p in pool) == rules.squad_play
    problem += pulp.lpSum(captain[p.player_id] for p in pool) == 1
    problem += pulp.lpSum(squad[p.player_id] * p.now_cost for p in pool) <= budget

    for p in pool:
        problem += start[p.player_id] <= squad[p.player_id]
        problem += captain[p.player_id] <= start[p.player_id]

    for pos_id, pos_rule in rules.positions.items():
        members = [p for p in pool if p.element_type == pos_id]
        problem += pulp.lpSum(squad[p.player_id] for p in members) == pos_rule.squad_select
        problem += pulp.lpSum(start[p.player_id] for p in members) >= pos_rule.min_play
        problem += pulp.lpSum(start[p.player_id] for p in members) <= pos_rule.max_play

    teams = {p.team_id for p in pool}
    for team_id in teams:
        members = [p for p in pool if p.team_id == team_id]
        problem += pulp.lpSum(squad[p.player_id] for p in members) <= rules.team_limit

    status = problem.solve(make_solver(time_limit))
    require_optimal(status)

    chosen = [p for p in pool if pulp.value(squad[p.player_id]) > 0.5]
    starters = {p.player_id for p in chosen if pulp.value(start[p.player_id]) > 0.5}
    cap_id = next(p.player_id for p in chosen if pulp.value(captain[p.player_id]) > 0.5)
    vice_id = max(
        (p for p in chosen if p.player_id in starters and p.player_id != cap_id),
        key=lambda p: p.xpts,
    ).player_id

    bench_gk = [p for p in chosen if p.player_id not in starters and p.element_type == 1]
    bench_out = sorted(
        [p for p in chosen if p.player_id not in starters and p.element_type != 1],
        key=lambda p: -p.xpts,
    )
    bench_seq = bench_gk + bench_out
    bench_order = {p.player_id: i + 1 for i, p in enumerate(bench_seq)}

    picks = [
        SquadPick(
            player=p,
            starter=p.player_id in starters,
            captain=p.player_id == cap_id,
            vice=p.player_id == vice_id,
            bench_order=None if p.player_id in starters else bench_order[p.player_id],
        )
        for p in chosen
    ]
    picks.sort(key=lambda p: (not p.starter, p.player.element_type, -p.player.xpts))
    spent = sum(p.now_cost for p in chosen)
    xi_pts = sum(p.xpts for p in chosen if p.player_id in starters)
    cap_pts = by_id[cap_id].xpts
    return WildcardPlan(
        status="Optimal",
        objective=float(pulp.value(problem.objective) or 0.0),
        bank=(budget - spent) / 10,
        picks=picks,
        horizon_xpts=xi_pts + cap_pts,
    )
