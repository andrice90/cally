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

const ICONS = {
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  pass: '<path d="M18 6 6 18M6 6l12 12"/>',
  note: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 2.5v3M15 2.5v3M9 11h6M9 15h4"/>',
  save: '<path class="fill" d="M12 20.5s-7.5-4.6-9.3-9.4C1.6 8 3.5 4.5 7 4.5c2.1 0 3.6 1.2 5 3 1.4-1.8 2.9-3 5-3 3.5 0 5.4 3.5 4.3 6.6-1.8 4.8-9.3 9.4-9.3 9.4z"/>',
};
function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name]; // constant markup, never user data
  return s;
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

// ---------- errors ----------
// Failures show as one line of text at the top of the page; successes are silent.
let errorTimer = null;
function showError(msg) {
  document.querySelectorAll(".page-error").forEach((e) => e.remove());
  clearTimeout(errorTimer);
  const el = h("p", { class: "page-error", role: "alert", text: msg });
  view().prepend(el);
  errorTimer = setTimeout(() => el.remove(), 6000);
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
      sec("Why", (card.why || []).map((w) => h("li", { text: w }))),
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

async function loadDeck(opts = {}) {
  try {
    deck.data = await api("/api/deck");
  } catch (e) { return renderError(e); }
  deck.cards = deck.data.cards;
  if (deck.frontId) {
    const i = deck.cards.findIndex((c) => c.id === deck.frontId);
    if (i > 0) deck.cards.unshift(deck.cards.splice(i, 1)[0]);
    deck.frontId = null;
  }
  renderDeck(opts);
  if (deck.data.running || (!deck.cards.length)) poll(() => route() === "deck" && loadDeck(), deck.data.running ? 5000 : 60000);
}

function renderDeck(opts = {}) {
  const v = view();
  v.replaceChildren();
  if (!deck.cards.length) {
    const running = deck.data && deck.data.running;
    const last = deck.data && deck.data.last_run;
    v.append(h("div", { class: "empty" },
      running
        ? [h("h2", { text: "Dealing your deck" })]
        : [h("h2", { text: "All caught up" }), h("p", { text: `Next deck at ${readyLabel(deck.data ? deck.data.ready_by : "07:00")}` })],
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
    if (idx === 0) attachDrag(el, card); else el.setAttribute("aria-hidden", "true");
    stack.append(el);
  });
  v.append(h("div", { class: "deck-wrap" },
    stack,
    h("div", { class: "controls" },
      h("button", { class: "round undo", type: "button", title: "Undo (u)", "aria-label": "Undo", onclick: undo }, icon("undo")),
      h("button", { class: "round pass", type: "button", title: "Dismiss (←)", "aria-label": "Dismiss", onclick: () => commit("left") }, icon("pass")),
      h("button", { class: "round note", type: "button", title: "Add a note (↑)", "aria-label": "Add a note", onclick: () => noteSheet(deck.cards[0]) }, icon("note")),
      h("button", { class: "round save", type: "button", title: "Save (→)", "aria-label": "Save", onclick: () => commit("right") }, icon("save")),
    ),
  ));
  const els = [...stack.querySelectorAll(".card")].reverse(); // top first
  els.forEach(fitCard);
  if (opts.enter) enterFrom(els, opts.enter);
}

// Shrink type step by step until the card's content fits; drop the reasons as a last resort
// (they're also in the details sheet).
const FIT_STEPS = [
  // [title px, pitch px, reason px, extra classes]
  [34, 18, 14.5, ""],
  [31, 17, 14, ""],
  [28, 16, 13.5, "clamp-why"],
  [26, 15.5, 13, "clamp-why clamp-pitch"],
  [24, 15, 13, "clamp-why-1 clamp-pitch"],
  [22, 14.5, 12.5, "clamp-why-1 clamp-pitch"],
];
const FIT_CLASSES = ["clamp-why", "clamp-why-1", "clamp-pitch", "no-why"];
function fitCard(el) {
  for (const [t, p, w, extra] of FIT_STEPS) {
    el.classList.remove(...FIT_CLASSES);
    if (extra) el.classList.add(...extra.split(" "));
    el.style.setProperty("--title-size", t + "px");
    el.style.setProperty("--pitch-size", p + "px");
    el.style.setProperty("--why-size", w + "px");
    if (el.scrollHeight <= el.clientHeight + 1) return;
  }
  el.classList.add("no-why");
}

function flingTransform(direction) {
  const x = direction === "right" ? window.innerWidth : -window.innerWidth;
  return `translate(${x}px, 40px) rotate(${direction === "right" ? 24 : -24}deg)`;
}

// Undo: the card flies back in from the side it left; the cards behind step back.
function enterFrom([top, nxt, thd], direction) {
  const all = [top, nxt, thd].filter(Boolean);
  all.forEach((el) => el.classList.add("no-anim"));
  top.style.transform = flingTransform(direction);
  if (nxt) nxt.classList.remove("next");
  if (thd) thd.classList.replace("third", "next");
  void top.offsetWidth; // commit the start state
  requestAnimationFrame(() => {
    all.forEach((el) => el.classList.remove("no-anim"));
    top.style.transform = "";
    if (nxt) nxt.classList.add("next");
    if (thd) thd.classList.replace("next", "third");
  });
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (route() === "deck" && !deck.busy && deck.cards.length) renderDeck(); }, 150);
});

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
      note ? h("span", { class: "note-mark", text: "Note attached" }) : null,
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
  el.style.transform = flingTransform(direction);
  el.style.opacity = "0";
  // The cards behind move up at the same time, so nothing pops in afterwards.
  const nxt = document.querySelector(".stack .card.next");
  const thd = document.querySelector(".stack .card.third");
  if (nxt) nxt.classList.remove("next");
  if (thd) thd.classList.replace("third", "next");
  return new Promise((r) => setTimeout(r, 300));
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
    if (direction === "right") refreshSavedCount();
  } catch (e) {
    showError(e.message);
    await loadDeck();
  } finally {
    deck.busy = false;
  }
}

