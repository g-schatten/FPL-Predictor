# FPL Predictor — Implementation Plan

Do not start this plan until the user asks to implement. Research and skills are already in the repo.

## Goal

A local CLI the user runs to:

1. Refresh FPL (+ optional Understat/Elo) data.
2. Choose **wildcard** or **transfers**.
3. Get a legal, explained recommendation.

Trust comes from a walk-forward harness that must beat official `ep_next`.

## Architecture

```
┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────┐
│  Refresh    │ → │  Features    │ → │  Models     │ → │  Solver  │
│  snapshots  │   │  deadline-   │   │  xMins+xPts │   │  HiGHS   │
│  FPL+xG+Elo │   │  safe store  │   │  +uncertainty│   │  WC / TR │
└─────────────┘   └──────────────┘   └─────────────┘   └──────────┘
                                              ↓
                                    CLI + local squad JSON
```

Suggested layout (when implementation starts):

```
src/fpl_predictor/
  cli.py
  data/     fpl_api.py  snapshots.py  understat.py  elo.py  mappings.py
  features/ builder.py  leakage.py
  models/   minutes.py  points.py  predict.py
  optimize/ wildcard.py transfers.py rules.py
  squad/    store.py
tests/
data/       gitignored snapshots; committed schemas + tiny fixtures
```

## Phase 1 — Data refresh (week 1)

- HTTP client with User-Agent, retries, and a per-run cache.
- Pull `bootstrap-static`, `fixtures`, `event-status`, `set-piece-notes`.
- Incremental `element-summary` for players whose history is stale.
- Write `data/snapshots/<utc>/` plus a `data/current` pointer.
- Parse live rules: budget, chip windows, position limits, sell-on fee.
- CLI: `fpl refresh` prints GW, deadline, player count, snapshot path.
- Tests: parse a frozen bootstrap fixture; refuse to use a snapshot after a deadline for that GW’s features.

**Out of scope:** model training, solver.

## Phase 2 — Historical warehouse (week 1–2)

- One-time import of vaastav seasons needed for training (start with 2021/22–2025/26).
- Normalize to a single `player_gw` table: `fpl_code`, season, GW, minutes, points, opponent, home, prices, ICT, FPL xG.
- Player mapping table (`fpl_code` ↔ Understat / FBref). Log unmatched.
- Optional first Understat + Club Elo pull via soccerdata; cache locally.
- Rebuild historical FPL points under 2025/26+ rules **or** tag `ruleset` and train separately.

## Phase 3 — Features (week 2)

- Rolling 1/3/5/10/38 on **completed** matches only.
- Opponent + home/away + FDR + Elo delta.
- H2H from football-data.co.uk (last N meetings, goals, xG if available).
- Availability, news flags, set-piece order.
- Pre-deadline `ep_next` if a snapshot exists; else `-1`.
- Unit tests that fail if a same-GW outcome column leaks into X.

## Phase 4 — Models (week 3–4)

- Minutes model: 3-class (0 / 1–59 / 60+).
- Position-specific points models (XGBoost first; OpenFPL-style ensemble later if it wins).
- Combine: `xPts = Σ P(bucket) * E[points | bucket]` or equivalent.
- Walk-forward by GW. Metrics: MAE, NDCG@10, top-20 recall by position, P(60+) Brier.
- Gate: must beat `ep_next` and last-4-GW form on NDCG for completed 2025/26 and available 2026/27 GWs.
- Persist model artifacts with the feature-schema hash.

## Phase 5 — Wildcard solver (week 4)

- HiGHS 15-man + XI + captain.
- Budget, 3-per-club, formation bounds from live settings.
- Horizon weights default 4 GWs.
- CLI: `fpl wildcard --horizon 4 --budget 100.0`
- Print XI, bench, captain, bank, projected points, flagged minutes risks.
- Tests: infeasible budgets fail cleanly; no 4-from-one-club squad; formation illegal without 3 DEF.

## Phase 6 — User squad + transfers (week 5)

- Local JSON store: 15 IDs, purchase/selling prices, bank, FTs, chips, locks/bans.
- Optional import from public `entry/{id}/event/{gw}/picks/` (prices still local).
- Transfer MILP: hits, sell-on, max hits flag.
- CLI: `fpl squad save`, `fpl transfers --horizon 4 --max-hits 1`
- Always show the do-nothing baseline vs the recommended hit.

## Phase 7 — Trust extras (after the two modes work)

- Alternative solutions (2nd / 3rd best squad).
- Monte Carlo over minutes uncertainty.
- Multi-competition minutes from FBref for rotation.
- Optional uploaded FPL Review CSV as a **challenger** projection, same solver.
- Chip planner only if the user asks; default is no auto-chip.

## Acceptance tests

A phase is done only if:

- [ ] `fpl refresh` succeeds against the live API and writes a timestamped snapshot.
- [ ] Feature builder rejects same-GW labels (pytest).
- [ ] Walk-forward report exists and is compared to `ep_next`.
- [ ] Wildcard output is a legal 15 with ≤3 per club and cost ≤ budget.
- [ ] Transfer output never spends more than bank + selling prices.
- [ ] Injury/0% availability players are not started unless every option is worse and the printout says so.

## What we are deliberately not building first

- A website.
- Login cookie scraping for `/my-team/`.
- An LLM that selects players.
- Live in-play bots.
- Betting advice.

## Implementation trigger

Wait for an explicit user request such as “implement phase 1” or “build the refresh CLI.”
