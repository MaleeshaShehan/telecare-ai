/* ═══════════════════════════════════════════════════════════════════
   TeleCare AI — front end
   Plain JS, no framework. Talks only to the Orchestrator on the same
   origin. The browser never sees a JWT: login state lives in the
   Orchestrator's session, keyed by our conversation id.
   ═══════════════════════════════════════════════════════════════════ */
"use strict";

// ───────────────────────────── constants ─────────────────────────────
const AGENTS = {
  orchestrator:     { name: "Orchestrator", role: "Front desk · routes",      short: "O" },
  knowledge_agent:  { name: "Knowledge",    role: "Product expert · RAG",     short: "K" },
  account_agent:    { name: "Account",      role: "Accounts clerk · read-only", short: "A" },
  supervisor_agent: { name: "Supervisor",   role: "Floor manager · escalates", short: "S" },
};
const DISCLOSURE = "Hi, I'm TeleCare's AI assistant.";
const HUMAN_REQUEST = "I'd like to talk to a human agent, please.";

// ───────────────────────────── state ─────────────────────────────
const state = {
  cid: sessionStorage.getItem("telecare_cid") || newId(),
  traceCount: 0,
  turn: 0,
  busy: false,
  auth: { stage: "out", msisdn: "", error: "" },
};
sessionStorage.setItem("telecare_cid", state.cid);

// ───────────────────────────── dom ─────────────────────────────
const $ = (id) => document.getElementById(id);
const el = {
  app: $("app"), messages: $("messages"), empty: $("empty"), composer: $("composer"), input: $("input"),
  send: $("send"), account: $("account"), agents: $("agents"), timeline: $("timeline"),
  traceEmpty: $("trace-empty"), legend: $("legend"), toasts: $("toasts"),
};

