# FPL Predictor

@AGENTS.md

Claude Code does not load `.cursor/rules/` or `.cursor/skills/` on its own. Read the file for the area you are about to change before editing.

## Commands

Python 3.12. From the repo root, with `.venv` activated:

```bash
source .venv/bin/activate
pip install -e ".[dev]"    # first time, or after pyproject.toml changes

fpl serve                  # local UI at http://localhost:8000  (Ctrl+C to stop)
fpl wildcard               # upcoming gameweek only; --horizon N for a longer plan
fpl transfers --name demo  # needs a saved squad; default name is "default"
fpl status
fpl refresh
fpl backtest --season 2025-26   # walk-forward eval; slow (a few minutes)
python -m pytest -q
```

`fpl serve` is already the product UI. Do not add a second app, a JS framework, or a build step.

## Where the code lives

| Path | Role |
|---|---|
| `src/fpl_predictor/cli.py` | All user commands |
| `src/fpl_predictor/features/builder.py` | Live projections. Calls the engine; does not score players itself |
| `src/fpl_predictor/models/engine.py` | Expected points for one player-fixture |
| `src/fpl_predictor/models/team_strength.py` | Attack/defence indices. `PRIOR_GAMES` and `XG_WEIGHT` are the shipped constants |
| `src/fpl_predictor/models/rates.py` | Shrunk per-90 rates. Season-long, not recency-weighted |
| `src/fpl_predictor/models/minutes.py` | P(appear), P(60+), expected minutes |
| `src/fpl_predictor/models/scoring.py` | FPL points table and Poisson helpers |
| `src/fpl_predictor/models/points.py` | Old form × FDR heuristic. Baseline for `fpl backtest` only. Do not call it from the live path |
| `src/fpl_predictor/models/predict.py` | Returns `{}`. A trained model must beat the engine on `fpl backtest` before this changes |
| `src/fpl_predictor/optimize/wildcard.py` | MILP 15 + XI + captain |
| `src/fpl_predictor/optimize/transfers.py` | MILP transfers from a stored squad |
| `src/fpl_predictor/eval/backtest.py` | Walk-forward harness. `EngineConfig` defaults must stay equal to the live constants |
| `src/fpl_predictor/web/` | FastAPI + static HTML/CSS/JS. Serialize and call existing functions only |
| `src/fpl_predictor/explain.py` | Trust note shared by CLI and UI |
| `data/squads/` | Local user squads (gitignored). `data/snapshots/` is the API cache |

## Read before changing that area

- Architecture or a new command: `.cursor/skills/fpl-architecture/SKILL.md` and `.cursor/rules/core.mdc`
- Data, snapshots, leakage: `.cursor/skills/fpl-data-pipeline/SKILL.md` and `.cursor/rules/data-leakage.mdc`
- Projections or evaluation: `.cursor/skills/fpl-modeling-eval/SKILL.md` and `docs/EVAL.md`
- Squad or transfer solver: `.cursor/skills/fpl-optimization/SKILL.md` and `.cursor/rules/optimizer-constraints.mdc`

`docs/PLAN.md` is the original build plan. The engine, UI, and backtest described in `docs/EVAL.md` and `AGENTS.md` are what shipped. If they disagree, follow the code and `docs/EVAL.md`.

## Boundaries

- An LLM never picks the squad. Change projections or the solver, then let HiGHS choose.
- Do not put FPL rules, scoring, or player filters in `web/` or in JavaScript.
- Do not use official `ep_next` / `ep_this`, or vaastav `xP`, as a same-gameweek feature or as a backtest baseline. `xP` in the public archive is leaked; `docs/EVAL.md` records why.
- Do not hardcode a season's chip or scoring rules when `bootstrap-static` already has them. The points table in `models/scoring.py` is the exception: the API does not publish it.
- `teams[].strength` is unusable. Strength comes from results, xG, and FDR.
- Default horizon is 1 (the upcoming gameweek).
- Do not claim a projection change is better without `fpl backtest` beating the form and price baselines on NDCG / top-k and on solved-squad points.
- Tests live in `tests/`. Run `python -m pytest -q` after a behavior change.

## Working tree

One commit exists (`Add local FPL wildcard and transfer CLI`). The web UI, projection engine, and backtest are local changes on top of that commit and are not committed. Read `git status` before assuming `HEAD` is the product. Do not commit unless asked.
