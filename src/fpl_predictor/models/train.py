from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, ndcg_score
from xgboost import XGBRegressor

from fpl_predictor.data.warehouse import download_vaastav_merged, load_player_gw
from fpl_predictor.features.leakage import FORBIDDEN_SAME_GW, assert_no_leakage
from fpl_predictor.paths import models_dir

FEATURE_COLS = [
    "minutes_roll3",
    "points_roll3",
    "points_roll5",
    "was_home",
    "value",
    "element_type",
    "xg_roll3",
    "xa_roll3",
]


def _num(frame: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce").fillna(default)


def engineer(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    frame["element"] = _num(frame, "element").astype(int)
    frame["GW"] = _num(frame, "GW" if "GW" in frame.columns else "round").astype(int)
    frame["total_points"] = _num(frame, "total_points")
    frame["minutes"] = _num(frame, "minutes")
    frame["value"] = _num(frame, "value")
    frame["was_home"] = _num(frame, "was_home")
    frame["element_type"] = _num(frame, "element_type", 3)
    frame["expected_goals"] = _num(frame, "expected_goals")
    frame["expected_assists"] = _num(frame, "expected_assists")
    frame = frame.sort_values(["season", "element", "GW"])
    grouped = frame.groupby(["season", "element"], sort=False)
    frame["minutes_roll3"] = grouped["minutes"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    frame["points_roll3"] = grouped["total_points"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    frame["points_roll5"] = grouped["total_points"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    frame["xg_roll3"] = grouped["expected_goals"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    frame["xa_roll3"] = grouped["expected_assists"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    frame["ep_next_raw"] = _num(frame, "xP") if "xP" in frame.columns else _num(frame, "ep_next", -1)
    # vaastav xP is leak-prone — do not use it as a feature.
    frame = frame.dropna(subset=FEATURE_COLS + ["total_points"])
    assert_no_leakage(FEATURE_COLS)
    leaked = FORBIDDEN_SAME_GW.intersection(FEATURE_COLS)
    if leaked:
        raise AssertionError(leaked)
    return frame


def _ndcg_by_gw(y_true: np.ndarray, y_pred: np.ndarray, groups: np.ndarray, k: int = 10) -> float:
    scores = []
    for gw in np.unique(groups):
        mask = groups == gw
        if mask.sum() < k:
            continue
        truth = y_true[mask].reshape(1, -1)
        pred = y_pred[mask].reshape(1, -1)
        scores.append(ndcg_score(truth, pred, k=k))
    return float(np.mean(scores)) if scores else float("nan")


def train_points_model(*, download: bool = False, seasons: tuple[str, ...] | None = None) -> dict:
    if download or not (models_dir().parent / "warehouse" / "player_gw.parquet").exists():
        download_vaastav_merged(seasons or ("2023-24", "2024-25", "2025-26"))
    raw = load_player_gw()
    frame = engineer(raw)
    last_season = sorted(frame["season"].unique())[-1]
    train = frame[frame["season"] != last_season]
    test = frame[frame["season"] == last_season]
    if train.empty or test.empty:
        train = frame.iloc[: int(len(frame) * 0.8)]
        test = frame.iloc[int(len(frame) * 0.8) :]

    model = XGBRegressor(
        n_estimators=250,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="reg:squarederror",
        n_jobs=-1,
        random_state=42,
    )
    model.fit(train[FEATURE_COLS], train["total_points"])
    pred = model.predict(test[FEATURE_COLS])
    mae = float(mean_absolute_error(test["total_points"], pred))
    groups = test["GW"].to_numpy()
    ndcg = _ndcg_by_gw(test["total_points"].to_numpy(), pred, groups)
    baseline = test["points_roll3"].to_numpy()
    base_ndcg = _ndcg_by_gw(test["total_points"].to_numpy(), baseline, groups)
    artifact = models_dir() / "points.json"
    model.get_booster().save_model(str(models_dir() / "points.ubj"))
    report = {
        "mae": mae,
        "ndcg@10": ndcg,
        "baseline_roll3_ndcg@10": base_ndcg,
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "test_season": str(last_season),
        "features": FEATURE_COLS,
        "beats_form_baseline": bool(ndcg > base_ndcg) if ndcg == ndcg else False,
    }
    artifact.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def model_exists() -> bool:
    return (models_dir() / "points.ubj").exists()


def load_booster() -> XGBRegressor | None:
    path = models_dir() / "points.ubj"
    if not path.exists():
        return None
    model = XGBRegressor()
    model.load_model(str(path))
    return model