// ───────────────────────────── helpers ─────────────────────────────
function newId() {
  return (crypto.randomUUID && crypto.randomUUID()) || `c-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
/** Minimal, safe formatting: bold, line breaks, and [n] citations -> clickable chips. */
function formatText(text) {
  let s = escapeHtml(text);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\[(\d{1,2})\]/g, '<button type="button" class="cite" data-n="$1" aria-label="Source $1">$1</button>');
  return s.replace(/\n/g, "<br>");
}
function money(n) {
  const v = Number(n) || 0;
  return (v < 0 ? "−" : "") + "Rs. " + Math.abs(v).toLocaleString("en-LK");
}
function timeOf(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString("en-GB", { hour12: false });
}
function maskMsisdn(m) {
  return m.length > 6 ? m.slice(0, 3) + "•••" + m.slice(-4) : m;
}
async function api(path, { method = "GET", body } = {}) {
  const headers = { "X-Conversation-Id": state.cid };
  if (body) headers["Content-Type"] = "application/json";
  try {
    const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let data = {};
    try { data = await r.json(); } catch { data = { detail: await r.text() }; }
    return { code: r.status, data };
  } catch (e) {
    return { code: 0, data: { detail: "Cannot reach the Orchestrator. Is run_all.py running?" } };
  }
}

// ───────────────────────────── toasts ─────────────────────────────
function toast({ kind = "info", icon = "ℹ", title, body, code, actions = [], ttl = 9000 }) {
  const t = h("div", { class: `toast ${kind}`, role: "status" },
    h("div", { class: "ticon" }, icon),
    h("div", { style: "flex:1;min-width:0" },
      h("div", { class: "tt" }, title),
      body ? h("div", { class: "tb" }, body) : null,
      code ? h("div", { class: "code" }, code) : null,
      actions.length ? h("div", { class: "tactions" }, actions.map((a) =>
        h("button", { class: a.primary ? "btn" : "ghost", onclick: () => { a.onClick(); dismiss(); } }, a.label))) : null,
    ),
    h("button", { class: "tx", "aria-label": "Dismiss", onclick: () => dismiss() }, "✕"),
  );
  function dismiss() { t.classList.add("leaving"); setTimeout(() => t.remove(), 260); }
  el.toasts.append(t);
  if (ttl) setTimeout(dismiss, ttl);
}

// ───────────────────────────── theme ─────────────────────────────
function initTheme() {
  const saved = localStorage.getItem("telecare_theme");
  if (saved) document.documentElement.dataset.theme = saved;
  $("theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("telecare_theme", next);
  });
}

// ───────────────────────────── agents rail ─────────────────────────────
function renderAgents(health = {}) {
  el.agents.replaceChildren(...Object.entries(AGENTS).map(([key, a]) =>
    h("li", { class: "agent", title: a.role },
      h("span", { class: "swatch", style: `background:var(--ag-${key})` }),
      h("div", null, h("div", { class: "name" }, a.name), h("div", { class: "role" }, a.role)),
      h("span", { class: `dot ${health[key] === undefined ? "" : health[key] ? "up" : "down"}`,
                  "aria-label": health[key] ? "online" : "offline" }),
    )));
  el.legend.replaceChildren(...Object.entries(AGENTS).map(([key, a]) =>
    h("span", null, h("i", { style: `background:var(--ag-${key})` }), a.name)));
}
async function pollHealth() {
  const { code, data } = await api("/agents/health");
  renderAgents(code === 200 ? data : { orchestrator: false });
}

// ───────────────────────────── account card ─────────────────────────────
function renderAccount() {
  const a = state.auth;
  const err = a.error ? h("div", { class: "form-error" }, a.error) : null;

  if (a.stage === "out") {
    el.account.replaceChildren(
      h("div", { class: "account-title" }, h("h3", null, "Your account"), h("span", { class: "pill" , style: "background:var(--surface-3);color:var(--muted)" }, "Logged out")),
      h("form", { onsubmit: onLogin },
        h("div", { class: "field" }, h("label", { for: "msisdn" }, "Mobile number"),
          h("input", { id: "msisdn", class: "input", inputmode: "tel", placeholder: "0712345678", required: "", autocomplete: "tel", pattern: "(?:\\+94|0)7\\d{8}" })),
        h("button", { class: "btn block", type: "submit" }, "Send verification code"),
        err,
      ),
      h("p", { class: "muted small" }, "We'll text a one-time code to verify your number. No password needed."),
    );
  } else if (a.stage === "otp") {
    el.account.replaceChildren(
      h("div", { class: "account-title" }, h("h3", null, "Verify it's you"), h("span", { class: "pill pill-ai" }, maskMsisdn(a.msisdn))),
      h("div", { class: "sms-hint" }, h("span", null, "📱"), h("span", null, "We sent a 6-digit code to your phone. It expires in 5 minutes and allows 3 attempts.")),
      h("form", { onsubmit: onVerify },
        h("div", { class: "field" },
          h("input", { id: "otp", class: "input otp", inputmode: "numeric", maxlength: "6", pattern: "\\d{6}", placeholder: "••••••", required: "", autocomplete: "one-time-code" })),
        h("div", { class: "row" },
          h("button", { class: "btn", type: "submit", style: "flex:1" }, "Verify"),
          h("button", { class: "btn secondary", type: "button", onclick: () => { state.auth = { stage: "out", msisdn: "", error: "" }; renderAccount(); } }, "Cancel")),
        err,
      ),
    );
    setTimeout(() => $("otp")?.focus(), 50);
  } else {
    el.account.replaceChildren(
      h("div", { class: "account-title" }, h("h3", null, "Your account"), h("span", { class: "pill pill-green" }, "Verified")),
      h("div", { class: "identity" },
        h("div", { class: "avatar" }, "✓"),
        h("div", null, h("div", { class: "who" }, maskMsisdn(a.msisdn)), h("div", { class: "since" }, "Session active · 15 min"))),
      h("button", { class: "btn secondary block", style: "margin-top:12px", onclick: onLogout }, "Log out"),
    );
  }
}
async function onLogin(e) {
  e.preventDefault();
  const msisdn = $("msisdn").value.trim();
  const btn = e.target.querySelector("button[type=submit]"); btn.disabled = true;
  const { code, data } = await api("/auth/login", { method: "POST", body: { conversation_id: state.cid, msisdn } });
  btn.disabled = false;
  if (code === 200) {
    state.auth = { stage: "otp", msisdn, error: "" };
    renderAccount();
    if (data.debug_otp) {
      toast({ kind: "sms", icon: "💬", title: "Simulated SMS · TeleCare", body: "Your one-time code is", code: data.debug_otp, ttl: 60000,
              actions: [{ label: "Use code", primary: true, onClick: () => { const o = $("otp"); if (o) { o.value = data.debug_otp; o.focus(); } } }] });
    } else if (data.channel === "sms") {
      toast({ kind: "sms", icon: "📱", title: "SMS sent", body: `A 6-digit code was sent to ${maskMsisdn(msisdn)}. Check your phone.`, ttl: 12000 });
    }
  } else {
    state.auth.error = data.detail || "We couldn't send a code to that number.";
    renderAccount();
  }
}
async function onVerify(e) {
  e.preventDefault();
  const otp = $("otp").value.trim();
  const btn = e.target.querySelector("button[type=submit]"); btn.disabled = true;
  const { code, data } = await api("/auth/verify-otp", { method: "POST", body: { conversation_id: state.cid, msisdn: state.auth.msisdn, otp } });
  btn.disabled = false;
  if (code === 200 && data.logged_in) {
    state.auth = { stage: "in", msisdn: state.auth.msisdn, error: "" };
    renderAccount();
    toast({ kind: "ok", icon: "✓", title: "Logged in", body: "You can now ask about your bill and data balance.", ttl: 5000 });
  } else {
    state.auth.error = data.detail || "That code was not accepted.";
    renderAccount();
  }
}
async function onLogout() {
  await api("/auth/logout", { method: "POST", body: { conversation_id: state.cid } });
  state.auth = { stage: "out", msisdn: "", error: "" };
  renderAccount();
}
async function syncAuth() {
  const { code, data } = await api(`/auth/status?conversation_id=${encodeURIComponent(state.cid)}`);
  if (code === 200 && data.logged_in && state.auth.stage !== "in") { state.auth = { stage: "in", msisdn: state.auth.msisdn || "your number", error: "" }; }
  if (code === 200 && !data.logged_in && state.auth.stage === "in") { state.auth = { stage: "out", msisdn: "", error: "" }; }
  renderAccount();
}

// ───────────────────────────── messages ─────────────────────────────
function scrollToEnd() { el.messages.scrollTo({ top: el.messages.scrollHeight, behavior: "smooth" }); }

function addUser(text) {
  el.empty.style.display = "none";
  el.messages.append(h("div", { class: "msg user" },
    h("div", { class: "avatar-user", "aria-hidden": "true" }, "You"),
    h("div", { class: "bubble-wrap" }, h("div", { class: "bubble" }, text))));
  scrollToEnd();
}
function addTyping() {
  const t = h("div", { class: "msg ai", id: "typing" },
    aiAvatar(), h("div", { class: "bubble-wrap" }, h("div", { class: "bubble typing" }, h("i"), h("i"), h("i"))));
  el.messages.append(t); scrollToEnd();
  return () => t.remove();
}
function aiAvatar() {
  const a = h("div", { class: "avatar-ai", "aria-hidden": "true" });
  a.innerHTML = '<svg viewBox="0 0 32 32" width="16" height="16"><path d="M8 11h16M8 16h11M8 21h7" stroke="currentColor" stroke-width="3" stroke-linecap="round" fill="none"/></svg>';
  return a;
}

function addAssistant(data) {
  let text = data.reply || "";
  let disclosed = false;
  if (text.startsWith(DISCLOSURE)) { text = text.slice(DISCLOSURE.length).trim(); disclosed = true; }

  const bubble = h("div", { class: `bubble ${data.status}` });
  bubble.innerHTML = formatText(text || "…");

  const wrap = h("div", { class: "bubble-wrap" },
    disclosed ? h("div", { class: "meta" }, h("span", { class: "pill pill-ai" }, "AI assistant"), "Answers are informational. A human handles anything serious.") : null,
    bubble,
  );

  // Structured cards
  const x = data.extra || {};
  if (x.bill_diff) wrap.append(billCard(x.bill_diff));
  if (x.quota) wrap.append(quotaCard(x.quota));
  if (x.ticket_id) wrap.append(ticketCard(x.ticket_id, x));
  if (data.sources && data.sources.length) wrap.append(sourcesList(data.sources));

  // State-specific helpers
  if (data.status === "needs_auth") {
    wrap.append(h("div", { class: "gate" },
      h("span", null, "🔒"), h("span", null, "This needs your account. Log in from the panel on the left."),
      h("button", { class: "btn", onclick: focusLogin }, "Log in")));
    focusLogin();
  }
  if (data.status === "not_found" || data.status === "error") {
    wrap.append(h("div", { class: "actions" },
      h("button", { class: "ghost", onclick: () => send(HUMAN_REQUEST) }, "Talk to a human")));
  }

  // citation hover <-> source card
  bubble.querySelectorAll(".cite").forEach((c) => {
    const target = () => wrap.querySelector(`.source[data-n="${c.dataset.n}"]`);
    c.addEventListener("mouseenter", () => target()?.classList.add("hot"));
    c.addEventListener("mouseleave", () => target()?.classList.remove("hot"));
    c.addEventListener("click", () => { const s = target(); if (s) { s.classList.add("hot"); s.scrollIntoView({ block: "nearest" }); setTimeout(() => s.classList.remove("hot"), 900); } });
  });

  el.messages.append(h("div", { class: "msg ai" }, aiAvatar(), wrap));
  scrollToEnd();
}

function sourcesList(sources) {
  return h("div", { class: "sources" }, sources.map((s, i) => {
    const n = s.id ?? i + 1;
    const tag = s.url ? "a" : "div";
    return h(tag, { class: "source", "data-n": n, href: s.url || null, target: s.url ? "_blank" : null, rel: "noopener" },
      h("span", { class: "n" }, n),
      h("div", { style: "min-width:0" }, h("div", { class: "t" }, s.title || "Source"), s.url ? h("div", { class: "u" }, s.url) : null),
      s.chunk_id ? h("span", { class: "c" }, s.chunk_id) : null);
  }));
}
function billCard(d) {
  const change = Number(d.change) || 0;
  return h("div", { class: "datacard" },
    h("div", { class: "label" }, "Change vs last month"),
    h("div", { class: `big ${change > 0 ? "up" : change < 0 ? "down" : ""}` }, (change > 0 ? "+" : "") + money(change)),
    (d.drivers || []).length ? h("ul", null, d.drivers.map((dr) =>
      h("li", null, h("span", null, dr.item, dr.date ? h("div", { class: "d" }, dr.date) : null), h("span", { class: "amt" }, money(dr.amount))))) : null,
    d.base_plan_changed === false ? h("div", { class: "ok" }, "✓ Base plan unchanged") : null,
  );
}
function quotaCard(q) {
  const used = Number(q.used_gb) || 0, total = Number(q.allowance_gb) || 0;
  const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
  return h("div", { class: "datacard" },
    h("div", { class: "label" }, "Data this cycle"),
    h("div", { class: "big" }, `${(total - used).toFixed(1)} GB left`),
    h("div", { class: "meter" }, h("i", { style: `width:${pct}%` })),
    h("div", { class: "muted small" }, `${used} of ${total} GB used · ${pct}%`),
  );
}
function ticketCard(id, x) {
  return h("div", { class: "datacard ticket" },
    h("div", { class: "row" },
      h("div", null, h("div", { class: "label" }, "Escalated to a human"), h("div", { class: "big mono" }, id)),
      h("button", { class: "copy", onclick: (e) => { navigator.clipboard?.writeText(id); e.target.textContent = "Copied"; setTimeout(() => (e.target.textContent = "Copy"), 1200); } }, "Copy")),
    h("div", { class: "muted small" }, (x.priority ? `Priority ${x.priority} · ` : "") + "A human agent will contact you within 24 hours."),
  );
}
function focusLogin() {
  el.account.classList.remove("attention"); void el.account.offsetWidth; el.account.classList.add("attention");
  $("msisdn")?.focus();
}

// ───────────────────────────── send ─────────────────────────────
async function send(text) {
  text = (text || "").trim();
  if (!text || state.busy) return;
  state.busy = true; el.send.disabled = true;
  el.input.value = ""; autosize();
  addUser(text);
  const stopTyping = addTyping();

  const { code, data } = await api("/chat", { method: "POST", body: { conversation_id: state.cid, message: text } });
  stopTyping();

  if (code === 200 || code === 429) {
    addAssistant(code === 429 ? { ...data, status: "error" } : data);
    if (Array.isArray(data.trace)) updateTrace(data.trace);
  } else {
    addAssistant({ reply: data.detail || "Something went wrong.", status: "error", sources: [], extra: {} });
  }
  state.busy = false; el.send.disabled = false; el.input.focus();
}

// ───────────────────────────── trace timeline ─────────────────────────────
const STOP_DECISIONS = new Set(["injection_blocked", "auth_required", "escalate", "clarify", "rate_limited", "answered_locally"]);

function updateTrace(trace) {
  const fresh = trace.slice(state.traceCount);
  if (!fresh.length) return;
  state.traceCount = trace.length;
  state.turn += 1;
  el.traceEmpty.style.display = "none";

  el.timeline.append(h("li", { class: "turn-sep" }, `Turn ${state.turn}`));
  fresh.forEach((t, i) => {
    const agent = AGENTS[t.agent] ? t.agent : "orchestrator";
    const [what, arrow] = describe(t.decision, agent);
    el.timeline.append(h("li", { class: `step ${STOP_DECISIONS.has(t.decision) ? "stop" : ""}`,
                              style: `--agent:var(--ag-${agent}); --delay:${i * 70}ms` },
      h("span", { class: "dot" }),
      h("div", { class: "who" }, AGENTS[agent].name),
      h("div", { class: "what" }, what, arrow ? [h("span", { class: "arrow" }, "→"), h("span", { style: `color:var(--ag-${arrow})` }, AGENTS[arrow]?.name || arrow)] : null),
      t.reason ? h("div", { class: "why" }, t.reason) : null,
      h("div", { class: "when" }, timeOf(t.ts)),
    ));
  });
  el.timeline.scrollTo({ top: el.timeline.scrollHeight, behavior: "smooth" });
}
/** "route->account_agent" -> ["Route", "account_agent"]; "intent=bill_enquiry" -> ["Intent: bill_enquiry"] */
function describe(decision = "", agent = "orchestrator") {
  if (decision.startsWith("route->")) return ["Route", decision.slice(7)];
  if (decision === "assess" && agent === "orchestrator") return ["Supervisor consulted", null];
  if (decision.startsWith("intent=")) return [`Intent · ${decision.slice(7)}`, null];
  if (decision.startsWith("result=")) return [`Result · ${decision.slice(7)}`, null];
  const names = {
    assess: "Sentiment assessed", escalate: "Escalated to human", auth_required: "Login required",
    injection_blocked: "Prompt injection blocked", clarify: "Asked to clarify", ai_disclosure_shown: "AI disclosure shown",
    answered_locally: "Out of scope · answered locally", stub_answer: "Stub answer", needs_auth: "Token missing",
    rate_limited: "Rate limited", assess_unavailable: "Supervisor unavailable", login_proxied: "Login forwarded",
    otp_verified: "OTP verified · session opened", otp_rejected: "OTP rejected", logout: "Logged out",
    retrieval_insufficient: "Evidence too weak", retrieved: "Documents retrieved",
  };
  return [names[decision] || decision.replace(/_/g, " "), null];
}

// ───────────────────────────── composer & misc ─────────────────────────────
function autosize() { el.input.style.height = "auto"; el.input.style.height = Math.min(el.input.scrollHeight, 160) + "px"; }

function newChat() {
  state.cid = newId(); sessionStorage.setItem("telecare_cid", state.cid);
  state.traceCount = 0; state.turn = 0;
  state.auth = { stage: "out", msisdn: "", error: "" };
  el.messages.querySelectorAll(".msg").forEach((m) => m.remove());
  el.empty.style.display = "";
  el.timeline.replaceChildren(); el.traceEmpty.style.display = "";
  renderAccount(); el.input.focus();
}

function bind() {
  el.composer.addEventListener("submit", (e) => { e.preventDefault(); send(el.input.value); });
  el.input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(el.input.value); } });
  el.input.addEventListener("input", autosize);
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => send(c.dataset.q)));
  $("newchat").addEventListener("click", newChat);
  const toggle = $("toggle-trace");
  const setTrace = (open) => { el.app.classList.toggle("trace-open", open); toggle.setAttribute("aria-expanded", String(open)); };
  toggle.addEventListener("click", () => setTrace(!el.app.classList.contains("trace-open")));
  $("close-trace").addEventListener("click", () => setTrace(false));
  $("scrim").addEventListener("click", () => setTrace(false));
  // Trace panel: open by default on wide screens, a drawer on narrow ones.
  const wide = window.matchMedia("(min-width: 1181px)");
  setTrace(wide.matches);
  wide.addEventListener("change", (e) => setTrace(e.matches));
}

// ───────────────────────────── boot ─────────────────────────────
initTheme();
renderAgents();
renderAccount();
bind();
syncAuth();
pollHealth();
setInterval(pollHealth, 8000);
el.input.focus();
