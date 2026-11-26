"use strict";
// Cinder client. All card and spec text is untrusted: it is only ever set with textContent.

// ---------- helpers ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function safeLink(url, text) {
  let ok = false;
  try { ok = ["https:", "http:"].includes(new URL(url).protocol); } catch (_) {}
  if (!ok) return h("span", { class: "src", text: text || url });
  return h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: text || url });
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (init.method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body || {});
  }
  const r = await fetch(path, init);
  if (r.status === 401) { location.href = "/login"; throw new Error("signed out"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error ? (typeof data.error === "string" ? data.error : "Request failed") : (Array.isArray(data.detail) ? "Invalid input" : `Error ${r.status}`));
  return data;
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + fmtTime(iso);
}
function readyLabel(hhmm) {
  const [hh, mm] = hhmm.split(":").map(Number);
  const d = new Date(); d.setHours(hh, mm, 0, 0);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

const view = () => document.getElementById("view");
let pollTimer = null;
function poll(fn, ms) { clearTimeout(pollTimer); pollTimer = setTimeout(fn, ms); }

// ---------- toast ----------
let toastTimer = null;
function toast(msg, actions = [], ms = 6000) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  clearTimeout(toastTimer);
  const el = h("div", { class: "toast", role: "status" }, h("span", { text: msg }));
  actions.forEach((a) => {
    el.append(h("span", { class: "sep", text: "·" }));
    el.append(h("button", { type: "button", onclick: () => { el.remove(); a.run(); } }, a.label));
  });
  document.body.append(el);
  toastTimer = setTimeout(() => el.remove(), ms);
}

// ---------- sheets ----------
function sheet(content, { onClose } = {}) {
  const close = () => { scrim.remove(); document.removeEventListener("keydown", esc); onClose && onClose(); };
  const esc = (e) => { if (e.key === "Escape") close(); };
  const box = h("div", { class: "sheet", role: "dialog", "aria-modal": "true" }, h("div", { class: "grab" }), content(close));
  const scrim = h("div", { class: "scrim", onclick: (e) => { if (e.target === scrim) close(); } }, box);
  document.addEventListener("keydown", esc);
  document.body.append(scrim);
  const f = box.querySelector("textarea, input, button.primary");
  if (f) setTimeout(() => f.focus(), 50);
  return close;
}

function detailSheet(card) {
  sheet((close) => {
    const sec = (title, body) => body && (Array.isArray(body) ? body.length : String(body).trim()) ? [h("h4", { text: title }), Array.isArray(body) ? h("ul", {}, body) : h("p", { text: body })] : null;
    return h("div", { class: "detail" },
      kindBadge(card),
      h("h3", { class: "mt8", text: card.title }),
      h("p", { class: "sub", text: card.pitch }),
      sec("Summary", card.summary),
      sec("Why now", card.why_now),
      sec("SEO angle", card.seo),
      sec("AI-agent visibility", card.agent_visibility),
      sec("Competitors / prior art", (card.competitors || []).map((c) => h("li", { text: c }))),
      sec("Evidence", (card.evidence || []).map((e) => h("li", {}, h("span", { text: e.claim + " " }), h("br"), safeLink(e.url)))),
      sec("Fit", card.fit),
      h("div", { class: "actions" }, h("button", { class: "btn", type: "button", onclick: close }, "Close")),
    );
  });
}

function kindBadge(card) {
  return card.kind === "feature"
    ? h("div", { class: "kind" }, h("span", { text: "Feature" }), h("code", { text: card.repo || "" }))
    : h("div", { class: "kind" }, "New project");
}

// ---------- deck ----------
const deck = { cards: [], notes: new Map(), busy: false, data: null, frontId: null };

async function loadDeck() {
  try {
    deck.data = await api("/api/deck");
  } catch (e) { return renderError(e); }
  deck.cards = deck.data.cards;
  if (deck.frontId) {
    const i = deck.cards.findIndex((c) => c.id === deck.frontId);
    if (i > 0) deck.cards.unshift(deck.cards.splice(i, 1)[0]);
    deck.frontId = null;
  }
  renderDeck();
  updateStatus(deck.data.running, deck.data.last_run);
  if (deck.data.running || (!deck.cards.length)) poll(() => route() === "deck" && loadDeck(), deck.data.running ? 5000 : 60000);
}

