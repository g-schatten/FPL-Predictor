from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    env = os.environ.get("FPL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def data_dir() -> Path:
    path = project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshots_dir() -> Path:
    path = data_dir() / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def current_pointer() -> Path:
    return data_dir() / "current"


def squads_dir() -> Path:
    path = data_dir() / "squads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def warehouse_dir() -> Path:
    path = data_dir() / "warehouse"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path
