const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = { squads: [], mode: "entry" };

/* ---------- helpers ---------- */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const money = (value) => `£${Number(value).toFixed(1)}m`;
const pts = (value) => Number(value).toFixed(1);
const signed = (value) => `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(1)}`;
const span = (horizon) => (Number(horizon) === 1 ? "upcoming GW" : `next ${horizon} GW`);

function riskLabel(player) {
  if (player.status !== "a") {
    return player.availability < 100
      ? `${player.status_label} · ${player.availability}% fit`
      : player.status_label;
  }
  if ((player.flags || []).includes("minutes-risk")) return `${player.xmins} min expected`;
  if (player.availability < 100) return `${player.availability}% fit`;
  return "";
}

function deadlineText(iso) {
  if (!iso) return "unknown";
  const when = new Date(iso);
  return when.toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function agoText(iso) {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function showError(message) {
  const box = $("#error");
  box.textContent = message;
  box.hidden = !message;
  if (message) window.scrollTo({ top: 0, behavior: "smooth" });
}

function busy(on, text = "Working…") {
  $("#busy-text").textContent = text;
  $("#busy").hidden = !on;
}

async function callApi(path, body) {
  const options = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : { method: path.endsWith("refresh") ? "POST" : "GET" };
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(typeof detail === "string" ? detail : "Request failed. Check the terminal for details.");
  }
  return payload;
}

/* ---------- snapshot header ---------- */

function renderSnapshot(snapshot) {
  const pill = $("#snapshot-pill");
  if (!snapshot) {
    pill.className = "pill muted";
    pill.textContent = "No data yet — run a prediction to fetch it";
    return;
  }
  pill.className = "pill";
  pill.innerHTML = `<b>GW${esc(snapshot.next_gw ?? "?")}</b> deadline ${esc(deadlineText(snapshot.next_deadline))}
    &nbsp;·&nbsp; ${esc(snapshot.injured)} injured &nbsp;·&nbsp; data ${esc(agoText(snapshot.pulled_at))}`;
}

function renderSquadOptions() {
  const select = $("#tr-saved");
  if (!state.squads.length) {
    select.innerHTML = `<option value="">No saved squads yet</option>`;
    return;
  }
  select.innerHTML = state.squads
    .map((squad) => `<option value="${esc(squad.name)}">${esc(squad.name)} · bank ${money(squad.bank)}</option>`)
    .join("");
  if (state.mode === "saved") applySavedSquadDefaults();
}

function applySavedSquadDefaults() {
  const chosen = state.squads.find((squad) => squad.name === $("#tr-saved").value);
  if (!chosen) return;
  $("#tr-bank").value = chosen.bank.toFixed(1);
  $("#tr-ft").value = String(Math.min(5, Math.max(0, chosen.free_transfers)));
}

/* ---------- squad rendering ---------- */

function why(player) {
  const parts = [];
  const b = player.breakdown || {};
  const label = { goals: "goals", assists: "assists", clean_sheet: "clean sheet", saves: "saves", defensive_contribution: "defensive actions", bonus: "bonus", appearance: "appearance" };
  Object.entries(label).forEach(([key, text]) => {
    if ((b[key] || 0) >= 0.25) parts.push(`${text} ${pts(b[key])}`);
  });
  const head = player.opponents?.length ? `vs ${player.opponents.join(", ")}` : "";
  const cs = b.clean_sheet_odds !== undefined ? `clean sheet odds ${Math.round(b.clean_sheet_odds * 100)}%` : "";
  return [head, parts.join(", "), cs, player.news].filter(Boolean).join(" · ");
}

function playerCard(player) {
  const badge = player.captain
    ? `<span class="badge">C</span>`
    : player.vice
    ? `<span class="badge vice">V</span>`
    : player.bench_order
    ? `<span class="badge vice">${player.bench_order}</span>`
    : "";
  const risk = riskLabel(player);
  const fixture = player.opponents?.length ? player.opponents.join(", ") : "no fixture";
  return `
    <div class="player ${risk ? "risk" : ""}" title="${esc(why(player) || player.name)}">
      ${badge}
      <div class="name">${esc(player.name)}</div>
      <div class="meta">${esc(player.team)} · ${esc(player.position)} · ${money(player.cost)}</div>
      <div class="fixture">${esc(fixture)}</div>
      <div class="pts">${pts(player.xpts)} <span>xPts</span></div>
      ${risk ? `<div class="warn">${esc(risk)}</div>` : ""}
    </div>`;
}

function pitch(squad) {
  const lines = [1, 2, 3, 4].map((type) => {
    const row = squad.starters.filter((p) => p.element_type === type);
    return row.length ? `<div class="line">${row.map(playerCard).join("")}</div>` : "";
  });
  return `
    <div class="card">
      <div class="pitch">
        ${lines.join("")}
        <div class="bench">
          <div class="bench-label">Bench</div>
          <div class="line">${squad.bench.map(playerCard).join("")}</div>
        </div>
      </div>
    </div>`;
}

function statsStrip(items) {
  return `<div class="stats">${items
    .map(
      (item) => `<div class="stat">
        <div class="value ${item.tone || ""}">${esc(item.value)}</div>
        <div class="label">${esc(item.label)}</div>
      </div>`
    )
    .join("")}</div>`;
}

function trustNote(note) {
  return `
    <div class="callout trust">
      <h4>About this prediction</h4>
      Official FPL data pulled <b>${esc(agoText(note.pulled_at))}</b> for
      <b>GW${esc(note.gameweek ?? "?")}</b> (deadline ${esc(deadlineText(note.deadline))}).
      Solver returned <b>${esc(note.solver_status)}</b>, so the squad is legal:
      <ul>${note.legality.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      <div style="margin-top:10px">
        xPts are expected points for <b>${esc(note.span)}</b>, built from:
        <ul>${(note.basis || []).map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      </div>
      <div style="margin-top:8px">
        They are estimates, not guaranteed scores. ${esc(note.risk_line)}
      </div>
    </div>`;
}

function newsCard(snapshot) {
  if (!snapshot?.flagged?.length && !snapshot?.movers?.length) return "";
  const news = snapshot.flagged
    .map(
      (item) => `<div class="news-item">
        <span class="nm">${esc(item.name)} <span style="color:var(--faint)">${money(item.cost)}</span></span>
        <span class="nn">${esc(item.news || item.status_label)}</span>
      </div>`
    )
    .join("");
  const moves = snapshot.movers
    .map(
      (item) => `<div class="news-item">
        <span class="nm">${esc(item.name)} <span style="color:var(--faint)">${esc(item.team)}</span></span>
        <span class="nn" style="color:${item.delta > 0 ? "var(--accent)" : "var(--warn)"}">
          ${signed(item.delta)} → ${money(item.cost)}</span>
      </div>`
    )
    .join("");
  return `
    <div class="two-col">
      <div class="callout">
        <h4>Injury news in this data</h4>
        <div class="news-list">${news || "<span>No flagged players.</span>"}</div>
      </div>
      <div class="callout">
        <h4>Price moves this gameweek</h4>
        <div class="news-list">${moves || "<span>No price changes yet.</span>"}</div>
      </div>
    </div>`;
}

/* ---------- actions ---------- */

async function loadState() {
  try {
    const data = await callApi("/api/state");
    state.squads = data.squads || [];
    renderSnapshot(data.snapshot);
    renderSquadOptions();
  } catch (error) {
    showError(error.message);
  }
}

async function refreshData() {
  busy(true, "Fetching latest prices and injuries…");
  try {
    const data = await callApi("/api/refresh", {});
    state.squads = data.squads || [];
    renderSnapshot(data.snapshot);
    renderSquadOptions();
    showError("");
  } catch (error) {
    showError(error.message);
  } finally {
    busy(false);
  }
}

async function runWildcard() {
  busy(true, $("#wc-refresh").checked ? "Refreshing data, then solving…" : "Solving squad…");
  showError("");
  try {
    const data = await callApi("/api/wildcard", {
      horizon: Number($("#wc-horizon").value),
      budget: Number($("#wc-budget").value),
      refresh: $("#wc-refresh").checked,
    });
    renderSnapshot(data.snapshot);
    const plan = data.plan;
    $("#wc-empty").hidden = true;
    $("#wc-result").hidden = false;
    $("#wc-result").innerHTML = `
      ${statsStrip([
        { value: pts(plan.horizon_xpts), label: `${span(data.note.horizon)} xPts (XI + captain)`, tone: "good" },
        { value: money(plan.spend), label: "Squad cost" },
        { value: money(plan.bank), label: "Money left" },
        { value: plan.status, label: "Solver status" },
      ])}
      <div>
        <div class="section-title"><h2>Recommended squad</h2><span>C = captain, V = vice, bench numbered</span></div>
        ${pitch(plan)}
      </div>
      ${trustNote(data.note)}
      ${newsCard(data.snapshot)}`;
  } catch (error) {
    showError(error.message);
  } finally {
    busy(false);
  }
}

async function runTransfers() {
  const body = {
    horizon: Number($("#tr-horizon").value),
    max_hits: Number($("#tr-hits").value),
    bank: Number($("#tr-bank").value),
    free_transfers: Number($("#tr-ft").value),
    refresh: true,
  };

  if (state.mode === "entry") {
    const entry = Number($("#tr-entry").value);
    if (!entry) return showError("Enter your FPL manager ID first.");
    body.entry_id = entry;
  } else if (state.mode === "ids") {
    const ids = $("#tr-ids").value.split(/[^0-9]+/).filter(Boolean).map(Number);
    if (ids.length !== 15) return showError(`Need exactly 15 player IDs — got ${ids.length}.`);
    body.player_ids = ids;
  } else {
    const name = $("#tr-saved").value;
    if (!name) return showError("No saved squad yet. Use manager ID or player IDs first.");
    body.squad_name = name;
  }

  busy(true, "Reading your squad, then solving transfers…");
  showError("");
  try {
    const data = await callApi("/api/transfers", body);
    state.squads = data.squads || state.squads;
    renderSnapshot(data.snapshot);
    const result = data.result;
    const moves = result.moves.length
      ? `<div class="moves">${result.moves
          .map(
            (move) => `<div class="move">
              <div class="who out">
                <div class="n">${esc(move.out.name)}</div>
                <div class="s">${esc(move.out.team)} · ${esc(move.out.position)} · sell ${money(move.out.price)}</div>
              </div>
              <div class="arrow">→</div>
              <div class="who">
                <div class="n">${esc(move.in.name)}</div>
                <div class="s">${esc(move.in.team)} · ${esc(move.in.position)} · buy ${money(move.in.price)}</div>
              </div>
              <div class="gain">${signed(move.gain)} xPts</div>
            </div>`
          )
          .join("")}</div>`
      : `<div class="callout"><h4>Hold your squad</h4>No transfer beats doing nothing within your hit limit.</div>`;

    $("#tr-empty").hidden = true;
    $("#tr-result").hidden = false;
    $("#tr-result").innerHTML = `
      ${statsStrip([
        {
          value: signed(result.delta_vs_hold),
          label: "Net xPts vs doing nothing",
          tone: result.delta_vs_hold > 0 ? "good" : result.delta_vs_hold < 0 ? "bad" : "",
        },
        { value: result.hits ? `${result.hits} (−${result.hit_cost})` : "0", label: "Point hits taken" },
        { value: pts(result.squad.horizon_xpts), label: `${span(data.note.horizon)} xPts` },
        { value: money(result.bank), label: "Bank after moves" },
      ])}
      <div>
        <div class="section-title"><h2>Transfers</h2><span>keeping the current 15 scores ${esc(pts(result.hold_xpts))} xPts</span></div>
        ${moves}
      </div>
      <div>
        <div class="section-title"><h2>Squad after transfers</h2><span>C = captain, V = vice</span></div>
        ${pitch(result.squad)}
      </div>
      ${trustNote(data.note)}`;
  } catch (error) {
    showError(error.message);
  } finally {
    busy(false);
  }
}

/* ---------- wiring ---------- */

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((other) => other.classList.toggle("active", other === tab));
    $("#panel-wildcard").hidden = tab.dataset.tab !== "wildcard";
    $("#panel-transfers").hidden = tab.dataset.tab !== "transfers";
  });
});

$$(".seg").forEach((seg) => {
  seg.addEventListener("click", () => {
    state.mode = seg.dataset.mode;
    $$(".seg").forEach((other) => other.classList.toggle("active", other === seg));
    $$("[data-mode-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.modePanel !== state.mode;
    });
    if (state.mode === "saved") applySavedSquadDefaults();
  });
});

$("#tr-saved").addEventListener("change", applySavedSquadDefaults);
$("#refresh-btn").addEventListener("click", refreshData);
$("#wc-run").addEventListener("click", runWildcard);
$("#tr-run").addEventListener("click", runTransfers);

loadState();
