"""Legacy form-and-FDR heuristic.

Superseded by `models/engine.py`, which beat this by 0.058 NDCG@20 and ~8 actual points
per gameweek in the walk-forward test (docs/EVAL.md). Kept only as the baseline that
`fpl backtest` scores new work against; nothing in the live path calls it.
"""

from __future__ import annotations

FDR_MULT = {1: 1.18, 2: 1.08, 3: 1.00, 4: 0.90, 5: 0.78}


def fixture_multiplier(fdr: int, home: bool) -> float:
    base = FDR_MULT.get(int(fdr), 1.0)
    venue = 1.05 if home else 0.95
    return base * venue


def project_gameweek_points(
    *,
    ep_next: float,
    form: float,
    availability: float,
    xmins: float,
    fdr: int,
    home: bool,
    use_official_ep: bool,
) -> float:
    """Deadline-safe blend. Official ep_next is only used for the next GW."""
    minutes_scale = min(1.0, xmins / 75.0) if xmins else 0.0
    fixture = fixture_multiplier(fdr, home)
    form_pts = max(0.0, form) * fixture * minutes_scale
    if use_official_ep and ep_next > 0:
        official = max(0.0, ep_next) * availability
        # Official EP already includes FPL's fixture view; keep a light FDR tweak.
        blended = 0.7 * official + 0.3 * form_pts
        return blended * (0.92 + 0.08 * fixture)
    return form_pts * availability
