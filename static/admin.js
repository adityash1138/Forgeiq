const API = "/api/v1/admin";
let adminKey = localStorage.getItem("fiq_admin_key") || "";

function $(s) { return document.querySelector(s); }
function esc(x) { return String(x ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function fmt(iso) { return iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—"; }
function pill(v) { return `<span class="pill ${esc(v)}">${esc(v ?? "—")}</span>`; }

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { "x-admin-key": adminKey, "Content-Type": "application/json", ...(opts.headers||{}) },
  });
  if (res.status === 401 || res.status === 503) { logout(); throw new Error("auth"); }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── auth ──
async function tryLogin(key) {
  adminKey = key;
  try {
    await api("/stats");
    localStorage.setItem("fiq_admin_key", key);
    $("#admin-login").classList.add("hidden");
    $("#admin-console").classList.remove("hidden");
    render("overview");
  } catch {
    $("#admin-login-error").textContent = "Invalid admin key (or ADMIN_API_KEY not set).";
    $("#admin-login-error").classList.remove("hidden");
  }
}
function logout() {
  localStorage.removeItem("fiq_admin_key"); adminKey = "";
  $("#admin-console").classList.add("hidden");
  $("#admin-login").classList.remove("hidden");
}

// ── table helper ──
function table(rows, cols) {
  if (!rows || !rows.length) return `<p class="subtle">No rows.</p>`;
  const head = cols.map(c => `<th>${esc(c.label)}</th>`).join("");
  const body = rows.map(r => "<tr>" + cols.map(c =>
    `<td>${c.render ? c.render(r) : esc(r[c.key])}</td>`).join("") + "</tr>").join("");
  return `<div style="overflow:auto"><table class="admin-table">
    <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

// ── views ──
const VIEWS = {
  overview: { title: "Overview", run: async () => {
    const s = await api("/stats");
    const cards = [
      ["companies","Companies"],["raw_signals","Signals"],
      ["signals_unresolved","Unresolved"],["scores","Scores"],
      ["hot_scores","Hot","hot"],["warm_scores","Warm","warm"],
      ["vendors","Vendors"],["leads_delivered","Leads Delivered"],
      ["entity_queue_active","Queue Active"],["outcomes","Outcomes"],
    ];
    return `<div class="stat-grid">${cards.map(([k,l,cls]) =>
      `<div class="stat-card ${cls||""}"><div class="num">${s[k]}</div>
       <div class="lbl">${l}</div></div>`).join("")}</div>`;
  }},

  scrapers: { title: "Scraper Health", run: async () => {
    const rows = await api("/scrapers");
    return table(rows, [
      { label: "Job", key: "job_name" },
      { label: "Status", render: r => pill(r.status) },
      { label: "Last run", render: r => fmt(r.finished_at) },
      { label: "Error", render: r => `<span class="subtle">${esc(r.error || "—")}</span>` },
    ]);
  }},

  "entity-queue": { title: "Entity Resolution Queue", run: async () => {
    const d = await api("/entity-queue");
    const tb = Object.entries(d.tier_breakdown || {}).map(([t,n]) =>
      `${pill(t)} ${n}`).join("  ");
    return `<p class="subtle" style="margin-bottom:.8rem">Tier breakdown (resolved signals): ${tb || "none"}</p>` +
      table(d.queue, [
        { label: "Raw name", key: "raw_company_name" },
        { label: "Best guess", render: r => esc(r.best_guess_name || "—") },
        { label: "Conf%", key: "confidence_pct" },
        { label: "Days", key: "days_in_queue" },
        { label: "Status", render: r => pill(r.status) },
        { label: "Notes", render: r => `<span class="subtle">${esc(r.resolution_notes||"—")}</span>` },
      ]);
  }},

  scores: { title: "Scoring Runs", run: async () => {
    const rows = await api("/scores");
    return table(rows, [
      { label: "Company", key: "company_name" },
      { label: "Application", key: "application_name" },
      { label: "Score", render: r => Number(r.current_score).toFixed(1) },
      { label: "Status", render: r => pill(r.status) },
      { label: "Neg ×", key: "negative_multiplier" },
      { label: "Calculated", render: r => fmt(r.last_calculated_at) },
    ]);
  }},

  "signal-config": { title: "Signal Type Config", run: async () => {
    const rows = await api("/signal-config");
    return `<p class="subtle" style="margin-bottom:.8rem">Edit tier weight / base strength inline — saves without a deploy.</p>` +
      table(rows, [
        { label: "Signal", key: "signal_type" },
        { label: "Tier", render: r => pill(r.tier) },
        { label: "Weight", render: r => `<input class="cfg-input" id="w-${r.signal_type}" value="${r.tier_weight}">` },
        { label: "Strength", render: r => `<input class="cfg-input" id="s-${r.signal_type}" value="${r.base_strength}">` },
        { label: "Decay", key: "decay_curve" },
        { label: "Trigger", key: "is_cascade_trigger" },
        { label: "", render: r => `<button class="cfg-save" data-sig="${r.signal_type}">Save</button>` },
      ]);
  }, after: () => {
    document.querySelectorAll(".cfg-save").forEach(b => b.addEventListener("click", async () => {
      const sig = b.dataset.sig;
      b.textContent = "…";
      try {
        await api(`/signal-config/${sig}`, { method: "PATCH", body: JSON.stringify({
          tier_weight: parseFloat($(`#w-${sig}`).value),
          base_strength: parseInt($(`#s-${sig}`).value, 10) }) });
        b.textContent = "Saved ✓";
      } catch { b.textContent = "Error"; }
    }));
  }},

  "cascade-config": { title: "Cascade Wave Config", run: async () => {
    const rows = await api("/cascade-config");
    return table(rows, [
      { label: "Trigger", key: "trigger_signal_type" },
      { label: "Application", key: "application_name" },
      { label: "Wave", key: "wave_order" },
      { label: "Months", render: r => `${r.activate_month_start}–${r.activate_month_end}` },
      { label: "Confirming", render: r => esc((r.confirming_signal_types||[]).join(", ")) },
    ]);
  }},

  outcomes: { title: "Outcomes (Calibration)", run: async () => {
    const d = await api("/outcomes");
    const bd = Object.entries(d.breakdown||{}).map(([k,n]) => `${pill(k)} ${n}`).join("  ");
    return `<p class="subtle" style="margin-bottom:.8rem">${bd || "No outcomes yet."}</p>` +
      table(d.outcomes, [
        { label: "Status", render: r => pill(r.outcome_status) },
        { label: "Vendor", key: "vendor_name" },
        { label: "Company", key: "company_name" },
        { label: "Reason", render: r => `<span class="subtle">${esc(r.reason_detail||"—")}</span>` },
        { label: "Via", key: "captured_via" },
        { label: "When", render: r => fmt(r.captured_at) },
      ]);
  }},

  vendors: { title: "Vendor Management", run: async () => {
    const rows = await api("/vendors");
    return table(rows, [
      { label: "Vendor", key: "vendor_name" },
      { label: "Tier", render: r => pill(r.price_tier) },
      { label: "Application", key: "application_name" },
      { label: "Geography", render: r => esc((r.geography||[]).join(", ")) },
      { label: "Leads", key: "leads_delivered" },
      { label: "API key", render: r => `<span class="mono">${esc(r.api_key||"—")}</span>` },
    ]);
  }},

  deliveries: { title: "Lead Delivery Audit", run: async () => {
    const rows = await api("/deliveries");
    return table(rows, [
      { label: "Company", key: "company_name" },
      { label: "Vendor", key: "vendor_name" },
      { label: "Score", render: r => Number(r.current_score).toFixed(1) },
      { label: "Tier shown", render: r => pill(r.confidence_tier_shown) },
      { label: "Spotcheck", render: r => r.human_spotcheck_done ? "✓" : "pending" },
      { label: "Outcome", render: r => r.latest_outcome ? pill(r.latest_outcome) : "—" },
      { label: "Delivered", render: r => fmt(r.delivered_at) },
    ]);
  }},

  companies: { title: "Company / Entity Browser", run: async () => {
    const rows = await api("/companies");
    return `<div class="table-tools">
      <input id="co-search" placeholder="Search name or CIN…">
      </div><div id="co-results">${table(rows, COMPANY_COLS)}</div>`;
  }, after: () => {
    const inp = $("#co-search");
    if (inp) inp.addEventListener("keydown", async e => {
      if (e.key !== "Enter") return;
      const rows = await api("/companies?q=" + encodeURIComponent(inp.value));
      $("#co-results").innerHTML = table(rows, COMPANY_COLS);
    });
  }},

  jobs: { title: "Job Scheduler Log", run: async () => {
    const rows = await api("/jobs");
    return table(rows, [
      { label: "Job", key: "job_name" },
      { label: "Status", render: r => pill(r.status) },
      { label: "Started", render: r => fmt(r.started_at) },
      { label: "Finished", render: r => fmt(r.finished_at) },
      { label: "Error", render: r => `<span class="subtle">${esc(r.error||"—")}</span>` },
    ]);
  }},
};

