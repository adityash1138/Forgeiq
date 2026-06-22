const API = "/api/v1/marketplace";
function $(s){return document.querySelector(s);}
function esc(x){return String(x??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
function fmtDate(iso){return iso?new Date(iso).toLocaleDateString("en-IN",{day:"numeric",month:"short",year:"numeric"}):"";}

const STATUS_PILL = { open:"COLD", matched:"WARM", proposals_in:"WARM", closed:"HOT" };

async function loadApps() {
  try {
    const apps = await fetch("/api/v1/applications").then(r=>r.json());
    $("#r-app").innerHTML = `<option value="">Any application</option>` +
      apps.map(a=>`<option value="${a.id}">${esc(a.application_name)}</option>`).join("");
  } catch {}
}

async function loadRFQs() {
  const box = $("#rfq-list");
  try {
    const rfqs = await fetch(API+"/rfqs").then(r=>r.json());
    if (!rfqs.length) { box.innerHTML = `<div class="empty">No RFQs yet — post the first one.</div>`; return; }
    box.innerHTML = rfqs.map(r=>`
      <div class="fb-row" data-rfq="${r.id}">
        <div>
          <div class="company-name">${esc(r.title)}</div>
          <div class="application-name">${esc(r.application_name||"Any")} ·
            ${esc(r.buyer_company||"—")} · ${fmtDate(r.created_at)}</div>
        </div>
        <div style="display:flex;align-items:center;gap:.6rem">
          <span class="subtle">${r.matches} matched · ${r.proposals} proposals</span>
          <span class="status-pill ${STATUS_PILL[r.status]||'COLD'}">${esc(r.status)}</span>
        </div></div>`).join("");
    box.querySelectorAll("[data-rfq]").forEach(el=>
      el.addEventListener("click",()=>openRFQ(el.dataset.rfq)));
  } catch(e){ box.innerHTML = `<div class="error">Failed: ${esc(e.message)}</div>`; }
}

async function openRFQ(id) {
  const body = $("#modal-body");
  body.innerHTML = `<p class="loading">Loading…</p>`;
  $("#modal-overlay").classList.remove("hidden");
  try {
    const d = await fetch(API+"/rfqs/"+id).then(r=>r.json());
    const r = d.rfq;
    const matches = (d.matches||[]).map(m=>`
      <div class="comp-item" style="border-left-color:var(--accent)">
        <div class="comp-top"><span class="comp-brand">${esc(m.vendor_name)}</span>
          <span class="comp-conf comp-medium">${m.match_score}</span></div>
        <div class="comp-meta">${esc(m.match_reason)}</div></div>`).join("");
    const proposals = (d.proposals||[]).map(p=>`
      <div class="comp-item" style="border-left-color:${p.status==='shortlisted'?'#22c55e':'var(--border)'}">
        <div class="comp-top"><span class="comp-brand">${esc(p.vendor_name)}</span>
          <span class="status-pill ${p.status==='shortlisted'?'HOT':'COLD'}">${esc(p.status)}</span></div>
        <div class="comp-meta">${esc(p.price_indication||"—")} ·
          ${p.lead_time_weeks?p.lead_time_weeks+"wk lead time":""}</div>
        <div class="tl-snippet">${esc(p.summary||"")}</div>
        ${r.status!=='closed'?`<button class="cfg-save shortlist" data-prop="${p.id}"
          style="margin-top:.5rem">Shortlist & close</button>`:""}
      </div>`).join("");
    body.innerHTML = `
      <h2>${esc(r.title)}</h2>
      <div class="app-label">${esc(r.application_name||"Any")} · ${esc(r.geography||"")}
        · ${esc(r.budget_range||"")}</div>
      <div class="why-text" style="margin:0.8rem 0">${esc(r.brief||"")}</div>
      ${r.status==='closed'?`<div class="exclusivity-bar">Closed · lead fee
        ₹${(r.lead_fee_inr||0).toLocaleString('en-IN')} charged</div>`:""}
      <div class="section-title">Matched Vendors (${d.matches.length})</div>${matches||'<p class="subtle">None</p>'}
      <div class="section-title">Proposals (${d.proposals.length})</div>${proposals||'<p class="subtle">No proposals yet.</p>'}`;
    body.querySelectorAll(".shortlist").forEach(b=>
      b.addEventListener("click",()=>shortlist(id,b.dataset.prop)));
  } catch(e){ body.innerHTML=`<p class="error">${esc(e.message)}</p>`; }
}

async function shortlist(rfqId, propId) {
  try {
    await fetch(`${API}/rfqs/${rfqId}/shortlist?proposal_id=${propId}`,{method:"POST"})
      .then(r=>{if(!r.ok)throw new Error("failed");});
    openRFQ(rfqId); loadRFQs();
  } catch(e){ alert("Shortlist failed: "+e.message); }
}

$("#toggle-form").addEventListener("click",()=>$("#rfq-form").classList.toggle("hidden"));
$("#r-submit").addEventListener("click",async()=>{
  const msg=$("#r-msg");
  const payload={title:$("#r-title").value.trim(),brief:$("#r-brief").value.trim(),
    application_id:$("#r-app").value||null,geography:$("#r-geo").value.trim()||null,
    budget_range:$("#r-budget").value.trim()||null,buyer_company:$("#r-company").value.trim()||null,
    buyer_email:$("#r-email").value.trim()||null};
  if(!payload.title){msg.textContent="Title required";msg.className="outcome-msg err";return;}
  try{
    const d=await fetch(API+"/rfqs",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)}).then(r=>r.json());
    msg.textContent=`✓ Posted — matched ${d.vendors_matched} vendor(s).`;msg.className="outcome-msg ok";
    $("#rfq-form").classList.add("hidden"); loadRFQs();
  }catch(e){msg.textContent="Failed: "+e.message;msg.className="outcome-msg err";}
});
$("#modal-close").addEventListener("click",()=>$("#modal-overlay").classList.add("hidden"));
$("#modal-overlay").addEventListener("click",e=>{if(e.target===$("#modal-overlay"))$("#modal-overlay").classList.add("hidden");});

loadApps(); loadRFQs();
