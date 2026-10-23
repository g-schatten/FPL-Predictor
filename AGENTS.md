# FPL Predictor — Agent Context

Local CLI tool that recommends Fantasy Premier League squads. Two user-facing modes:

1. **Wildcard** — build the best legal 15-player squad for a horizon of upcoming gameweeks.
2. **Transfers** — take a stored user squad (players, bank, free transfers, selling prices) and recommend the best legal transfer set.

Both modes ship as a CLI and as a local dark web UI (`fpl serve`, FastAPI in `src/fpl_predictor/web/`). The UI is a thin layer: it calls the same projection and solver functions and adds no game logic of its own. Keep prediction and optimization separate. Refresh official FPL data before every recommendation unless the user asked not to.

## Hard architecture rule

Prediction and optimization are separate systems.

- A model (or ensemble) outputs expected points / minutes / risk per player-gameweek.
- A mixed-integer solver picks a legal squad or transfer set from those numbers.
- Never ask an LLM, genetic algorithm, or heuristic ranker to "just pick the team."
- Never treat official FPL `ep_next` / `ep_this` as ground truth or as an unshifted same-gameweek feature.

## Live game facts (verify on each data refresh)

Official public API: `https://fantasy.premierleague.com/api/`

Checked 2026-09-13:

- Season **2026/27**, 657 players, 20 clubs, 380 fixtures.
- Current event GW4 (unfinished). Next deadline: **GW5, 2026-09-18 17:30 UTC**.
- Budget **£100.0m** (`squad_total_spend` = 1000 in 0.1m units).
- Squad: 15 players, max 3 per club, 2 GKP / 5 DEF / 5 MID / 3 FWD.
- Starting XI: 11 players; formations must satisfy 1 GKP, 3–5 DEF, 2–5 MID, 1–3 FWD.
- 1 free transfer per GW, bank up to **5** (`max_extra_free_transfers` = 4 extra). Hits cost **4** points. Transfer cap 20.
- Selling-price rule: `transfers_sell_on_fee` = 0.5 (user keeps half of price rises).
- Two chip sets: Wildcard, Free Hit, Bench Boost, Triple Captain in GW2–19 and again in GW20–38 (BB/TC also usable GW1). One chip per GW. First-half chips expire after GW19.
- Defensive contribution still scores: DEF +2 at 10 CBIT; MID/FWD +2 at 12 CBIRT.

`teams[].strength` is currently null and attack/defence strength fields are 0. Do not rely on them. Use fixtures FDR, Club Elo, and xG instead.

## How projections are produced

`models/engine.py` is the live projection engine. Per player-fixture it combines:

- per-90 xG, xA, bonus, defensive actions, saves and cards, shrunk toward position medians;
  each match adds at most 1.0 xG / 1.0 xA so one outlier game cannot dominate
- team attack/defence indices from finished results and aggregated xG (`models/team_strength.py`),
  shrunk toward an FDR prior because `teams[].strength` is null
- expected goals for and against for that exact fixture, then Poisson tails for clean sheets,
  goals-conceded penalties, saves and the defensive-contribution threshold
- expected minutes with P(appear) and P(60+) from recent selection plus availability; live
  per-match minutes come from `/event/{gw}/live/`, cached per finished gameweek

The wildcard solver gives bench players a small weight (0.1 outfield, 0.03 keeper) so the
bench is made of players who actually play. `fpl backtest` scores squads with autosubs.

Do not add "form" or `ep_next` back as the primary signal. Season-long rates beat recency
weighting and blending recent points made ranking worse — both measured, see [docs/EVAL.md](docs/EVAL.md).

Default horizon is **1**: recommendations target the upcoming gameweek unless the user asks
for a longer plan.

## Required reading before changing code

- [docs/EVAL.md](docs/EVAL.md) — what the engine uses, backtest results, tuned constants.
- [docs/RESEARCH.md](docs/RESEARCH.md) — prior art, datasets, leakage findings.
- [docs/PLAN.md](docs/PLAN.md) — phased build and acceptance tests.
- Skills: `fpl-architecture`, `fpl-data-pipeline`, `fpl-modeling-eval`, `fpl-optimization`.

## Trust standard

A recommendation is trustworthy only if:

1. Features used at inference time were available **before** the relevant deadline.
2. Walk-forward backtests beat the form and price baselines on ranking metrics (NDCG / top-k
   capture) and on the actual points a solved squad scored — not only MAE. Run `fpl backtest`
   before claiming any change is an improvement. The public historical `xP` column is leaked
   and cannot serve as the `ep_next` baseline; comparing against live `ep_next` needs
   accumulated pre-deadline snapshots.
3. Every output squad is legal under the live `bootstrap-static` rules payload, not a hardcoded older season.
4. User-squad recommendations respect **selling prices**, bank, free transfers, and hit cost.
5. Uncertainty is shown (minutes risk, rotation, injury news). A single point estimate is not enough.
