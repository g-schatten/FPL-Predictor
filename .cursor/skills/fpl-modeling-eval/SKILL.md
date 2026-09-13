---
name: fpl-modeling-eval
description: Trains and evaluates leakage-safe FPL expected-points and minutes models. Use when building features, training XGBoost or other models, backtesting, comparing to ep_next, or when the user mentions accuracy, trust, walk-forward tests, or AI training.
---

# FPL modeling and evaluation

## Target design

Predict **per player-fixture**, then roll up to gameweek (doubles/blanks later).

Train two heads, then combine:

1. **Minutes** — P(0), P(1–59), P(60+), optional expected minutes.
2. **Points | minutes bucket** — or a points model multiplied by P(play).

Position-specific models (GKP / DEF / MID / FWD). Do not train one global regressor as the only model.

FPL scoring changed in 2025/26 (defensive contribution). Use a `ruleset` column and either:

- train only on the current ruleset plus a rebuilt historical target, or
- include `ruleset` and DC features only where they existed.

## Feature families (deadline-safe)

Rolling windows of last 1 / 3 / 5 / 10 / 38 **completed** matches, all shifted:

- Player: points, minutes, xG/xA, ICT, BPS, cards, set-piece order, availability %, news
- Team: xG for/against, PPDA, Deep, Elo, league rank
- Opponent: same, plus FDR and home/away
- H2H: prior PL meetings (football-data.co.uk), not just this season
- Multi-competition: recent minutes in Europe/cups (rotation risk)
- FPL `ep_next` only from a **pre-deadline** snapshot; missing = `-1`

Same-GW realized `minutes`, `starts`, `total_points`, `defensive_contribution` are labels.

## Validation

Walk-forward by gameweek. Retrain on all earlier GWs (and earlier seasons). Never random-split player-rows.

Report metrics **inside each GW**, then average:

- MAE / RMSE of points (secondary)
- NDCG@10 and recall of the actual top 20 scorers by position (primary — this is what the solver uses)
- Calibration of P(60+)
- Squad-level: points of a solved wildcard vs baseline (FPL `ep_next` + same solver)

Must beat, on the same eligible rows:

1. Official `ep_next`
2. Last-4-GW points per 90 × expected minutes
3. Price rank

If a change does not beat (1) on NDCG, do not ship it as "better AI."

## Leakage checklist (run in CI)

- No feature whose `source_available_time >= deadline`
- No unshifted vaastav `xP`
- No filling missing `ep_next` with 0
- No using post-match element-summary fields for the GW being predicted

## What we are not copying blindly

OpenFPL: strong public baseline (FPL + Understat, position ensembles). Improve with a minutes model, Elo, H2H, multi-comp minutes, and era-aware DC points.

Dastan / SmartPlay: treat their leakage rules as mandatory. Do not copy an undocumented 286-feature dump without reproducing the contract.

FPL Review: commercial EV + xMins, hourly. Optional later comparison, not a training label.

## Additional resources

- OpenFPL paper: https://arxiv.org/abs/2508.09992
- Dastan data rules: https://github.com/qazybekb/smartplayfpl-dastan
- [docs/RESEARCH.md](../../../docs/RESEARCH.md)
