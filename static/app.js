const API = "/api/v1";
let apiKey = localStorage.getItem("fiq_api_key") || "";

// ── helpers ──────────────────────────────────────────────
function $$(id) { return document.getElementById(id); }

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { "x-api-key": apiKey, "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  if (res.status === 401 || res.status === 403) { logout(); return null; }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function statusClass(status) {
  if (status === "HOT") return "HOT";
  if (status === "WARM") return "WARM";
  return "COLD";
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// ── auth ─────────────────────────────────────────────────
async function tryLogin(key) {
  apiKey = key;
  try {
    const vendor = await apiFetch("/vendors/me");
    if (!vendor) return;
    localStorage.setItem("fiq_api_key", key);
    $$("vendor-name").textContent = vendor.vendor_name || "Vendor";
    showScreen("dashboard");
    loadLeads();
  } catch {
    $$("login-error").textContent = "Invalid API key. Please try again.";
    $$("login-error").classList.remove("hidden");
  }
}

function logout() {
  localStorage.removeItem("fiq_api_key");
  apiKey = "";
  showScreen("login");
}

// ── screens ───────────────────────────────────────────────
function showScreen(name) {
  $$("login-screen").classList.toggle("hidden", name !== "login");
  $$("dashboard-screen").classList.toggle("hidden", name !== "dashboard");
}

// ── leads ─────────────────────────────────────────────────
async function loadLeads() {
  const status = $$("filter-status").value;
  const city   = $$("filter-city").value.trim();

  let qs = "";
  if (status) qs += `status=${encodeURIComponent(status)}&`;
  if (city)   qs += `city=${encodeURIComponent(city)}&`;

  $$("leads-loading").classList.remove("hidden");
  $$("leads-empty").classList.add("hidden");
  $$("leads-error").classList.add("hidden");
  $$("leads-grid").classList.add("hidden");

  try {
    const leads = await apiFetch(`/leads${qs ? "?" + qs : ""}`);
    if (!leads) return;
    renderLeads(leads);
  } catch (e) {
    $$("leads-loading").classList.add("hidden");
    $$("leads-error").textContent = "Failed to load leads: " + e.message;
    $$("leads-error").classList.remove("hidden");
  }
}

function renderLeads(leads) {
  $$("leads-loading").classList.add("hidden");
  const grid = $$("leads-grid");
  grid.innerHTML = "";

  if (!leads.length) {
    $$("leads-empty").classList.remove("hidden");
    return;
  }

  leads.forEach(lead => {
    const sc = statusClass(lead.status);
    const card = document.createElement("div");
    card.className = "lead-card";
    card.innerHTML = `
      <div class="lead-card-top">
        <div>
          <div class="company-name">${esc(lead.company_name)}</div>
          <div class="application-name">${esc(lead.application_name || "—")}</div>
        </div>
        <div class="score-badge ${sc}">${Math.round(lead.current_score)}</div>
      </div>
      <div class="lead-meta">
        <span class="status-pill ${sc}">${lead.status}</span>
        ${lead.confidence_tier_shown ? `<span class="tier-pill">${esc(lead.confidence_tier_shown)}</span>` : ""}
        <span class="delivered-at">${fmtDate(lead.delivered_at)}</span>
      </div>
    `;
    card.addEventListener("click", () => openDetail(lead.score_id));
    grid.appendChild(card);
  });

  grid.classList.remove("hidden");
}

// ── detail modal ──────────────────────────────────────────
async function openDetail(scoreId) {
  const overlay = $$("modal-overlay");
  const body    = $$("modal-body");
  body.innerHTML = `<p class="loading">Loading…</p>`;
  overlay.classList.remove("hidden");

  try {
    const d = await apiFetch(`/leads/${scoreId}`);
    if (!d) return;
    const sc = statusClass(d.status);

    let contactsHtml = "";
    if (d.contacts && d.contacts.length) {
      contactsHtml = `
        <div class="section-title">Contacts</div>
        <div class="contacts-list">
          ${d.contacts.map(c => `
            <div class="contact-item">
              <div class="contact-name">${esc(c.full_name)}</div>
              <div class="contact-role">${esc(c.role || "")}</div>
              ${c.email_pattern_guess ? `<div class="contact-email">${esc(c.email_pattern_guess)}</div>` : ""}
            </div>
          `).join("")}
        </div>`;
    }

    let exclusivityHtml = "";
    if (d.exclusivity_window_end) {
      const end = new Date(d.exclusivity_window_end);
      const now = new Date();
      const hoursLeft = Math.max(0, Math.round((end - now) / 36e5));
      exclusivityHtml = `
        <div class="section-title">Exclusivity Window</div>
        <div class="exclusivity-bar">
          ${hoursLeft > 0
            ? `Expires in <span>${hoursLeft}h</span> (${fmtDate(d.exclusivity_window_end)})`
            : `Expired — ${fmtDate(d.exclusivity_window_end)}`}
        </div>`;
    }

    body.innerHTML = `
      <h2>${esc(d.company_name)}</h2>
      <div class="app-label">${esc(d.application_name || "—")}${
        d.plant_location ? " · " + esc(d.plant_location) : ""}</div>
      <div class="modal-score">
        <span class="big-score score-badge ${sc}">${Math.round(d.current_score)}</span>
        <span class="status-pill ${sc}">${d.status}</span>
        ${d.confidence_tier_shown ? `<span class="tier-pill">${esc(d.confidence_tier_shown)}</span>` : ""}
      </div>
      ${scoreBreakdownHtml(d.score_breakdown)}
      ${d.why_explanation ? `
        <div class="section-title">Why This Lead</div>
        <div class="why-text">${esc(d.why_explanation)}</div>` : ""}
      ${signalTimelineHtml(d.signal_timeline)}
      ${competitorHtml(d.competitor_intel)}
      ${exclusivityHtml}
      ${contactsHtml}
      <div class="action-row">
        <button class="btn-contacted" id="btn-contacted-${scoreId}">
          ✓ Mark as Contacted
        </button>
        <button class="btn-ghost" id="btn-outcome-${scoreId}">Log outcome…</button>
      </div>
      <div id="outcome-panel-${scoreId}" class="outcome-panel hidden"></div>
    `;

    document.getElementById(`btn-contacted-${scoreId}`)
      .addEventListener("click", () => markContacted(scoreId));
    document.getElementById(`btn-outcome-${scoreId}`)
      .addEventListener("click", () => toggleOutcomePanel(scoreId, d));

  } catch (e) {
    body.innerHTML = `<p class="error">Failed to load: ${esc(e.message)}</p>`;
  }
}

async function markContacted(scoreId) {
  const btn = document.getElementById(`btn-contacted-${scoreId}`);
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    await apiFetch(`/leads/${scoreId}/mark-contacted`, { method: "POST" });
    btn.textContent = "✓ Contacted";
  } catch {
    btn.disabled = false;
    btn.textContent = "✓ Mark as Contacted";
  }
}