async function neverLike(card) {
  try {
    await api(`/api/cards/${card.id}/never`, { method: "POST" });
    loadHistory();
  } catch (e) { showError(e.message); }
}

async function undo() {
  if (deck.busy) return;
  deck.busy = true;
  try {
    const r = await api("/api/undo", { method: "POST" });
    deck.frontId = r.card_id;
    if (route() !== "deck") {
      location.hash = "#/";
      return;  // the route change renders the deck
    }
    await loadDeck({ enter: r.was === "liked" ? "right" : "left" });
    refreshSavedCount();
  } catch (e) {
    showError(e.message);
  } finally {
    deck.busy = false;
  }
}

function noteSheet(card) {
  if (!card) return;
  sheet((close) => {
    const ta = h("textarea", { id: "note", maxlength: "4000", placeholder: "Note", "aria-label": "Note" });
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
      ta,
      h("div", { class: "actions" },
        h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel"),
        h("button", { class: "btn", type: "button", onclick: attach }, "Attach note"),
        h("button", { class: "btn", type: "button", onclick: () => go("left") }, "Dismiss"),
        h("button", { class: "btn primary", type: "button", onclick: () => go("right") }, "Save"),
      ),
    );
  });
}

async function runNow() {
  try {
    await api("/api/runs", { method: "POST" });
    loadDeck();
  } catch (e) { showError(e.message); }
}