const COMPANY_COLS = [
  { label: "Company", key: "legal_name" },
  { label: "CIN", render: r => `<span class="mono">${esc(r.cin||"—")}</span>` },
  { label: "Location", key: "plant_location" },
  { label: "Neg flag", render: r => r.negative_flag && r.negative_flag !== "None" ? pill(r.negative_flag) : "—" },
  { label: "Signals", key: "signal_count" },
  { label: "Scores", key: "score_count" },
];

async function render(view) {
  document.querySelectorAll("#admin-nav a").forEach(a =>
    a.classList.toggle("active", a.dataset.view === view));
  const v = VIEWS[view]; if (!v) return;
  $("#admin-view-title").textContent = v.title;
  $("#admin-content").innerHTML = `<div class="loading">Loading…</div>`;
  try {
    $("#admin-content").innerHTML = await v.run();
    if (v.after) v.after();
  } catch (e) {
    if (e.message !== "auth")
      $("#admin-content").innerHTML = `<p class="error">Failed: ${esc(e.message)}</p>`;
  }
}

// ── wiring ──
$("#admin-login-form").addEventListener("submit", e => {
  e.preventDefault(); $("#admin-login-error").classList.add("hidden");
  tryLogin($("#admin-key-input").value.trim());
});
$("#admin-logout").addEventListener("click", logout);
document.querySelectorAll("#admin-nav a").forEach(a =>
  a.addEventListener("click", () => render(a.dataset.view)));

if (adminKey) tryLogin(adminKey);
