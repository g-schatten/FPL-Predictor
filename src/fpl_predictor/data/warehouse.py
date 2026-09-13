from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd

from fpl_predictor.data.fpl_api import USER_AGENT
from fpl_predictor.paths import warehouse_dir

VAASTAV_SEASONS = ("2022-23", "2023-24", "2024-25", "2025-26")
RAW_BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"


def download_vaastav_merged(seasons: tuple[str, ...] = VAASTAV_SEASONS) -> Path:
    dest = warehouse_dir()
    frames: list[pd.DataFrame] = []
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for season in seasons:
            url = f"{RAW_BASE}/{season}/gws/merged_gw.csv"
            response = client.get(url)
            response.raise_for_status()
            csv_path = dest / f"merged_gw_{season}.csv"
            csv_path.write_bytes(response.content)
            frame = pd.read_csv(csv_path)
            frame["season"] = season
            frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "player_gw.parquet"
    combined.to_parquet(out, index=False)
    return out


def load_player_gw() -> pd.DataFrame:
    path = warehouse_dir() / "player_gw.parquet"
    if not path.exists():
        raise FileNotFoundError("No warehouse yet. Run `fpl train --download` first.")
    return pd.read_parquet(path)
