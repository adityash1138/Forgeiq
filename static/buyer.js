function $(s) { return document.querySelector(s); }
function esc(x) { return String(x ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

$("#b-submit").addEventListener("click", async () => {
  $("#b-error").classList.add("hidden");
  const email = $("#b-email").value.trim();
  const role = $("#b-role").value.trim();
  const cin = $("#b-cin").value.trim();
  if (!email || !role || !cin) {
    $("#b-error").textContent = "Please fill all fields.";
    $("#b-error").classList.remove("hidden"); return;
  }
  $("#b-submit").textContent = "Verifying…"; $("#b-submit").disabled = true;
  try {
    const res = await fetch("/api/v1/auth/buyer/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role, company_cin: cin }),
    });
    if (!res.ok) {
      const t = await res.json().catch(() => ({}));
      throw new Error(t.detail || "Verification failed");
    }
    const d = await res.json();
    renderBenchmark(d);
  } catch (e) {
    $("#b-submit").textContent = "Get my free benchmark"; $("#b-submit").disabled = false;
    $("#b-error").textContent = e.message; $("#b-error").classList.remove("hidden");
  }
});

function renderBenchmark(d) {
  $("#buyer-form").classList.add("hidden");
  const b = d.benchmark || {};
  const apps = (b.application_scores || []).map(a =>
    `<div class="bm-row"><span>${esc(a.application)}</span>
      <b>${Math.round(a.score)} · ${esc(a.status)}</b></div>`).join("");
  $("#buyer-result").classList.remove("hidden");
  $("#buyer-result").innerHTML = `
    <div class="benchmark">
      <div class="done-check" style="margin-bottom:1rem">✓</div>
      <h2 style="text-align:center;font-size:1.2rem">Verified — ${esc(d.company)}</h2>
      <p class="subtle" style="text-align:center;margin-bottom:1rem">
        Your corporate contact is now verified (highest confidence tier).</p>
      <div class="bm-row"><span>Your top expansion-intent score</span>
        <b>${Math.round(b.your_top_score)}</b></div>
      <div class="bm-row"><span>Sector average</span>
        <b>${b.sector_avg_score}</b></div>
      <div class="bm-row"><span>Companies tracked in sector</span>
        <b>${b.sector_companies_tracked}</b></div>
      <div class="bm-row"><span>Signals detected on your company</span>
        <b>${b.signals_detected_on_you}</b></div>
      ${apps ? `<div class="section-title" style="margin-top:1rem">By application</div>${apps}` : ""}
    </div>`;
}
