---
name: fpl-optimization
description: Builds legal Fantasy Premier League wildcard and transfer MILP solvers. Use when implementing squad selection, transfers, hits, selling prices, chips, captaincy, formations, HiGHS/PuLP, or when the user mentions best team, wildcard, or best transfer.
---

# FPL optimization

The solver consumes projected points. It does not invent projections.

Engine: HiGHS (`highspy`). PuLP only as a thin wrapper if needed.

## Wildcard

Decision: 15 binary squad picks, 11 starters, 1 captain, 1 vice, bench order.

Enforce live `game_settings` / `element_types`:

- 2 GKP, 5 DEF, 5 MID, 3 FWD
- max 3 per `team`
- `sum(now_cost) <= budget` in 0.1m units (default 1000)
- 11 starters; 1 GKP; DEF 3–5; MID 2–5; FWD 1–3
- captain and vice are starters; captain points count twice (or three times only if user forced Triple Captain)

Horizon objective:

`sum_g w_g * (xi_points + captain_extra) - risk_penalty`

Default `w = [1.0, 0.8, 0.6, 0.4]` for the next 4 GWs. Do not optimize chips unless asked.

## Transfers

Inputs from local squad JSON: 15 IDs, purchase prices, selling prices, bank, free transfers, locks, bans.

- `n_in = n_out`
- cash: `bank + sum(sell_out) - sum(buy_in) >= 0`
- selling prices are **not** `now_cost`; apply FPL half-profit (`transfers_sell_on_fee` 0.5) when the user did not supply them
- hits = `max(0, n_in - free_transfers) * 4`
- objective = horizon xPts of new squad − hit cost − optional risk
- default search: 0, 1, 2, … up to user `--max-hits` (not an unbounded hit farm)

## 2026/27 chips

Two identical sets. First half ends GW19; second starts GW20. Wildcard/Free Hit start GW2. One chip per GW. Free Hits cannot be consecutive across GW19→20.

Do not auto-play a chip. Wildcard mode is an explicit user choice.

## Output

Always print:

- XI, bench, captain/vice, remaining bank
- transfers in/out with prices and xPts delta vs do-nothing
- solver status (`Optimal` required to show a plan)
- top 3 alternative solutions if the user asked for them (fix previous squad and re-solve)

If the model is uncertain (low P(60+), flag, 25% chance), say so next to the pick.

## Additional resources

- Sertalp / Solio open solver: https://github.com/solioanalytics/open-fpl-solver
- SmartPlay solver (HiGHS, chips, sell-on): https://github.com/qazybekb/smartplayfpl-solver
- Live rules: `bootstrap-static` → `game_settings`, `chips`
