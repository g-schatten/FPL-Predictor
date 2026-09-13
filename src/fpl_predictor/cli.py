from __future__ import annotations

from typing import Optional

import typer

from fpl_predictor.data.rules import tenths
from fpl_predictor.data.snapshots import load_current, refresh_snapshot
from fpl_predictor.features.builder import build_projections, projections_frame
from fpl_predictor.models.predict import load_model_adjustments
from fpl_predictor.models.train import train_points_model
from fpl_predictor.optimize.transfers import solve_transfers
from fpl_predictor.optimize.wildcard import solve_wildcard
from fpl_predictor.render import console, print_saved_squad, print_snapshot, print_squad_plan, print_transfers
from fpl_predictor.squad.store import (
    import_public_entry,
    list_squads,
    load_squad,
    save_squad,
    squad_from_ids,
)

app = typer.Typer(help="Local FPL wildcard and transfer recommender. Refreshes official data on each solve.")
squad_app = typer.Typer(help="Save or inspect a local 15-man squad.")
app.add_typer(squad_app, name="squad")


def _refresh_if_needed(refresh: bool, full: bool):
    if refresh:
        snapshot = refresh_snapshot(full=full)
        print_snapshot(snapshot)
        return snapshot
    snapshot = load_current()
    console.print(f"Using snapshot from {snapshot.meta['pulled_at']}")
    return snapshot


def _parse_ids(raw: str) -> list[int]:
    parts = [p.strip() for p in raw.replace(" ", ",").split(",") if p.strip()]
    return [int(p) for p in parts]


@app.command()
def refresh(
    full: bool = typer.Option(False, help="Also pull per-player element-summary histories (slower)."),
) -> None:
    """Fetch the latest official FPL prices, injuries, fixtures, and rules."""
    snapshot = refresh_snapshot(full=full)
    print_snapshot(snapshot)
    console.print("Latest prices and injury flags are now stored locally.")


@app.command()
def status() -> None:
    """Show the current snapshot: deadline, price movers, injuries."""
    snapshot = load_current()
    print_snapshot(snapshot)
    movers = sorted(
        snapshot.players(),
        key=lambda p: abs(int(p.get("cost_change_event") or 0)),
        reverse=True,
    )
    shown = [p for p in movers if int(p.get("cost_change_event") or 0) != 0][:12]
    if shown:
        console.print("Biggest price moves this GW:")
        for player in shown:
            delta = int(player["cost_change_event"]) / 10
            console.print(
                f"  {delta:+.1f}  £{int(player['now_cost'])/10:.1f}  {player['web_name']}  {player.get('news') or ''}"
            )


@app.command()
def wildcard(
    horizon: int = typer.Option(4, min=1, max=8),
    budget: float = typer.Option(100.0, help="Budget in £m. Default is the official £100.0m."),
    refresh: bool = typer.Option(True, help="Refresh official FPL data before solving."),
    full: bool = typer.Option(False, help="Include per-player histories in the refresh."),
    csv: Optional[str] = typer.Option(None, help="Optional path to write the projection table."),
) -> None:
    """Build the best legal 15-man wildcard squad for the next gameweeks."""
    snapshot = _refresh_if_needed(refresh, full)
    projections = build_projections(snapshot, horizon=horizon, model_adjustments=load_model_adjustments())
    plan = solve_wildcard(projections, snapshot.rules, budget=tenths(budget))
    print_squad_plan(plan, title=f"Wildcard · next {horizon} GW · £{budget:.1f}m")
    if csv:
        projections_frame(projections).to_csv(csv, index=False)
        console.print(f"Wrote projections to {csv}")


@app.command()
def transfers(
    name: str = typer.Option("default", help="Saved squad name."),
    horizon: int = typer.Option(4, min=1, max=8),
    max_hits: int = typer.Option(1, min=0, max=5),
    refresh: bool = typer.Option(True),
    full: bool = typer.Option(False),
) -> None:
    """Recommend the best legal transfers from a saved local squad."""
    snapshot = _refresh_if_needed(refresh, full)
    squad = load_squad(name)
    projections = build_projections(snapshot, horizon=horizon, model_adjustments=load_model_adjustments())
    plan = solve_transfers(projections, snapshot.rules, squad, max_hits=max_hits)
    print_transfers(plan)


@app.command()
def train(
    download: bool = typer.Option(True, help="Download vaastav historical merged_gw files first."),
) -> None:
    """Train a leakage-safe points model on historical GWs and report walk-forward metrics."""
    report = train_points_model(download=download)
    console.print(report)
    if report.get("beats_form_baseline"):
        console.print("[green]Trained model beats last-3-GW form on NDCG@10.[/green]")
    else:
        console.print("[yellow]Trained model did not beat the form baseline. Live engine stays primary.[/yellow]")


@squad_app.command("save")
def squad_save(
    ids: str = typer.Option(..., help="15 FPL element ids, comma-separated."),
    bank: float = typer.Option(0.0, help="Money in the bank, in £m (e.g. 0.5)."),
    ft: int = typer.Option(1, help="Free transfers available."),
    name: str = typer.Option("default"),
    purchase: Optional[str] = typer.Option(
        None,
        help="Optional purchase prices in £m aligned with ids, e.g. 4.5,6.5,...",
    ),
) -> None:
    """Store your current 15, bank, and free transfers locally."""
    snapshot = load_current()
    player_ids = _parse_ids(ids)
    purchase_prices = None
    if purchase:
        values = [float(x) for x in purchase.split(",") if x.strip()]
        if len(values) != len(player_ids):
            raise typer.BadParameter("purchase list must match the number of ids.")
        purchase_prices = {pid: tenths(val) for pid, val in zip(player_ids, values)}
    squad = squad_from_ids(
        name=name,
        player_ids=player_ids,
        snapshot=snapshot,
        bank=bank,
        free_transfers=ft,
        purchase_prices=purchase_prices,
    )
    path = save_squad(squad)
    console.print(f"Saved {name} → {path}")
    print_saved_squad(squad, snapshot)


@squad_app.command("import-entry")
def squad_import(
    entry_id: int = typer.Argument(..., help="Public FPL manager id."),
    bank: float = typer.Option(..., help="Bank in £m. Not available on the public picks endpoint."),
    ft: int = typer.Option(1),
    name: str = typer.Option("default"),
) -> None:
    """Import a public 15 from a manager id. You still supply bank and free transfers."""
    snapshot = load_current()
    squad = import_public_entry(entry_id, snapshot, name=name, bank=bank, free_transfers=ft)
    path = save_squad(squad)
    console.print(f"Imported entry {entry_id} → {path}")
    print_saved_squad(squad, snapshot)


@squad_app.command("show")
def squad_show(name: str = typer.Option("default")) -> None:
    snapshot = load_current()
    squad = load_squad(name)
    print_saved_squad(squad, snapshot)


@squad_app.command("list")
def squad_list() -> None:
    names = list_squads()
    if not names:
        console.print("No saved squads.")
        return
    for name in names:
        console.print(name)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