// ── lead-detail section builders ──────────────────────────
function scoreBreakdownHtml(b) {
  if (!b) return "";
  const adjusted = b.negative_multiplier && b.negative_multiplier < 1;
  return `
    <div class="section-title">Score Breakdown</div>
    <div class="breakdown">
      <div class="bd-row"><span>Signal score (pre-adjustment)</span>
        <b>${b.pre_adjustment_score}</b></div>
      ${adjusted ? `
      <div class="bd-row neg"><span>Negative adjustment
        ${b.negative_flag ? "(" + esc(b.negative_flag) + ")" : ""}</span>
        <b>× ${b.negative_multiplier}</b></div>` : ""}
      <div class="bd-row total"><span>Final score</span>
        <b>${b.final_score}</b></div>
    </div>`;
}

function signalTimelineHtml(items) {
  if (!items || !items.length) return "";
  const rows = items.map(s => `
    <div class="tl-item">
      <div class="tl-dot tl-${(s.tier || "").toLowerCase()}"></div>
      <div class="tl-body">
        <div class="tl-top">
          <span class="tl-label">${esc(s.label)}</span>
          <span class="tl-tier">${esc(s.tier || "")}</span>
          ${s.contribution != null
            ? `<span class="tl-contrib">+${s.contribution} pts</span>` : ""}
        </div>
        <div class="tl-meta">${fmtDate(s.date_detected)}${
          s.source ? " · " + esc(s.source) : ""}${
          s.decay_position != null
            ? ` · ${Math.round(s.decay_position * 100)}% live` : ""}</div>
        ${s.snippet ? `<div class="tl-snippet">${esc(s.snippet)}</div>` : ""}
      </div>
    </div>`).join("");
  return `<div class="section-title">Signal Timeline</div>
          <div class="timeline">${rows}</div>`;
}

