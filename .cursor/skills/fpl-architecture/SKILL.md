---
name: fpl-architecture
description: Guides Fantasy Premier League predictor architecture, CLI UX, and the predict-vs-optimize split. Use when designing, scaffolding, or changing the fpl-predictor system, wildcard/transfer product flow, or when the user mentions project structure, AI training, or how recommendations should be produced.
---

# FPL architecture

## Product

Local CLI. On every run: refresh official FPL data, then one of:

1. **Wildcard** — unconstrained rebuild of a 15-man squad for a GW horizon.
2. **Transfers** — best legal moves from a user-owned squad stored locally.

Trust comes from walk-forward evaluation, not from an LLM sounding confident.

## Required split

```
refresh APIs → features (deadline-safe) → predict xMins + xPts → MILP solve → explain
```

| Layer | Owns | Must not do |
|---|---|---|
| Data | snapshots, joins, ID maps | invent missing players |
| Features | rolling form, opponent, H2H, Elo | use same-GW outcomes |
| Models | P(minutes), xPts, uncertainty | pick a squad |
| Solver | legal squad / transfers | override FPL rules |
| CLI | inputs, saved squads, printed plan | silently change chips |

Do not collapse this into "ask a model for the best team."

## Default stack

- Python 3.12+, `httpx`, `pandas`/`polars`, `pyarrow`, `xgboost`, `highspy`
- SQLite or local parquet under `data/` (gitignored raw dumps; commit schemas only)
- `typer` CLI
- `pytest` with fixture snapshots

## CLI contract

```
fpl refresh
fpl wildcard [--horizon 4] [--budget 100.0]
fpl transfers --squad path/or-name [--max-hits 1] [--horizon 4]
fpl squad save|show
```

User squad JSON must include: 15 element IDs, purchase prices, selling prices, bank, free transfers, chips remaining, optional locks/bans.

## When implementing

1. Read [docs/PLAN.md](../../../docs/PLAN.md) and implement only the requested phase.
2. Load live `game_settings` / `element_types` / `chips` rather than copying last season.
3. Show projections **and** solver constraints in the output so a user can reject a pick.
4. Keep commercial projection CSVs (FPL Review) optional and unused by default.

## Additional resources

- Datasets and leakage: skill `fpl-data-pipeline`
- Training / tests: skill `fpl-modeling-eval`
- Solver rules: skill `fpl-optimization`
- Prior art: [docs/RESEARCH.md](../../../docs/RESEARCH.md)
