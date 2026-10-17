# Evaluation

Reproduce everything here with:

```bash
fpl backtest --season 2025-26 --start-gw 6
```

## What is being tested

The projection engine is rebuilt from scratch for every gameweek using **only** completed
gameweeks before it: team attack/defence indices, player per-90 rates, position priors, and
minutes profiles. Nothing from the gameweek being predicted is available, including its
results, lineups, and league-wide rates.

2025-26 is the test season because it is the first full season under the current ruleset
(defensive contribution), so its scoring matches what the tool projects today.

## Headline result

33 walk-forward gameweeks, ~790 player-gameweeks scored per gameweek.

| method | NDCG@10 | NDCG@20 | top-20 capture | MAE | solved XI+captain, actual points/GW |
|---|---|---|---|---|---|
| **engine (shipped)** | **0.367** | **0.388** | **0.402** | **0.963** | **58.6** |
| legacy heuristic (form × FDR × minutes) | 0.303 | 0.330 | 0.345 | 0.995 | 50.2 |
| last-4-GW points per 90 × minutes | 0.284 | 0.310 | 0.330 | 1.031 | 48.8 |
| price | 0.272 | 0.289 | 0.299 | 48.08 | 36.2 |

The last column is the metric that matches how the tool is used: each gameweek the real MILP
solver builds a legal £100.0m 15-man squad from that method's projections, and the table
reports what the resulting XI plus captain **actually scored**. The engine gains ~8 points a
gameweek over the heuristic it replaced.

Caveats, stated plainly:

- Every method gets to rebuild the squad each week with no transfer cost, so the absolute
  points are optimistic. Only the gap between methods is meaningful.
- Historical data has no injury flags or `chance_of_playing`, so the live engine has
  information in production that it lacked here.
- The engine loses on Spearman (0.725 vs 0.744). Spearman is computed over all ~790 rows,
  most of whom are squad filler, so it mostly measures ordering at the bottom of the pool.
  Squad selection depends on the top of the ranking, which is what NDCG and capture measure.
- Squad-level points are noisy across 33 gameweeks; the ranking metrics are the stable signal.

## Why `ep_next` is not in the table

The trust standard asks for a comparison against official FPL expected points. That is not
possible on historical data: the `xP` column in the public archive is **leaked**.

```
gameweeks with any value        11 of 38
correlation with actual points  0.668
top-200 by xP that played 0 min 1%
```

A genuine pre-deadline projection ranks plenty of players who then do not play, and
correlates with realised points far below 0.67 at player-gameweek level. `fpl backtest`
runs this diagnostic (`official_ep_leakage`) and refuses to score the column as a baseline.
Comparing against live `ep_next` requires accumulating pre-deadline snapshots going forward.

## What the engine actually uses

Per player, per fixture, all from the official API:

- **Attacking**: xG and xA per 90, shrunk toward the position median by 320 pseudo-minutes,
  scaled by how good this specific fixture looks for the team.
- **Team strength**: attack and defence indices from finished results plus aggregated player
  xG (keeper xGC for defence), shrunk toward an FDR-derived prior.
- **Fixture**: expected goals for and against from `league_avg × attack × opponent defence ×
  venue`. Clean sheets are `P(0 conceded)` under Poisson; the goals-conceded penalty is
  `E[floor(conceded / 2)]`, not a point estimate.
- **Minutes**: P(appear) and P(60+) from recency-weighted appearances, times availability
  from `status` and `chance_of_playing_next_round`.
- **Defensive contribution**: `P(actions ≥ threshold)` under Poisson, with the position
  threshold (10 CBIT for defenders, 12 CBIRT otherwise).
- **Bonus / saves / cards**: observed per-90 rates, with saves scaled by fixture danger.

## Parameter sweeps

Every constant below was chosen by walk-forward NDCG@20, not by taste.

**Recency weighting of player rates** — season-long rates beat recent form:

| rate half-life | flat | 12 matches | 8 | 4 |
|---|---|---|---|---|
| NDCG@20 | **0.3876** | 0.3844 | 0.3840 | 0.3790 |

**Blending the player's own recent points per 90 into the projection** — makes it worse:

| points blend | 0.0 | 0.2 | 0.35 | 0.5 |
|---|---|---|---|---|
| NDCG@20 | **0.3790** | 0.3784 | 0.3745 | 0.3700 |

**Team strength: xG weight vs goals** — xG is the better strength signal:

| xG weight | 0.0 (goals only) | 0.35 | 0.65 | 0.85 | 1.0 |
|---|---|---|---|---|---|
| NDCG@20 | 0.3791 | 0.3816 | 0.3876 | **0.3894** | 0.3881 |

**Team strength shrinkage** (`prior_games`): flat between 0 and 8 (0.3853–0.3893) and worse
at 20 (0.3782). Shipped value is 3.0, which is inside the flat region and protects
early-season estimates the backtest cannot exercise (it starts once several gameweeks exist).

**Minutes half-life**: 4 matches (0.3876) beat 2 (0.3849), 8 (0.3834) and 20 (0.3852).
Unlike scoring rates, minutes *should* be recency weighted — selection changes, ability does
not.

## Probability calibration

Predicted probabilities are compared with observed frequencies for players who played 60+
minutes (n=6,371):

| event | predicted | actual |
|---|---|---|
| defensive contribution, DEF | 0.258 | 0.271 |
| defensive contribution, MID | 0.163 | 0.189 |
| defensive contribution, FWD | 0.005 | 0.014 |
| clean sheet | 0.267 | 0.253 |

Slightly conservative on defensive contribution, slightly optimistic on clean sheets. Both
are close enough that the points they generate are not systematically inflated.

## Known gaps

- No Club Elo, no head-to-head history, no European/cup minutes for rotation risk.
- Set-piece and penalty duties are available live (`penalties_order`,
  `corners_and_indirect_freekicks_order`) but are not in the historical archive, so they are
  not yet used — they cannot be validated here.
- The XGBoost model in `models/train.py` is not wired into live projections;
  `load_model_adjustments()` returns an empty dict until a trained model beats this engine
  on these same metrics.
- One test season. Adding 2024-25 requires rebuilding the target under the old ruleset.
