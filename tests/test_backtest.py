from fpl_predictor.eval.backtest import autosub_points
from fpl_predictor.optimize.wildcard import solve_wildcard
from test_solver import _pool, _rules


def test_autosub_replaces_a_blank_starter_and_vice_takes_the_armband() -> None:
    plan = solve_wildcard(_pool(), _rules())
    captain = next(p for p in plan.picks if p.captain)
    vice = next(p for p in plan.picks if p.vice)
    minutes = {p.player.player_id: 90.0 for p in plan.picks}
    points = {p.player.player_id: 2.0 for p in plan.picks}
    minutes[captain.player.player_id] = points[captain.player.player_id] = 0.0
    points[vice.player.player_id] = 5.0
    # 9 starters on 2, vice 5 doubled to 10, first legal outfield sub 2.
    assert autosub_points(plan, minutes, points, _rules()) == 9 * 2.0 + 10.0 + 2.0
