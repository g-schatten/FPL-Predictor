from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fpl_predictor.data.rules import tenths
from fpl_predictor.data.snapshots import Snapshot, load_current, refresh_snapshot
from fpl_predictor.explain import build_trust_note
from fpl_predictor.features.builder import build_projections
from fpl_predictor.models.predict import load_model_adjustments
from fpl_predictor.optimize.transfers import solve_transfers
from fpl_predictor.optimize.wildcard import solve_wildcard
from fpl_predictor.squad.store import (
    import_public_entry,
    list_squads,
    load_squad,
    save_squad,
    squad_from_ids,
)
from fpl_predictor.web.serialize import (
    note_json,
    plan_json,
    snapshot_json,
    squad_json,
    transfer_plan_json,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="FPL Predictor", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class WildcardRequest(BaseModel):
    horizon: int = Field(1, ge=1, le=8)
    budget: float = Field(100.0, gt=0, le=200)
    refresh: bool = True


class TransferRequest(BaseModel):
    horizon: int = Field(1, ge=1, le=8)
    max_hits: int = Field(1, ge=0, le=5)
    bank: float = Field(0.0, ge=0, le=100)
    free_transfers: int = Field(1, ge=0, le=5)
    refresh: bool = True
    entry_id: int | None = None
    player_ids: list[int] | None = None
    squad_name: str | None = None
    save_as: str = "web"


def _snapshot(refresh: bool) -> Snapshot:
    if refresh:
        return refresh_snapshot()
    try:
        return load_current()
    except FileNotFoundError:
        return refresh_snapshot()


def _saved_squads(snapshot: Snapshot) -> list[dict[str, Any]]:
    saved = []
    for name in list_squads():
        try:
            saved.append(squad_json(load_squad(name), snapshot))
        except (ValueError, KeyError, OSError):
            continue
    return saved


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/state")
def state() -> dict[str, Any]:
    try:
        snapshot = load_current()
    except FileNotFoundError:
        return {"snapshot": None, "squads": []}
    return {"snapshot": snapshot_json(snapshot), "squads": _saved_squads(snapshot)}


@app.post("/api/refresh")
def refresh() -> dict[str, Any]:
    snapshot = refresh_snapshot()
    return {"snapshot": snapshot_json(snapshot), "squads": _saved_squads(snapshot)}


@app.post("/api/wildcard")
def wildcard(request: WildcardRequest) -> dict[str, Any]:
    snapshot = _snapshot(request.refresh)
    projections = build_projections(
        snapshot, horizon=request.horizon, model_adjustments=load_model_adjustments()
    )
    try:
        plan = solve_wildcard(projections, snapshot.rules, budget=tenths(request.budget))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "snapshot": snapshot_json(snapshot),
        "plan": plan_json(plan),
        "note": note_json(build_trust_note(snapshot, plan, horizon=request.horizon)),
    }


@app.post("/api/transfers")
def transfers(request: TransferRequest) -> dict[str, Any]:
    snapshot = _snapshot(request.refresh)

    try:
        if request.player_ids:
            squad = squad_from_ids(
                name=request.save_as,
                player_ids=request.player_ids,
                snapshot=snapshot,
                bank=request.bank,
                free_transfers=request.free_transfers,
            )
            save_squad(squad)
        elif request.entry_id:
            squad = import_public_entry(
                request.entry_id,
                snapshot,
                name=request.save_as,
                bank=request.bank,
                free_transfers=request.free_transfers,
            )
            save_squad(squad)
        elif request.squad_name:
            squad = load_squad(request.squad_name)
            squad.bank = request.bank
            squad.free_transfers = request.free_transfers
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide an FPL manager id, 15 player ids, or a saved squad name.",
            )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Could not read that squad from FPL: {exc}") from exc

    projections = build_projections(
        snapshot, horizon=request.horizon, model_adjustments=load_model_adjustments()
    )
    try:
        plan = solve_transfers(
            projections, snapshot.rules, squad, max_hits=request.max_hits
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "snapshot": snapshot_json(snapshot),
        "squads": _saved_squads(snapshot),
        "squad": squad_json(squad, snapshot),
        "result": transfer_plan_json(plan),
        "note": note_json(build_trust_note(snapshot, plan.wildcard, horizon=request.horizon)),
    }
