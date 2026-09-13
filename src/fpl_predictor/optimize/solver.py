from __future__ import annotations

import pulp


def make_solver(time_limit: int = 20) -> pulp.LpSolver:
    try:
        return pulp.HiGHS(msg=False, timeLimit=time_limit)
    except Exception:
        return pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit)


def require_optimal(status: int) -> None:
    if status != pulp.LpStatusOptimal:
        raise RuntimeError(f"Solver did not find an optimal plan ({pulp.LpStatus[status]}).")
