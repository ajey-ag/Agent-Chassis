/* Agent Chassis dashboard — vanilla JS, no build step. */
const $ = (id) => document.getElementById(id);
let token = localStorage.getItem("token") || "";
let ws = null;

const api = async (path, opts = {}) => {
  const resp = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token, ...(opts.headers || {}) },
  });
  if (resp.status === 401) { showLogin(); throw new Error("unauthorized"); }
  if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
  return resp.json();
};

/* ---------- login ---------- */
function showLogin() { $("login").classList.remove("hidden"); $("main").classList.add("hidden"); }
function showMain() { $("login").classList.add("hidden"); $("main").classList.remove("hidden"); connectWs(); refreshAll(); }

$("loginBtn").onclick = async () => {
  try {
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("password").value }) });
    if (!r.ok) throw new Error((await r.json()).detail);
    token = (await r.json()).token;
    localStorage.setItem("token", token);
    showMain();
  } catch (e) { $("loginErr").textContent = e.message; }
};
$("password").addEventListener("keydown", (e) => e.key === "Enter" && $("loginBtn").click());

/* ---------- tabs ---------- */
document.querySelectorAll("nav button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("nav button").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.add("hidden"));
    b.classList.add("active");
    $("tab-" + b.dataset.tab).classList.remove("hidden");
    if (b.dataset.tab === "runs") loadRuns();
    if (b.dataset.tab === "approvals") loadApprovals();
    if (b.dataset.tab === "settings") loadSettings();
  };
});

/* ---------- websocket trace ---------- */
function connectWs() {
  if (ws) ws.close();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/trace?token=${encodeURIComponent(token)}`);
  ws.onopen = () => { $("wsStatus").textContent = "live"; $("wsStatus").className = "pill ok"; };
  ws.onclose = () => { $("wsStatus").textContent = "disconnected"; $("wsStatus").className = "pill bad";
    setTimeout(connectWs, 3000); };
  ws.onmessage = (m) => addTraceEvent(JSON.parse(m.data));
  setInterval(() => ws && ws.readyState === 1 && ws.send("ping"), 25000);
}

function addTraceEvent(ev) {
  const el = document.createElement("div");
  el.className = "ev " + ev.kind + (ev.prominent ? " prominent" : "");
  const { ts, kind, raw, ...rest } = ev;
  el.textContent = `[${new Date(ts * 1000).toLocaleTimeString()}] ${kind}  ${JSON.stringify(rest, null, 1)}`;
  const box = $("trace");
  box.appendChild(el);
  while (box.children.length > 500) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
  if (["approval_queued", "approval_executed", "approval_denied"].includes(kind)) loadApprovals();
  if (["run_finished", "run_started"].includes(kind)) loadRuns();
}

/* ---------- task submission ---------- */
$("submitTask").onclick = async () => {
  const task = $("taskInput").value.trim();
  if (!task) return;
  try {
    const r = await api("/api/tasks", { method: "POST", body: JSON.stringify({ task }) });
    $("taskMsg").textContent = "Started " + r.run_id + " — watch the Live Trace tab.";
    $("taskInput").value = "";
  } catch (e) { $("taskMsg").textContent = "Error: " + e.message; }
};

/* ---------- runs ---------- */
async function loadRuns() {
  try {
    const runs = await api("/api/tasks");
    $("runs").innerHTML = runs.length ? "" : "<p class='muted'>No runs yet.</p>";
    for (const r of runs) {
      const d = document.createElement("div");
      d.className = "run";
      d.innerHTML = `<span class="status ${r.status}">${r.status}</span> <b>${esc(r.task)}</b>
        <p class="muted">${r.id} · ${r.iterations ?? "…"} iterations${(r.pending_approvals||[]).length ? " · ⏳ " + r.pending_approvals.length + " pending approval(s)" : ""}</p>
        <p>${esc((r.final_answer || "").slice(0, 800))}</p>`;
      $("runs").appendChild(d);
    }
  } catch {}
}

/* ---------- approvals ---------- */
async function loadApprovals() {
  try {
    const items = await api("/api/approvals");
    $("apCount").textContent = items.length;
    $("apCount").classList.toggle("hidden", !items.length);
    $("approvals").innerHTML = items.length ? "" : "<p class='muted'>Nothing pending. 🎉</p>";
    for (const a of items) {
      const d = document.createElement("div");
      d.className = "approval";
      d.innerHTML = `<span class="status ${a.status}">${a.status}</span> <b>${esc(a.tool)}</b>
        <p class="muted">run ${a.run_id} · task: ${esc(a.task)}</p>
        <p class="muted">agent reasoning: ${esc(a.reasoning)}</p>
        <pre>${esc(JSON.stringify(a.arguments, null, 2))}</pre>`;
      const ok = document.createElement("button"); ok.textContent = "Approve & execute";
      const no = document.createElement("button"); no.textContent = "Deny"; no.className = "deny";
      ok.onclick = () => decide(a.id, true); no.onclick = () => decide(a.id, false);
      d.append(ok, document.createTextNode(" "), no);
      $("approvals").appendChild(d);
    }
  } catch {}
}
async function decide(id, approve) {
  await api("/api/approvals/" + id, { method: "POST", body: JSON.stringify({ approve }) });
  loadApprovals();
}

/* ---------- settings ---------- */
async function loadSettings() {
  const s = await api("/api/settings");
  $("orderInput").value = s.fallback_order.join(", ");
  $("providers").innerHTML = "";
  for (const [name, p] of Object.entries(s.providers)) {
    const pill = p.configured ? (p.state === "closed" ? "ok" : "bad") : "";
    $("providers").innerHTML += `<div class="tierrow"><label>${name}</label>
      <span class="pill ${pill}">${p.configured ? p.state : "no key"}</span></div>`;
  }
  $("tiers").innerHTML = "";
  for (const [name, tier] of Object.entries(s.tool_tiers)) {
    $("tiers").innerHTML += `<div class="tierrow"><label>${name}</label>
      <select data-tool="${name}">
        <option value="1" ${tier === 1 ? "selected" : ""}>Tier 1 — auto-run</option>
        <option value="2" ${tier === 2 ? "selected" : ""}>Tier 2 — auto + logged</option>
        <option value="3" ${tier === 3 ? "selected" : ""}>Tier 3 — needs approval</option>
      </select></div>`;
  }
}
$("saveSettings").onclick = async () => {
  const tiers = {};
  document.querySelectorAll("#tiers select").forEach((s) => (tiers[s.dataset.tool] = parseInt(s.value)));
  const order = $("orderInput").value.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ fallback_order: order, tool_tiers: tiers }) });
    $("settingsMsg").textContent = "Saved.";
  } catch (e) { $("settingsMsg").textContent = "Error: " + e.message; }
};

function refreshAll() { loadRuns(); loadApprovals(); }
function esc(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }

/* ---------- PWA ---------- */
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/static/sw.js");

/* ---------- boot ---------- */
token ? showMain() : showLogin();