function updateStatus(running, last) {
  const el = document.getElementById("status");
  if (running) { el.textContent = `Dealing… ${last && last.step ? last.step : ""}`; el.className = "status-pill live"; }
  else el.className = "status-pill hidden";
}

function renderDeck() {
  const v = view();
  v.replaceChildren();
  if (!deck.cards.length) {
    const running = deck.data && deck.data.running;
    const last = deck.data && deck.data.last_run;
    v.append(h("div", { class: "empty" },
      h("div", { class: "glow", "aria-hidden": "true" }, "🔥"),
      running
        ? [h("h2", { text: "Dealing your deck…" }), h("p", { text: `Researching ideas${last && last.step ? " (" + last.step + ")" : ""}. This can take a while.` })]
        : [h("h2", { text: "You're all caught up" }), h("p", { text: `Next deck at ${readyLabel(deck.data ? deck.data.ready_by : "07:00")}.` })],
      last && last.status === "failed" && !running ? h("p", { class: "err", text: "Last run failed: " + (last.error || "unknown error") }) : null,
      running ? null : h("button", { class: "btn primary", type: "button", onclick: runNow }, "Run now"),
    ));
    return;
  }
  const stack = h("div", { class: "stack", role: "region", "aria-label": "Idea cards" });
  const shown = deck.cards.slice(0, 3);
  shown.slice().reverse().forEach((card, ri) => {
    const idx = shown.length - 1 - ri;
    const el = cardEl(card);
    if (idx === 1) el.classList.add("next");
    if (idx === 2) el.classList.add("third");
    if (idx === 0) attachDrag(el, card);
    stack.append(el);
  });
  v.append(h("div", { class: "deck-wrap" },
    stack,
    h("div", { class: "controls" },
      h("button", { class: "round small", type: "button", title: "Undo (u)", "aria-label": "Undo", onclick: undo }, "↶"),
      h("button", { class: "round pass", type: "button", title: "Dismiss (←)", "aria-label": "Dismiss", onclick: () => commit("left") }, "✕"),
      h("button", { class: "round note", type: "button", title: "Add a note (↑)", "aria-label": "Add a note", onclick: () => noteSheet(deck.cards[0]) }, "✎"),
      h("button", { class: "round save", type: "button", title: "Save (→)", "aria-label": "Save", onclick: () => commit("right") }, "♥"),
    ),
    h("div", { class: "hint", text: `${deck.cards.length} in your deck · tap a card for details` }),
  ));
}

function cardEl(card) {
  const note = deck.notes.get(card.id);
  const effortName = { S: "Small", M: "Medium", L: "Large" }[card.effort] || card.effort;
  return h("article", { class: "card", tabindex: "0", "aria-label": card.title, "data-id": card.id },
    h("div", { class: "stamp save", text: "Save" }),
    h("div", { class: "stamp pass", text: "Pass" }),
    h("div", { class: "stamp note", text: "Note" }),
    h("div", { class: "card-top" },
      kindBadge(card),
      h("span", { class: "effort", title: `Effort: ${effortName}`, "aria-label": `Effort: ${effortName}`, text: card.effort }),
    ),
    h("div", { class: "card-face" },
      h("h2", { text: card.title }),
      h("div", { class: "divider", "aria-hidden": "true" }),
      h("p", { class: "pitch", text: card.pitch }),
    ),
    h("ul", { class: "why" }, (card.why || []).map((w) => h("li", { text: w }))),
    h("div", { class: "foot" },
      note ? h("span", { class: "note-mark", text: "✎ Note attached" }) : h("span", { text: "Tap for details" }),
    ),
  );
}

