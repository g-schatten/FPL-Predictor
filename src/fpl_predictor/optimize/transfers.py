from __future__ import annotations

from dataclasses import dataclass

import pulp

from fpl_predictor.data.rules import GameRules, selling_price
from fpl_predictor.features.builder import PlayerProjection
from fpl_predictor.optimize.solver import make_solver, require_optimal
from fpl_predictor.optimize.wildcard import SquadPick, WildcardPlan, solve_lineup
from fpl_predictor.squad.store import UserSquad


@dataclass
class TransferMove:
    player_out: PlayerProjection
    player_in: PlayerProjection
    sell: int
    buy: int


@dataclass
class TransferPlan:
    wildcard: WildcardPlan
    transfers: list[TransferMove]
    hits: int
    hit_cost: int
    do_nothing_xpts: float
    delta_vs_hold: float
    bank: float
    free_transfers_used: int


def _hold_xpts(projections: list[PlayerProjection], squad: UserSquad, rules: GameRules) -> float:
    owned = [p for p in projections if p.player_id in set(squad.player_ids)]
    return solve_lineup(owned, rules)


def solve_transfers(
    projections: list[PlayerProjection],
    rules: GameRules,
    squad: UserSquad,
    *,
    max_hits: int = 1,
    time_limit: int = 25,
) -> TransferPlan:
    owned_ids = set(squad.player_ids)
    pool = [
        p
        for p in projections
        if p.can_select and (p.availability > 0 or p.player_id in owned_ids)
    ]
    by_id = {p.player_id: p for p in pool}
    missing = [pid for pid in squad.player_ids if pid not in by_id]
    if missing:
        raise ValueError(f"Stored squad player ids not in the current snapshot: {missing}")

    owned = owned_ids
    sell = {
        pid: squad.selling_prices.get(
            pid,
            selling_price(squad.purchase_prices.get(pid, by_id[pid].now_cost), by_id[pid].now_cost, rules.sell_on_fee),
        )
        for pid in owned
    }
    bank = squad.bank_tenths
    ft = squad.free_transfers
    locks = set(squad.locks)
    bans = set(squad.bans)

    problem = pulp.LpProblem("fpl_transfers", pulp.LpMaximize)
    ids = [p.player_id for p in pool]
    x = pulp.LpVariable.dicts("squad", ids, cat="Binary")
    start = pulp.LpVariable.dicts("start", ids, cat="Binary")
    captain = pulp.LpVariable.dicts("cap", ids, cat="Binary")
    hits = pulp.LpVariable("hits", lowBound=0, upBound=max_hits, cat="Integer")

    problem += pulp.lpSum(start[p.player_id] * p.xpts + captain[p.player_id] * p.xpts for p in pool) - rules.hit_cost * hits

    problem += pulp.lpSum(x[i] for i in ids) == rules.squad_size
    problem += pulp.lpSum(start[i] for i in ids) == rules.squad_play
    problem += pulp.lpSum(captain[i] for i in ids) == 1
    for p in pool:
        problem += start[p.player_id] <= x[p.player_id]
        problem += captain[p.player_id] <= start[p.player_id]
        if p.player_id in bans:
            problem += x[p.player_id] == 0
        if p.player_id in locks:
            problem += x[p.player_id] == 1

    for pos_id, pos_rule in rules.positions.items():
        members = [p.player_id for p in pool if p.element_type == pos_id]
        problem += pulp.lpSum(x[i] for i in members) == pos_rule.squad_select
        problem += pulp.lpSum(start[i] for i in members) >= pos_rule.min_play
        problem += pulp.lpSum(start[i] for i in members) <= pos_rule.max_play

    for team_id in {p.team_id for p in pool}:
        members = [p.player_id for p in pool if p.team_id == team_id]
        problem += pulp.lpSum(x[i] for i in members) <= rules.team_limit

    bought = pulp.lpSum(x[p.player_id] * p.now_cost for p in pool if p.player_id not in owned)
    sold = pulp.lpSum((1 - x[pid]) * sell[pid] for pid in owned)
    problem += bank + sold - bought >= 0

    n_in = pulp.lpSum(x[p.player_id] for p in pool if p.player_id not in owned)
    problem += hits >= n_in - ft
    problem += n_in <= ft + max_hits

    status = problem.solve(make_solver(time_limit))
    require_optimal(status)

    new_ids = {pid for pid in ids if pulp.value(x[pid]) > 0.5}
    ins = sorted(new_ids - owned)
    outs = sorted(owned - new_ids)
    moves = []
    # Pair by position then xpts so the printout is readable.
    out_players = sorted((by_id[i] for i in outs), key=lambda p: (p.element_type, p.xpts))
    in_players = sorted((by_id[i] for i in ins), key=lambda p: (p.element_type, -p.xpts))
    for player_out, player_in in zip(out_players, in_players):
        moves.append(
            TransferMove(
                player_out=player_out,
                player_in=player_in,
                sell=sell[player_out.player_id],
                buy=player_in.now_cost,
            )
        )

    starters = {pid for pid in new_ids if pulp.value(start[pid]) > 0.5}
    cap_id = next(pid for pid in new_ids if pulp.value(captain[pid]) > 0.5)
    vice_id = max(
        (by_id[pid] for pid in starters if pid != cap_id),
        key=lambda p: p.xpts,
    ).player_id
    bench_gk = [by_id[pid] for pid in new_ids if pid not in starters and by_id[pid].element_type == 1]
    bench_out = sorted(
        [by_id[pid] for pid in new_ids if pid not in starters and by_id[pid].element_type != 1],
        key=lambda p: -p.xpts,
    )
    bench_order = {p.player_id: i + 1 for i, p in enumerate(bench_gk + bench_out)}
    picks = [
        SquadPick(
            player=by_id[pid],
            starter=pid in starters,
            captain=pid == cap_id,
            vice=pid == vice_id,
            bench_order=None if pid in starters else bench_order[pid],
        )
        for pid in new_ids
    ]
    picks.sort(key=lambda p: (not p.starter, p.player.element_type, -p.player.xpts))
    spent = sum(by_id[pid].now_cost for pid in new_ids if pid not in owned)
    gained = sum(sell[pid] for pid in owned if pid not in new_ids)
    new_bank = (bank + gained - spent) / 10
    hits_used = int(round(pulp.value(hits) or 0))
    hold = _hold_xpts(projections, squad, rules)
    new_xi = sum(by_id[pid].xpts for pid in starters) + by_id[cap_id].xpts
    wildcard = WildcardPlan(
        status="Optimal",
        objective=float(pulp.value(problem.objective) or 0.0),
        bank=new_bank,
        picks=picks,
        horizon_xpts=new_xi,
    )
    return TransferPlan(
        wildcard=wildcard,
        transfers=moves,
        hits=hits_used,
        hit_cost=hits_used * rules.hit_cost,
        do_nothing_xpts=hold,
        delta_vs_hold=new_xi - hold - hits_used * rules.hit_cost,
        bank=new_bank,
        free_transfers_used=min(len(moves), ft),
    )
