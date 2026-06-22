const API = "/api/v1";
const STATES = ["Maharashtra", "Tamil Nadu", "Karnataka", "Gujarat",
  "Telangana", "Haryana", "Andhra Pradesh", "Uttar Pradesh",
  "Rajasthan", "Madhya Pradesh", "Delhi NCR", "West Bengal"];

const data = { vendor_name: "", application_id: "", price_tier: "",
  min_deal_size_inr: null, geography: [] };
let step = 1;
const STEPS = [1, 2, 3, 4, "done"];

function $(s) { return document.querySelector(s); }
function $$(s) { return document.querySelectorAll(s); }

function show(stepKey) {
  $$(".step").forEach(el =>
    el.classList.toggle("hidden", el.dataset.step != String(stepKey)));
  const idx = STEPS.indexOf(stepKey);
  $("#progress-bar").style.width = `${(idx / (STEPS.length - 1)) * 100}%`;
  $("#btn-back").classList.toggle("hidden", idx === 0 || stepKey === "done");
  $("#btn-next").classList.toggle("hidden", stepKey === "done");
  $("#btn-next").textContent = stepKey === 4 ? "Finish →" : "Next →";
}

function err(msg) {
  const cur = $(`.step[data-step="${step}"] .step-err`);
  if (cur) { cur.textContent = msg; cur.classList.toggle("hidden", !msg); }
}

// ── load applications ──
async function loadApplications() {
  try {
    const apps = await fetch(API + "/applications").then(r => r.json());
    const sel = $("#f-application");
    sel.innerHTML = `<option value="">Select an application…</option>` +
      apps.map(a => `<option value="${a.id}">${a.application_name}` +
        `${a.category_name ? " — " + a.category_name : ""}</option>`).join("");
  } catch {
    $("#f-application").innerHTML = `<option value="">Failed to load</option>`;
  }
}

// ── geography chips ──
function buildGeo() {
  $("#geo-chips").innerHTML = STATES.map(s =>
    `<button type="button" class="geo-chip" data-state="${s}">${s}</button>`).join("");
  $$(".geo-chip").forEach(chip => chip.addEventListener("click", () => {
    chip.classList.toggle("on");
    const st = chip.dataset.state;
    if (chip.classList.contains("on")) data.geography.push(st);
    else data.geography = data.geography.filter(x => x !== st);
  }));
}

// ── tier cards ──
function buildTiers() {
  $$(".tier-opt").forEach(opt => opt.addEventListener("click", () => {
    $$(".tier-opt").forEach(o => o.classList.remove("on"));
    opt.classList.add("on");
    data.price_tier = opt.dataset.tier;
  }));
}

// ── validation per step ──
function validate() {
  err("");
  if (step === 1) {
    data.vendor_name = $("#f-vendor-name").value.trim();
    if (!data.vendor_name) return err("Please enter your company name."), false;
  }
  if (step === 2) {
    data.application_id = $("#f-application").value;
    if (!data.application_id) return err("Please select an application."), false;
  }
  if (step === 3) {
    if (!data.price_tier) return err("Please choose a tier."), false;
    const v = $("#f-deal-size").value;
    data.min_deal_size_inr = v ? parseInt(v, 10) : null;
  }
  if (step === 4) {
    if (!data.geography.length) return err("Pick at least one state."), false;
  }
  return true;
}

// ── submit ──
async function submitRegistration() {
  const res = await fetch(API + "/vendors/register", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vendor_name: data.vendor_name, application_id: data.application_id,
      price_tier: data.price_tier, geography: data.geography }),
  });
  if (!res.ok) throw new Error(await res.text());
  const out = await res.json();

  // Persist deal size via PATCH if provided.
  if (data.min_deal_size_inr) {
    await fetch(API + "/vendors/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "x-api-key": out.api_key },
      body: JSON.stringify({ min_deal_size_inr: data.min_deal_size_inr }),
    }).catch(() => {});
  }
  return out.api_key;
}

// ── nav ──
$("#btn-next").addEventListener("click", async () => {
  if (!validate()) return;
  if (step === 4) {
    $("#btn-next").textContent = "Creating…"; $("#btn-next").disabled = true;
    try {
      const key = await submitRegistration();
      $("#new-api-key").textContent = key;
      localStorage.setItem("fiq_api_key", key);  // auto sign-in
      step = "done"; show("done");
    } catch (e) {
      $("#btn-next").disabled = false; $("#btn-next").textContent = "Finish →";
      err("Registration failed: " + e.message);
    }
    return;
  }
  step = STEPS[STEPS.indexOf(step) + 1]; show(step);
});

$("#btn-back").addEventListener("click", () => {
  step = STEPS[STEPS.indexOf(step) - 1]; show(step);
});

$("#copy-key").addEventListener("click", () => {
  navigator.clipboard.writeText($("#new-api-key").textContent);
  $("#copy-key").textContent = "Copied!";
});

// ── boot ──
loadApplications(); buildGeo(); buildTiers(); show(1);