function attachDrag(el, card) {
  let start = null, dx = 0, dy = 0, moved = false;
  const stamps = { save: el.querySelector(".stamp.save"), pass: el.querySelector(".stamp.pass"), note: el.querySelector(".stamp.note") };
  const setStamps = () => {
    const up = dy < 0 && Math.abs(dy) > Math.abs(dx) ? Math.min(1, -dy / 110) : 0;
    stamps.save.style.opacity = !up && dx > 0 ? Math.min(1, dx / 110) : 0;
    stamps.pass.style.opacity = !up && dx < 0 ? Math.min(1, -dx / 110) : 0;
    stamps.note.style.opacity = up;
  };
  el.addEventListener("pointerdown", (e) => {
    if (deck.busy || e.button > 0) return;
    start = { x: e.clientX, y: e.clientY, t: Date.now() }; dx = dy = 0; moved = false;
    el.setPointerCapture(e.pointerId);
    el.classList.add("dragging");
  });
  el.addEventListener("pointermove", (e) => {
    if (!start) return;
    dx = e.clientX - start.x; dy = e.clientY - start.y;
    if (Math.abs(dx) + Math.abs(dy) > 6) moved = true;
    el.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 18}deg)`;
    setStamps();
  });
  const end = () => {
    if (!start) return;
    const dt = Math.max(1, Date.now() - start.t);
    start = null;
    el.classList.remove("dragging");
    const fast = Math.abs(dx) / dt > 0.6;
    if (!moved) { el.style.transform = ""; detailSheet(card); return; }
    if (dy < -110 && Math.abs(dy) > Math.abs(dx)) {
      el.style.transform = ""; setStampsReset(); noteSheet(card); return;
    }
    if (dx > 110 || (fast && dx > 40)) return commit("right");
    if (dx < -110 || (fast && dx < -40)) return commit("left");
    el.style.transform = ""; setStampsReset();
  };
  const setStampsReset = () => Object.values(stamps).forEach((s) => (s.style.opacity = 0));
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", () => { start = null; el.classList.remove("dragging"); el.style.transform = ""; setStampsReset(); });
  el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); detailSheet(card); } });
}

function flyOut(direction) {
  const el = document.querySelector(".stack .card:not(.next):not(.third)");
  if (!el) return Promise.resolve();
  const x = direction === "right" ? window.innerWidth : -window.innerWidth;
  el.style.transform = `translate(${x}px, 40px) rotate(${direction === "right" ? 24 : -24}deg)`;
  el.style.opacity = "0";
  return new Promise((r) => setTimeout(r, 220));
}

async function commit(direction, extra = {}) {
  const card = deck.cards[0];
  if (!card || deck.busy) return;
  deck.busy = true;
  const note = deck.notes.get(card.id) || null;
  try {
    await flyOut(direction);
    await api(`/api/cards/${card.id}/swipe`, { method: "POST", body: { direction, note, never: !!extra.never } });
    deck.notes.delete(card.id);
    deck.cards.shift();
    renderDeck();
    if (direction === "left") {
      toast("Dismissed", [
        { label: "Undo", run: undo },
        { label: "Never like this", run: () => neverLike(card) },
      ]);
    } else {
      toast("Saved · writing the spec", [{ label: "Undo", run: undo }]);
      refreshSavedCount();
    }
  } catch (e) {
    toast(e.message);
    await loadDeck();
  } finally {
    deck.busy = false;
  }
}

async function neverLike(card) {
  try {
    await api(`/api/cards/${card.id}/never`, { method: "POST" });
    toast("Got it. Cinder won't suggest ideas like this.");
  } catch (e) { toast(e.message); }
}

async function undo() {
  if (deck.busy) return;
  deck.busy = true;
  try {
    const r = await api("/api/undo", { method: "POST" });
    deck.frontId = r.card_id;
    if (route() !== "deck") location.hash = "#/";
    await loadDeck();
    refreshSavedCount();
  } catch (e) {
    toast(e.message);
  } finally {
    deck.busy = false;
  }
}

function noteSheet(card) {
  if (!card) return;
  sheet((close) => {
    const ta = h("textarea", { id: "note", maxlength: "4000", placeholder: "Why you like it, what to change, or why you're passing…" });
    ta.value = deck.notes.get(card.id) || "";
    const attach = () => {
      const v = ta.value.trim();
      if (v) deck.notes.set(card.id, v); else deck.notes.delete(card.id);
      close(); renderDeck();
    };
    const go = (dir) => { const v = ta.value.trim(); if (v) deck.notes.set(card.id, v); close(); commit(dir); };
    return h("div", {},
      h("h3", { text: "Add a note" }),
      h("p", { class: "sub", text: card.title }),
      h("label", { for: "note", text: "Saving? It steers the spec. Passing? It teaches Cinder your taste." }),
      ta,
      h("div", { class: "actions" },
        h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel"),
        h("button", { class: "btn", type: "button", onclick: attach }, "Attach note"),
        h("button", { class: "btn", type: "button", onclick: () => go("left") }, "✕ Dismiss"),
        h("button", { class: "btn primary", type: "button", onclick: () => go("right") }, "♥ Save"),
      ),
    );
  });
}

async function runNow() {
  try {
    await api("/api/runs", { method: "POST" });
    toast("Run started. New cards will appear here.");
    loadDeck();
  } catch (e) { toast(e.message); }
}

// ---------- saved ----------
async function loadSaved() {
  let data;
  try { data = await api("/api/saved"); } catch (e) { return renderError(e); }
  const labels = { queued: "Queued", writing: "Writing spec…", pr_open: "PR open", failed: "Failed" };
  const v = view();
  v.replaceChildren(h("h2", { class: "page-title", text: "Saved" }));
  if (!data.cards.length) v.append(h("p", { class: "muted", text: "Swipe right on an idea and Cinder will write a spec and open a PR for it." }));
  const list = h("div", { class: "list" });
  for (const c of data.cards) {
    list.append(h("div", { class: "item" },
      kindBadgeSmall(c),
      h("h3", { text: c.title }),
      h("p", { text: c.pitch }),
      c.note ? h("div", { class: "note", text: c.note }) : null,
      h("div", { class: "meta" },
        h("span", { class: `chip ${c.spec_status || ""}`, text: labels[c.spec_status] || "—" }),
        c.pr_url ? safeLink(c.pr_url, "View PR ↗") : null,
        c.spec_status === "failed" ? h("button", { class: "btn", type: "button", onclick: async () => { try { await api(`/api/specs/${c.spec_id}/retry`, { method: "POST" }); loadSaved(); } catch (e) { toast(e.message); } } }, "Retry") : null,
        h("span", { text: fmtDate(c.decided_at) }),
        h("button", { class: "btn ghost", type: "button", onclick: () => detailSheet(c) }, "Details"),
      ),
      c.spec_status === "failed" && c.spec_error ? h("div", { class: "err", text: c.spec_error }) : null,
    ));
  }
  v.append(list);
  if (data.cards.some((c) => ["queued", "writing"].includes(c.spec_status))) poll(() => route() === "saved" && loadSaved(), 8000);
}

function kindBadgeSmall(c) {
  return h("div", { class: "kind small muted", text: c.kind === "feature" ? `Feature · ${c.repo}` : "New project" });
}

// ---------- history ----------
let historyFilter = "all";
async function loadHistory() {
  let data;
  try { data = await api(`/api/history?filter=${historyFilter}`); } catch (e) { return renderError(e); }
  const v = view();
  const seg = h("div", { class: "seg", role: "tablist" },
    ["all", "liked", "dismissed"].map((f) => h("button", { type: "button", class: f === historyFilter ? "on" : "", role: "tab", "aria-selected": String(f === historyFilter), onclick: () => { historyFilter = f; loadHistory(); } }, { all: "All", liked: "Saved", dismissed: "Dismissed" }[f])));
  v.replaceChildren(h("h2", { class: "page-title", text: "History" }), seg);
  if (!data.cards.length) v.append(h("p", { class: "muted", text: "Nothing here yet." }));
  const list = h("div", { class: "list" });
  for (const c of data.cards) {
    list.append(h("div", { class: "item" },
      kindBadgeSmall(c),
      h("h3", { text: c.title }),
      h("p", { text: c.pitch }),
      c.note ? h("div", { class: "note", text: c.note }) : null,
      h("div", { class: "meta" },
        h("span", { class: `chip ${c.status}`, text: c.status === "liked" ? "Saved" : (c.never ? "Never like this" : "Dismissed") }),
        h("span", { text: fmtDate(c.decided_at) }),
        c.pr_url ? safeLink(c.pr_url, "PR ↗") : null,
        h("button", { class: "btn ghost", type: "button", onclick: () => detailSheet(c) }, "Details"),
        c.status === "dismissed" ? h("button", { class: "btn", type: "button", onclick: async () => {
          try { await api(`/api/cards/${c.id}/resave`, { method: "POST", body: {} }); toast("Saved · writing the spec"); refreshSavedCount(); loadHistory(); } catch (e) { toast(e.message); }
        } }, "♥ Save instead") : null,
      ),
    ));
  }
  v.append(list);
}

// ---------- settings ----------
async function loadSettings() {
  let s, repos, rules, profile, runs;
  try {
    [s, repos, rules, profile, runs] = await Promise.all([
      api("/api/settings"), api("/api/repos"), api("/api/never-rules"), api("/api/profile"), api("/api/runs/latest"),
    ]);
  } catch (e) { return renderError(e); }
  const v = view();
  v.replaceChildren(h("h2", { class: "page-title", text: "Settings" }));

  // Runs
  const runRows = runs.recent.length ? runs.recent.map((r) => h("div", { class: "run" },
    h("span", { class: `chip ${r.status === "succeeded" ? "pr_open" : r.status === "failed" ? "failed" : "writing"}`, text: r.status }),
    h("span", { text: `${fmtDate(r.started_at)} · ${r.kind}` }),
    h("span", { class: "muted", text: `${r.new_cards} new · $${(r.cost_usd || 0).toFixed(2)}` }),
    r.status === "running" ? h("span", { class: "muted", text: r.step || "" }) : null,
    r.error ? h("div", { class: "err w100", text: r.error }) : null,
  )) : [h("p", { class: "muted small", text: "No runs yet." })];
  v.append(h("div", { class: "section" },
    h("h3", {}, "Runs", h("button", { class: "btn primary", type: "button", disabled: runs.running, onclick: async () => { await runNow(); loadSettings(); } }, runs.running ? "Running…" : "Run now")),
    runRows));
  if (runs.running) poll(() => route() === "settings" && loadSettings(), 6000);

  // Schedule & deck
  const f = (id, type, value, attrs = {}) => h("input", { id, type, value, ...attrs });
  const tz = f("tz", "text", s.tz), ready = f("ready", "time", s.ready_by);
  const size = f("size", "number", s.deck_size, { min: 1, max: 30 }), mf = f("mf", "number", s.mix_features, { min: 0, max: 30 }), mp = f("mp", "number", s.mix_projects, { min: 0, max: 30 });
  const maxRepos = f("maxrepos", "number", s.max_repos, { min: 1, max: 200 });
  const msg = h("span", { class: "small muted" });
  v.append(h("div", { class: "section" },
    h("h3", { text: "Schedule & deck" }),
    h("div", { class: "grid2" }, h("div", {}, h("label", { for: "tz", text: "Time zone" }), tz), h("div", {}, h("label", { for: "ready", text: "Deck ready by" }), ready)),
    h("div", { class: "grid3 mt12" },
      h("div", {}, h("label", { for: "size", text: "Deck size" }), size),
      h("div", {}, h("label", { for: "mf", text: "Features" }), mf),
      h("div", {}, h("label", { for: "mp", text: "New projects" }), mp)),
    h("div", { class: "mt12" }, h("label", { for: "maxrepos", text: "Analyse the most recently active … repos" }), maxRepos),
    h("div", { class: "row-actions mt12" },
      h("button", { class: "btn primary", type: "button", onclick: async () => {
        try {
          await api("/api/settings", { method: "PUT", body: { tz: tz.value.trim(), ready_by: ready.value, deck_size: +size.value, mix_features: +mf.value, mix_projects: +mp.value, max_repos: +maxRepos.value } });
          msg.textContent = "Saved.";
        } catch (e) { msg.textContent = e.message; }
      } }, "Save"), msg),
  ));

  // Repos
  const repoBox = h("div", {});
  if (!repos.repos.length) repoBox.append(h("p", { class: "muted small", text: "No repos synced yet. Sync to list everything Cinder can read." }));
  for (const r of repos.repos) {
    const cb = h("input", { type: "checkbox", "aria-label": `Include ${r.full_name}` });
    cb.checked = !r.excluded;
    cb.addEventListener("change", async () => {
      try { await api(`/api/repos/${r.id}`, { method: "PUT", body: { excluded: !cb.checked } }); } catch (e) { cb.checked = !cb.checked; toast(e.message); }
    });
    const tags = [r.private ? "private" : "public", r.fork ? "fork" : null, r.archived ? "archived" : null, r.pushed_at ? "pushed " + fmtDate(r.pushed_at) : null].filter(Boolean).join(" · ");
    repoBox.append(h("div", { class: "repo" },
      h("div", { class: "name" }, h("b", { text: r.full_name }), h("span", { text: tags })),
      h("label", { class: "switch" }, cb, h("span", {}))));
  }
  const syncBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    syncBtn.disabled = true; syncBtn.textContent = "Syncing…";
    try { const r = await api("/api/repos/sync", { method: "POST" }); toast(`${r.count} repos synced`); loadSettings(); }
    catch (e) { toast(e.message, [], 9000); syncBtn.disabled = false; syncBtn.textContent = "Sync"; }
  } }, "Sync");
  v.append(h("div", { class: "section" }, h("h3", {}, `Repos (${repos.repos.filter((r) => !r.excluded).length}/${repos.repos.length} included)`, syncBtn), repoBox));

  // Never rules
  const ruleBox = h("div", {});
  if (!rules.rules.length) ruleBox.append(h("p", { class: "muted small", text: "None yet. Tap “Never like this” after dismissing a card." }));
  for (const r of rules.rules) {
    ruleBox.append(h("div", { class: "rule" },
      h("span", { class: "t", text: r.text }),
      h("button", { class: "iconbtn", type: "button", title: "Edit", "aria-label": "Edit rule", onclick: () => editRule(r) }, "✎"),
      h("button", { class: "iconbtn", type: "button", title: "Remove", "aria-label": "Remove rule", onclick: async () => { try { await api(`/api/never-rules/${r.id}`, { method: "DELETE" }); loadSettings(); } catch (e) { toast(e.message); } } }, "✕")));
  }
  v.append(h("div", { class: "section" }, h("h3", { text: "Never like this" }), ruleBox));

  // Profile
  v.append(h("div", { class: "section" },
    h("h3", {}, "What Cinder thinks you like", h("button", { class: "btn ghost danger", type: "button", onclick: async () => {
      if (!confirm("Reset the preference profile? Cinder will forget what it has learned from your swipes so far.")) return;
      try { await api("/api/profile", { method: "DELETE" }); loadSettings(); } catch (e) { toast(e.message); }
    } }, "Reset")),
    profile.markdown ? h("pre", { class: "profile", text: profile.markdown }) : h("p", { class: "muted small", text: "Nothing learned yet. The profile updates at the start of each daily run from your swipes and notes." }),
    profile.updated_at ? h("p", { class: "small muted", text: "Updated " + fmtDate(profile.updated_at) }) : null));

  v.append(h("div", { class: "section" },
    h("h3", {}, "Account", h("button", { class: "btn", type: "button", onclick: async () => { await api("/auth/logout", { method: "POST" }).catch(() => {}); location.href = "/login"; } }, "Sign out"))));
}

function editRule(rule) {
  sheet((close) => {
    const inp = h("input", { type: "text", id: "rule", maxlength: "300" });
    inp.value = rule.text;
    return h("div", {},
      h("h3", { text: "Edit rule" }),
      h("label", { for: "rule", text: "Cinder will never suggest ideas matching:" }), inp,
      h("div", { class: "actions" },
        h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel"),
        h("button", { class: "btn primary", type: "button", onclick: async () => {
          try { await api(`/api/never-rules/${rule.id}`, { method: "PUT", body: { text: inp.value } }); close(); loadSettings(); } catch (e) { toast(e.message); }
        } }, "Save")));
  });
}

// ---------- routing ----------
function route() {
  const r = location.hash.replace(/^#\/?/, "");
  return ["saved", "history", "settings"].includes(r) ? r : "deck";
}

function renderError(e) {
  view().replaceChildren(h("div", { class: "empty" }, h("h2", { text: "Something went wrong" }), h("p", { text: e.message }), h("button", { class: "btn", type: "button", onclick: render }, "Try again")));
}

async function refreshSavedCount() {
  try {
    const d = await api("/api/saved");
    const n = d.cards.filter((c) => ["queued", "writing", "failed"].includes(c.spec_status)).length;
    const el = document.getElementById("saved-count");
    el.replaceChildren(n ? h("span", { class: "badge-count", text: n }) : "");
  } catch (_) {}
}

function render() {
  clearTimeout(pollTimer);
  const r = route();
  document.querySelectorAll("nav.tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === r));
  document.querySelectorAll("nav.tabs a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.tab === r));
  ({ deck: loadDeck, saved: loadSaved, history: loadHistory, settings: loadSettings })[r]();
}

document.addEventListener("keydown", (e) => {
  if (route() !== "deck" || document.querySelector(".scrim") || e.target.closest("input, textarea")) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); commit("left"); }
  else if (e.key === "ArrowRight") { e.preventDefault(); commit("right"); }
  else if (e.key === "ArrowUp") { e.preventDefault(); noteSheet(deck.cards[0]); }
  else if (e.key === "u" || e.key === "U") undo();
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) render(); });
window.addEventListener("hashchange", render);
render();
refreshSavedCount();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