function competitorHtml(items) {
  if (!items || !items.length) return "";
  const rows = items.map(c => `
    <div class="comp-item">
      <div class="comp-top">
        <span class="comp-brand">${esc(c.competitor_brand || "Unknown")}</span>
        ${c.confidence ? `<span class="comp-conf comp-${c.confidence.toLowerCase()}">${esc(c.confidence)}</span>` : ""}
      </div>
      <div class="comp-meta">${esc(c.evidence_type || "")}${
        c.evidence_date ? " · " + fmtDate(c.evidence_date) : ""}</div>
      ${c.recommended_move ? `<div class="comp-move">→ ${esc(c.recommended_move)}</div>` : ""}
    </div>`).join("");
  return `<div class="section-title">Competitor Intel</div>
          <div class="competitors">${rows}</div>`;
}

// ── outcome feedback panel ────────────────────────────────
const OUTCOME_OPTIONS = [
  ["Won", "Deal won 🎉"], ["Contacted", "Contacted"],
  ["No response", "No response"], ["Lost-Competitor", "Lost to competitor"],
  ["Not-Relevant", "Not relevant"],
];

function toggleOutcomePanel(scoreId, d) {
  const panel = document.getElementById(`outcome-panel-${scoreId}`);
  if (!panel) return;
  if (!panel.classList.contains("hidden")) {
    panel.classList.add("hidden"); return;
  }
  panel.innerHTML = `
    <div class="section-title">Log an outcome</div>
    <div class="outcome-options">
      ${OUTCOME_OPTIONS.map(([v, label]) =>
        `<button class="outcome-opt" data-v="${v}">${label}</button>`).join("")}
    </div>
    <textarea id="outcome-reason-${scoreId}" class="outcome-reason"
      placeholder="Optional note (why won/lost)…"></textarea>
    <div id="outcome-msg-${scoreId}" class="outcome-msg"></div>`;
  panel.classList.remove("hidden");
  panel.querySelectorAll(".outcome-opt").forEach(btn =>
    btn.addEventListener("click", () => submitOutcome(scoreId, btn.dataset.v)));
}

async function submitOutcome(scoreId, status) {
  const reason = (document.getElementById(`outcome-reason-${scoreId}`) || {}).value || "";
  const msg = document.getElementById(`outcome-msg-${scoreId}`);
  try {
    await apiFetch(`/leads/${scoreId}/outcome`, {
      method: "POST",
      body: JSON.stringify({ outcome_status: status, reason_detail: reason }),
    });
    if (msg) { msg.textContent = "✓ Outcome recorded — thank you."; msg.className = "outcome-msg ok"; }
  } catch (e) {
    if (msg) { msg.textContent = "Failed: " + e.message; msg.className = "outcome-msg err"; }
  }
}

// ── escape helper ─────────────────────────────────────────
function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── event wiring ──────────────────────────────────────────
$$("login-form").addEventListener("submit", e => {
  e.preventDefault();
  $$("login-error").classList.add("hidden");
  tryLogin($$("api-key-input").value.trim());
});

$$("logout-btn").addEventListener("click", logout);
$$("filter-btn").addEventListener("click", loadLeads);
$$("filter-city").addEventListener("keydown", e => { if (e.key === "Enter") loadLeads(); });

$$("modal-close").addEventListener("click", () => {
  $$("modal-overlay").classList.add("hidden");
});
$$("modal-overlay").addEventListener("click", e => {
  if (e.target === $$("modal-overlay")) $$("modal-overlay").classList.add("hidden");
});

// ── boot ──────────────────────────────────────────────────
if (apiKey) {
  tryLogin(apiKey);
} else {
  showScreen("login");
}