// ---------- saved ----------
async function loadSaved() {
  let data;
  try { data = await api("/api/saved"); } catch (e) { return renderError(e); }
  const labels = { queued: "Queued", writing: "Writing spec", pr_open: "PR open", failed: "Failed" };
  const v = view();
  v.replaceChildren(h("h2", { class: "page-title", text: "Saved" }));
  if (!data.cards.length) v.append(h("p", { class: "muted", text: "Nothing saved yet." }));
  const list = h("div", { class: "list" });
  for (const c of data.cards) {
    list.append(h("div", { class: "item" },
      kindBadgeSmall(c),
      h("h3", { text: c.title }),
      h("p", { text: c.pitch }),
      c.note ? h("div", { class: "note", text: c.note }) : null,
      h("div", { class: "meta" },
        h("span", { class: `chip ${c.spec_status || ""}`, text: labels[c.spec_status] || "—" }),
        c.pr_url ? safeLink(c.pr_url, "View PR") : null,
        c.spec_status === "failed" ? h("button", { class: "btn", type: "button", onclick: async () => { try { await api(`/api/specs/${c.spec_id}/retry`, { method: "POST" }); loadSaved(); } catch (e) { showError(e.message); } } }, "Retry") : null,
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
        c.pr_url ? safeLink(c.pr_url, "View PR") : null,
        h("button", { class: "btn ghost", type: "button", onclick: () => detailSheet(c) }, "Details"),
        c.status === "dismissed" ? h("button", { class: "btn", type: "button", onclick: async () => {
          try { await api(`/api/cards/${c.id}/resave`, { method: "POST", body: {} }); refreshSavedCount(); loadHistory(); } catch (e) { showError(e.message); }
        } }, "Save instead") : null,
        c.status === "dismissed" && !c.never ? h("button", { class: "btn ghost", type: "button", onclick: () => neverLike(c) }, "Never like this") : null,
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

  // Demo mode
  const demoCb = h("input", { type: "checkbox", "aria-label": "Demo mode" });
  demoCb.checked = !!s.demo_mode;
  demoCb.addEventListener("change", async () => {
    try {
      await api("/api/settings", { method: "PUT", body: { demo_mode: demoCb.checked } });
      deck.notes.clear();
      refreshSavedCount();
      loadSettings();
    } catch (e) { demoCb.checked = !demoCb.checked; showError(e.message); }
  });
  v.append(h("div", { class: "section demo-section" },
    h("h3", {}, h("span", { class: "nowrap", text: "Demo mode" }), h("label", { class: "switch" }, demoCb, h("span", {}))),
    s.demo_mode ? h("div", { class: "mt12" }, h("button", { class: "btn", type: "button", onclick: async () => {
      try { await api("/api/demo/reset", { method: "POST" }); deck.notes.clear(); refreshSavedCount(); loadSettings(); } catch (e) { showError(e.message); }
    } }, "Reset demo")) : null,
  ));

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
    h("div", { class: "mt12" }, h("label", { for: "maxrepos", text: "Repos to analyse" }), maxRepos),
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
  if (!repos.repos.length) repoBox.append(h("p", { class: "muted small", text: "No repos synced." }));
  for (const r of repos.repos) {
    const cb = h("input", { type: "checkbox", "aria-label": `Include ${r.full_name}` });
    cb.checked = !r.excluded;
    cb.addEventListener("change", async () => {
      try { await api(`/api/repos/${r.id}`, { method: "PUT", body: { excluded: !cb.checked } }); } catch (e) { cb.checked = !cb.checked; showError(e.message); }
    });
    const tags = [r.private ? "private" : "public", r.fork ? "fork" : null, r.archived ? "archived" : null, r.pushed_at ? "pushed " + fmtDate(r.pushed_at) : null].filter(Boolean).join(" · ");
    repoBox.append(h("div", { class: "repo" },
      h("div", { class: "name" }, h("b", { text: r.full_name }), h("span", { text: tags })),
      h("label", { class: "switch" }, cb, h("span", {}))));
  }
  const syncBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    syncBtn.disabled = true; syncBtn.textContent = "Syncing…";
    try { const r = await api("/api/repos/sync", { method: "POST" }); loadSettings(); }
    catch (e) { showError(e.message); syncBtn.disabled = false; syncBtn.textContent = "Sync"; }
  } }, "Sync");
  v.append(h("div", { class: "section" }, h("h3", {}, `Repos (${repos.repos.filter((r) => !r.excluded).length}/${repos.repos.length} included)`, syncBtn), repoBox));

  // Never rules
  const ruleBox = h("div", {});
  if (!rules.rules.length) ruleBox.append(h("p", { class: "muted small", text: "None." }));
  for (const r of rules.rules) {
    ruleBox.append(h("div", { class: "rule" },
      h("span", { class: "t", text: r.text }),
      h("button", { class: "iconbtn", type: "button", title: "Edit", "aria-label": "Edit rule", onclick: () => editRule(r) }, "Edit"),
      h("button", { class: "iconbtn", type: "button", title: "Remove", "aria-label": "Remove rule", onclick: async () => { try { await api(`/api/never-rules/${r.id}`, { method: "DELETE" }); loadSettings(); } catch (e) { showError(e.message); } } }, "Remove")));
  }
  v.append(h("div", { class: "section" }, h("h3", { text: "Never like this" }), ruleBox));

  // Profile
  v.append(h("div", { class: "section" },
    h("h3", {}, "What Cinder thinks you like", h("button", { class: "btn ghost danger", type: "button", onclick: async () => {
      if (!confirm("Reset the preference profile? Cinder will forget what it has learned from your swipes so far.")) return;
      try { await api("/api/profile", { method: "DELETE" }); loadSettings(); } catch (e) { showError(e.message); }
    } }, "Reset")),
    profile.markdown ? profileEl(profile.markdown) : h("p", { class: "muted small", text: "Nothing learned yet." }),
  ));

  v.append(h("div", { class: "section" },
    h("h3", {}, "Account", h("button", { class: "btn", type: "button", onclick: async () => { await api("/auth/logout", { method: "POST" }).catch(() => {}); location.href = "/login"; } }, "Sign out"))));
}

// Minimal markdown for the profile: "## " headings and "- " lists; everything as plain text.
function profileEl(md) {
  const box = h("div", { class: "profile" });
  let list = null;
  for (const raw of md.split("\n")) {
    const line = raw.trim();
    if (!line) { list = null; continue; }
    const head = line.match(/^#{1,6}\s+(.*)$/);
    const item = line.match(/^[-*]\s+(.*)$/);
    const clean = (t) => t.replace(/\*\*(.+?)\*\*/g, "$1").replace(/(^|\s)[*_](.+?)[*_](?=\s|$|[.,;:])/g, "$1$2");
    if (head) { list = null; box.append(h("h4", { text: clean(head[1]) })); }
    else if (item) { if (!list) { list = h("ul", {}); box.append(list); } list.append(h("li", { text: clean(item[1]) })); }
    else { list = null; box.append(h("p", { text: clean(line) })); }
  }
  return box;
}

function editRule(rule) {
  sheet((close) => {
    const inp = h("input", { type: "text", id: "rule", maxlength: "300" });
    inp.value = rule.text;
    return h("div", {},
      h("h3", { text: "Edit rule" }),
      h("label", { for: "rule", text: "Rule" }), inp,
      h("div", { class: "actions" },
        h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel"),
        h("button", { class: "btn primary", type: "button", onclick: async () => {
          try { await api(`/api/never-rules/${rule.id}`, { method: "PUT", body: { text: inp.value } }); close(); loadSettings(); } catch (e) { showError(e.message); }
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
    el.replaceChildren(n ? ` (${n})` : "");
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
