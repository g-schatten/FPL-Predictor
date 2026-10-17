from fpl_predictor.data.rules import GameRules, PositionRule
from fpl_predictor.features.builder import PlayerProjection
from fpl_predictor.optimize.transfers import solve_transfers
from fpl_predictor.optimize.wildcard import solve_wildcard
from fpl_predictor.squad.store import UserSquad


def _rules() -> GameRules:
    return GameRules(
        squad_size=15,
        squad_play=11,
        team_limit=3,
        budget=1000,
        sell_on_fee=0.5,
        max_extra_free_transfers=4,
        hit_cost=4,
        transfers_cap=20,
        positions={
            1: PositionRule(1, "GKP", 2, 1, 1),
            2: PositionRule(2, "DEF", 5, 3, 5),
            3: PositionRule(3, "MID", 5, 2, 5),
            4: PositionRule(4, "FWD", 3, 1, 3),
        },
    )


def _player(pid: int, pos: int, team: int, cost: int, xpts: float, **kwargs) -> PlayerProjection:
    names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    return PlayerProjection(
        player_id=pid,
        code=pid,
        web_name=f"P{pid}",
        team_id=team,
        team_short=f"T{team}",
        position=names[pos],
        element_type=pos,
        now_cost=cost,
        status=kwargs.get("status", "a"),
        news="",
        chance_next=100,
        availability=kwargs.get("availability", 1.0),
        xmins=kwargs.get("xmins", 80),
        ep_next=xpts,
        form=xpts,
        xpts_by_gw={5: xpts},
        xpts=xpts,
        risk_flags=[],
    )


def _pool() -> list[PlayerProjection]:
    players: list[PlayerProjection] = []
    pid = 1
    # 4 GKs cheap/good
    for i, xpts in enumerate([4.0, 3.2, 2.0, 1.0]):
        players.append(_player(pid, 1, 10 + i, 45 + i, xpts))
        pid += 1
    # 12 DEFs across teams
    for i in range(12):
        players.append(_player(pid, 2, 1 + (i % 8), 45 + (i % 5), 5.0 - i * 0.2))
        pid += 1
    # 12 MIDs
    for i in range(12):
        players.append(_player(pid, 3, 1 + (i % 8), 60 + i, 8.0 - i * 0.25))
        pid += 1
    # 8 FWDs
    for i in range(8):
        players.append(_player(pid, 4, 1 + (i % 8), 70 + i, 7.5 - i * 0.3))
        pid += 1
    return players


def test_wildcard_is_legal() -> None:
    plan = solve_wildcard(_pool(), _rules(), budget=1000)
    ids = [p.player.player_id for p in plan.picks]
    assert len(ids) == 15
    assert len(set(ids)) == 15
    assert sum(p.player.now_cost for p in plan.picks) <= 1000
    by_pos = {}
    by_team: dict[int, int] = {}
    for pick in plan.picks:
        by_pos[pick.player.element_type] = by_pos.get(pick.player.element_type, 0) + 1
        by_team[pick.player.team_id] = by_team.get(pick.player.team_id, 0) + 1
    assert by_pos == {1: 2, 2: 5, 3: 5, 4: 3}
    assert max(by_team.values()) <= 3
    assert sum(1 for p in plan.picks if p.starter) == 11
    assert sum(1 for p in plan.picks if p.captain) == 1
    starters = [p for p in plan.picks if p.starter]
    assert sum(1 for p in starters if p.player.element_type == 1) == 1
    assert 3 <= sum(1 for p in starters if p.player.element_type == 2) <= 5


def test_wildcard_respects_tight_budget() -> None:
    try:
        solve_wildcard(_pool(), _rules(), budget=400)
    except RuntimeError as exc:
        assert "optimal" in str(exc).lower()
        return
    raise AssertionError("expected infeasible tiny budget")


def test_transfers_never_overspend() -> None:
    pool = _pool()
    # Take a legal but mid-quality 15 as the current squad.
    cheap = (
        [p for p in pool if p.element_type == 1][:2]
        + [p for p in pool if p.element_type == 2][-5:]
        + [p for p in pool if p.element_type == 3][-5:]
        + [p for p in pool if p.element_type == 4][-3:]
    )
    squad = UserSquad(
        name="t",
        player_ids=[p.player_id for p in cheap],
        purchase_prices={p.player_id: p.now_cost for p in cheap},
        selling_prices={p.player_id: p.now_cost for p in cheap},
        bank=0.5,
        free_transfers=1,
    )
    plan = solve_transfers(pool, _rules(), squad, max_hits=1)
    assert plan.hits <= 1
    assert plan.bank >= -1e-6
    assert len(plan.wildcard.picks) == 15


def test_bench_takes_the_best_spare_keeper_when_money_allows() -> None:
    plan = solve_wildcard(_pool(), _rules())
    bench_keeper = next(p.player for p in plan.bench if p.player.element_type == 1)
    assert bench_keeper.xpts == 3.2  # a zero bench weight was indifferent and kept the 1.0 keeper
