"""Compact weekly status for the FPL predictor. Run from the repo root after `fpl refresh`.

Prints only what the weekly update needs, so the agent does not read raw snapshots.
"""
import json
from collections import defaultdict
from datetime import datetime

from fpl_predictor.data.snapshots import load_current
from fpl_predictor.paths import snapshots_dir


def ts(raw):
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


snap = load_current()
r = snap.rules
cur, nxt = snap.current_event() or {}, snap.next_event() or {}
els = snap.players()
print(f"snapshot {snap.meta['pulled_at']}  GW{cur.get('id')} finished={cur.get('finished')}  "
      f"next GW{nxt.get('id')} deadline {nxt.get('deadline_time')}  pre-deadline={snap.is_pre_deadline(int(nxt.get('id') or 0))}")
print(f"players {len(els)}  histories {len(snap.histories)}  "
      f"injured {sum(e.get('status') == 'i' for e in els)}  doubtful {sum(e.get('status') == 'd' for e in els)}")
print(f"rules budget {r.budget / 10}m  squad {r.squad_size}/{r.squad_play}  club {r.team_limit}  "
      f"extra FT {r.max_extra_free_transfers}  hit {r.hit_cost}  sell fee {r.sell_on_fee}  cap {r.transfers_cap}")
print("chips " + ", ".join(f"{c.name} GW{c.start_event}-{c.stop_event}" for c in r.chips))

# Pre-deadline snapshots per gameweek: the live ep_next scorecard needs >= 10 finished GWs with one.
pre = defaultdict(int)
for meta_path in snapshots_dir().glob("*/meta.json"):
    meta = json.loads(meta_path.read_text())
    if meta.get("next_event") and meta.get("next_deadline") and ts(meta["pulled_at"]) < ts(meta["next_deadline"]):
        pre[int(meta["next_event"])] += 1
last_done = int(cur.get("id") or 0) - (0 if cur.get("finished") else 1)
done = [gw for gw in pre if gw <= last_done]
print(f"pre-deadline snapshots: GWs {sorted(pre)}  finished GWs covered {len(done)}/10")
