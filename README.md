# FPL Predictor

Local CLI that refreshes official Fantasy Premier League data on every run, then recommends:

1. A legal **wildcard** 15
2. Legal **transfers** from a squad you store on disk

Predictions and the solver are separate. An optimizer (HiGHS) picks the squad. Prices, injuries, and availability always come from the live FPL API.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

fpl refresh
fpl wildcard --horizon 4 --budget 100.0
# reuse a snapshot without another download:
# fpl wildcard --no-refresh

# Save your 15 FPL element IDs, bank, and free transfers
fpl squad save --ids 1,2,3,... --bank 0.5 --ft 1
fpl transfers --name default --max-hits 1
```

`fpl refresh --full` also pulls per-player histories (slower, better minutes).

`fpl train` downloads vaastav historical gameweeks and reports walk-forward metrics. The live engine stays primary until that model beats a form baseline.

See `docs/PLAN.md` and `AGENTS.md` for the architecture.
