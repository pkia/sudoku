/* Our Sudoku — NYT-identical gameplay (light theme, meaning-based colors) */
"use strict";

const $ = (sel, el) => (el || document).querySelector(sel);
const $$ = (sel, el) => Array.from((el || document).querySelectorAll(sel));
const LS = {
  get(k, d) { try { const v = localStorage.getItem("sud." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("sud." + k, JSON.stringify(v)); } catch {} },
};

/* ---------- NYT gameboard settings (per device) ---------- */
const SETTINGS_DEFAULTS = {
  check: true,
  autoCandidate: false,
  errorCounter: true,
  showTimer: true,
  hlConflicts: true,
  hlRowCol: true,
  hlBox: true,
  hlSame: true,
  sound: true,
};
let settings = Object.assign({}, SETTINGS_DEFAULTS, LS.get("settings", {}));
function saveSettings() { LS.set("settings", settings); }

const SETTING_META = [
  { key: "check", label: "Check guesses when entered" },
  { key: "autoCandidate", label: "Start in auto candidate mode" },
  { key: "errorCounter", label: "Show error counter" },
  { key: "showTimer", label: "Show timer" },
  { key: "hlConflicts", label: "Highlight conflicts" },
  { key: "hlRowCol", label: "Highlight row and column" },
  { key: "hlBox", label: "Highlight box" },
  { key: "hlSame", label: "Highlight identical numbers" },
  { key: "sound", label: "Play sound on solve" },
];

const app = $("#app");
let toastTimer = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtClock(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}
function fmtAgo(ts) {
  if (!ts) return "";
  const d = Date.now() - ts * 1000;
  const min = Math.floor(d / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "short" });
}
function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

/* ---------- sound ---------- */
let audioCtx = null;
function playJingle() {
  if (!settings.sound) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    const now = audioCtx.currentTime;
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => {
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.type = "sine";
      o.frequency.value = f;
      g.gain.setValueAtTime(0, now + i * 0.12);
      g.gain.linearRampToValueAtTime(0.2, now + i * 0.12 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.12 + 0.5);
      o.connect(g).connect(audioCtx.destination);
      o.start(now + i * 0.12);
      o.stop(now + i * 0.12 + 0.55);
    });
  } catch {}
}

/* ---------- net ---------- */
async function api(path, opts) {
  const token = LS.get("token");
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}), ...(opts && opts.headers) },
  });
  if (res.status === 401) { goWelcome(); throw new Error("signed out"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "something went wrong");
  return data;
}

/* ---------- identity ---------- */
function me() { return LS.get("player", null); }
let ROSTER = ["one", "two"];
function partner() { return ROSTER.find((p) => p !== me()) || ROSTER[0]; }
function signedIn() { return !!(me() && LS.get("token")); }

/* ---------- routing ---------- */
let view = null;
function setView(html, cls) {
  app.innerHTML = html;
  app.firstElementChild.className = "screen " + (cls || "");
  view = { unbind: [] };
  return app.firstElementChild;
}
function onUnload(fn) { if (view) view.unbind.push(fn); }
function unloadView() {
  if (view) { view.unbind.forEach((f) => { try { f(); } catch {} }); view = null; }
}

/* ---------- welcome ---------- */
function goWelcome() {
  unloadView();
  const el = setView(`
    <div class="welcome">
      <div class="logo" aria-hidden="true"><span>5</span><span>3</span><span>·</span><span>6</span><span>·</span><span>·</span><span>·</span><span>9</span><span>8</span></div>
      <h1 class="wordmark">Our Sudoku</h1>
      <p class="tag">our little puzzle place 💕</p>
      <div class="passcard">
        <label for="pc0">Our secret code</label>
        <div class="passcode" id="pcode">
          ${[0, 1, 2, 3].map((i) => `<input id="pc${i}" inputmode="numeric" autocomplete="off" maxlength="1" aria-label="digit ${i + 1}">`).join("")}
        </div>
        <div class="who">
          ${ROSTER.map((p, i) => `<button data-p="${p}"><span class="em">${cap(p).slice(0, 1)}</span>${cap(p)}</button>`).join("")}
        </div>
        <div class="err" id="werr"></div>
        <button class="btn-primary" id="enter" disabled>Enter</button>
        <div class="hint">Just us two. No accounts, ever.</div>
      </div>
    </div>`);
  const digits = $$("#pcode input");
  const err = $("#werr");
  const enterBtn = $("#enter");
  let picked = null;
  $$(".who button", el).forEach((b) => {
    b.addEventListener("click", () => {
      picked = b.dataset.p;
      $$(".who button").forEach((x) => (x.className = ""));
      b.classList.add("sel-" + ROSTER.indexOf(picked));
      refresh();
    });
  });
  digits.forEach((d, i) => {
    d.addEventListener("input", () => {
      d.value = d.value.replace(/\D/g, "").slice(0, 1);
      if (d.value && i < 3) digits[i + 1].focus();
      refresh();
    });
    d.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && !d.value && i > 0) { digits[i - 1].focus(); digits[i - 1].value = ""; }
      if (e.key === "Enter") tryEnter();
    });
  });
  function ready() { return picked && digits.every((d) => d.value !== ""); }
  function refresh() { enterBtn.disabled = !ready(); err.textContent = ""; }
  async function tryEnter() {
    if (!ready()) return;
    enterBtn.disabled = true;
    err.textContent = "";
    try {
      const r = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passcode: digits.map((d) => d.value).join(""), player: picked }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail === "too many attempts, try later" ? "Too many tries — wait a few minutes" : "That code isn't right");
      LS.set("token", data.token);
      LS.set("player", data.player);
      goHome();
    } catch (e) {
      err.textContent = e.message;
      digits.forEach((d) => (d.value = ""));
      digits[0].focus();
      enterBtn.disabled = false;
    }
  }
  enterBtn.addEventListener("click", tryEnter);
  digits[0].focus();
}

/* ---------- home ---------- */
let lastHome = null;
function goHome() {
  unloadView();
  const el = setView(`
    <div>
      <div class="homehead">
        <h1 class="wordmark">Our Sudoku</h1>
        <div style="display:flex;align-items:center;gap:12px">
          <div class="me-chip"><span class="dot" id="pdot"></span><span id="pstat"></span></div>
          <button class="gear" id="home-gear" aria-label="settings">⚙️</button>
        </div>
      </div>
      <div class="homesub" id="greet"></div>

      <div class="sect" id="s-continue" hidden>
        <div class="sect-title">Playing together</div>
        <div id="continue-cards"></div>
      </div>

      <div class="sect" id="s-join" hidden>
        <div class="sect-title" id="join-title"></div>
        <div id="join-cards"></div>
      </div>

      <div class="sect" id="s-open" hidden>
        <div class="sect-title" id="open-title"></div>
        <div id="open-cards"></div>
      </div>

      <div class="sect" id="s-solo" hidden>
        <div class="sect-title">Solo</div>
        <div id="solo-cards"></div>
      </div>

      <div class="sect">
        <button class="newbtn big" id="new-coop">✚&ensp;New game together</button>
        <div class="solorow">
          <button class="newbtn" id="new-solo">Solo · new</button>
        </div>
      </div>

      <div class="sect" id="s-recent" hidden>
        <div class="sect-title">Our games</div>
        <div class="hist" id="recent-cards"></div>
      </div>
    </div>`);
  const render = (data) => {
    lastHome = data;
    const greet = $("#greet", el);
    const hour = new Date().getHours();
    const hi = hour < 5 ? "Up late, hm?" : hour < 12 ? "Good morning, sunshine ☀️" : hour < 18 ? "Happy afternoon" : "Cozy evening, eh?";
    greet.textContent = `${hi}, ${cap(me())}.`;

    const dot = $("#pdot", el), pstat = $("#pstat", el);
    if (data.partner_online) { dot.classList.add("on"); pstat.textContent = `${cap(partner())} online`; }
    else { dot.classList.remove("on"); pstat.textContent = `${cap(partner())} offline`; }

    const items = [];
    if (data.continue) items.push(data.continue);
    items.push(...(data.also_active || []));
    const cont = $("#s-continue", el);
    cont.hidden = items.length === 0;
    if (!cont.hidden) {
      $("#continue-cards", el).innerHTML = items.map((g) => coopActiveCard(g)).join("");
      $$("#continue-cards .card", el).forEach((c, i) => c.addEventListener("click", () => openGame(items[i].id, false)));
    }

    const join = $("#s-join", el);
    join.hidden = data.joinable.length === 0;
    if (!join.hidden) {
      $("#join-title", el).textContent = `${cap(partner())} made these — join in`;
      $("#join-cards", el).innerHTML = data.joinable.map((g) => joinCard(g)).join("");
      $$("#join-cards .card", el).forEach((c, i) => c.addEventListener("click", () => openGame(data.joinable[i].id, true)));
    }

    const openS = $("#s-open", el);
    openS.hidden = data.my_open.length === 0;
    if (!openS.hidden) {
      $("#open-title", el).textContent = `Waiting for ${cap(partner())}`;
      $("#open-cards", el).innerHTML = data.my_open.map((g) => openCard(g)).join("");
      $$("#open-cards .card", el).forEach((c, i) => c.addEventListener("click", () => openGame(data.my_open[i].id, false)));
    }

    const soloS = $("#s-solo", el);
    const soloGames = data.solo_games || [];
    soloS.hidden = soloGames.length === 0;
    if (!soloS.hidden) {
      $("#solo-cards", el).innerHTML = soloGames.map((g) => soloCard(g)).join("");
      $$("#solo-cards .card", el).forEach((c, i) => c.addEventListener("click", () => openGame(soloGames[i].id, false)));
    }

    const rec = data.recent || [];
    const recS = $("#s-recent", el);
    recS.hidden = rec.length === 0;
    if (!recS.hidden) {
      $("#recent-cards", el).innerHTML = rec.map((g) => histCard(g)).join("");
      $$("#recent-cards .h", el).forEach((c, i) => c.addEventListener("click", () => openGame(rec[i].id, false)));
    }
  };

  async function load() {
    try { render(await api("/api/home")); } catch (e) { if (String(e.message) !== "signed out") toast(e.message); }
  }
  load();
  const homePoll = setInterval(load, 15000);
  onUnload(() => clearInterval(homePoll));

  $("#new-coop", el).addEventListener("click", () => newGameSheet("coop"));
  $("#new-solo", el).addEventListener("click", () => newGameSheet("solo"));
  $("#home-gear", el).addEventListener("click", () => settingsSheet());
}

function badge(g) {
  if (g.state === "completed") return '<span class="badge">Solved</span>';
  if (g.state === "active" && g.running) return '<span class="badge live">Live</span>';
  return '<span class="badge">Paused</span>';
}
function coopActiveCard(g) {
  return `<button class="card" data-g="${g.id}">
    <div class="row1"><span class="diff">${cap(g.difficulty)}</span>${badge(g)}</div>
    <div class="meta">${g.progress}% solved · ${fmtClock(g.elapsed_ms)} so far · last played ${fmtAgo(g.last_activity)}</div>
    <div class="prog"><i style="width:${g.progress}%"></i></div>
    <div class="cta">Continue</div>
  </button>`;
}
function joinCard(g) {
  return `<button class="card" data-g="${g.id}">
    <div class="waiting-em">💌</div>
    <div class="row1"><span class="diff">${cap(g.difficulty)}</span><span class="badge go">Join</span></div>
    <div class="meta">${cap(g.creator)} made this ${fmtAgo(g.created_at)} — waiting for you</div>
    <div class="cta">Join</div>
  </button>`;
}
function openCard(g) {
  return `<button class="card" data-g="${g.id}">
    <div class="row1"><span class="diff">${cap(g.difficulty)}</span><span class="badge">Waiting</span></div>
    <div class="meta">Waiting for ${cap(partner())} to join · created ${fmtAgo(g.created_at)}</div>
    <div class="cta ghost">Open board</div>
  </button>`;
}
function soloCard(g) {
  return `<button class="card" data-g="${g.id}">
    <div class="row1"><span class="diff">${cap(g.difficulty)}</span>${badge(g)}</div>
    <div class="meta">${g.progress}% solved · ${fmtClock(g.elapsed_ms)} so far · last played ${fmtAgo(g.last_activity)}</div>
    <div class="prog"><i style="width:${g.progress}%"></i></div>
    <div class="cta">Continue</div>
  </button>`;
}
function histCard(g) {
  const who = g.kind === "coop" ? "Solved together" : `Solo · ${cap(g.creator)}`;
  return `<div class="h" data-g="${g.id}">
    <div class="d">${cap(g.difficulty)}</div>
    <div class="m">${who}</div>
    <div class="t"><b>${fmtClock(g.elapsed_ms)}</b><br>${fmtAgo(g.completed_at || g.last_activity)}</div>
  </div>`;
}

/* ---------- new game sheet ---------- */
function newGameSheet(kind) {
  const wrap = document.createElement("div");
  wrap.className = "sheet-wrap";
  wrap.innerHTML = `<div class="sheet">
    <div class="grab"></div>
    <div class="sheet-head">
      <button class="sheet-back" id="sheet-back" aria-label="Back">‹</button>
      <h2>${kind === "coop" ? "New game together" : "New solo game"}</h2>
      <span class="sheet-head-sp"></span>
    </div>
    <div class="lbl">Difficulty</div>
    <div class="diffrow">
      ${["easy", "medium", "hard", "expert"].map((d, i) => `<button data-d="${d}" class="${i === 1 ? "on" : ""}">${cap(d)}</button>`).join("")}
    </div>
    <button class="btn-primary" id="mk" style="margin-top:20px">Create game</button>
  </div>`;
  document.body.appendChild(wrap);
  let diff = "medium";
  $$(".diffrow button", wrap).forEach((b) => b.addEventListener("click", () => {
    diff = b.dataset.d;
    $$(".diffrow button", wrap).forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
  }));
  const close = () => wrap.remove();
  $("#sheet-back", wrap).addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  $("#mk", wrap).addEventListener("click", async () => {
    const btn = $("#mk", wrap);
    btn.disabled = true;
    btn.textContent = "Making puzzle…";
    try {
      const r = await api("/api/games", { method: "POST", body: JSON.stringify({ kind, difficulty: diff }) });
      close();
      openGame(r.game.id, false);
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Create game";
      toast(e.message);
    }
  });
}

/* ---------- settings sheet (NYT gameboard settings) ---------- */
function settingsSheet() {
  const wrap = document.createElement("div");
  wrap.className = "sheet-wrap";
  wrap.innerHTML = `<div class="sheet">
    <div class="grab"></div>
    <div class="sheet-head">
      <button class="sheet-back" id="sheet-back" aria-label="Back">‹</button>
      <h2>Settings</h2>
      <span class="sheet-head-sp"></span>
    </div>
    <div class="lbl">Gameboard settings</div>
    <div class="setlist">
      ${SETTING_META.map((s) => `
        <label class="setrow" data-k="${s.key}">
          <span class="setname">${s.label}</span>
          <span class="switch"><input type="checkbox" data-k="${s.key}" ${settings[s.key] ? "checked" : ""}><i></i></span>
        </label>`).join("")}
    </div>
    <div class="hint" style="margin-top:14px">Settings apply on this device, live.</div>
  </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  $("#sheet-back", wrap).addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  $$("input[type=checkbox]", wrap).forEach((cb) => {
    cb.addEventListener("change", () => {
      settings[cb.dataset.k] = cb.checked;
      saveSettings();
      if (cb.dataset.k === "autoCandidate" && gameCtx) {
        gameCtx.mode = cb.checked ? "auto" : "normal";
      }
      if (gameCtx && gameCtx.game) render();
    });
  });
}

/* ---------- game ---------- */
let gameCtx = null;
function openGame(gid, viaJoin) {
  unloadView();
  const el = setView(`<div class="game" id="gd"></div>`, "");
  gameCtx = {
    gid, ws: null, closed: false, sel: null, mode: settings.autoCandidate ? "auto" : "normal",
    game: null, undoStack: [], cellsEls: [], prevCells: {},
    timer: { base: 0, running: false, at: 0 }, online: [], pendingDigit: null,
    reconnectTimer: null,
  };
  const c = gameCtx;
  el.innerHTML = `
    <div class="ghead">
      <button class="back" id="bk" aria-label="home">‹</button>
      <div class="mid">
        <div class="tl"><span id="gdiff"></span><span class="sep">·</span><span id="gkind"></span></div>
        <div class="sub" id="gmeta"></div>
      </div>
      <div style="text-align:right">
        <div class="timer" id="gtimer">0:00</div>
        <div class="presence" id="pres"></div>
      </div>
      <button class="gear" id="gear" aria-label="settings">⚙️</button>
      <button class="delbtn" id="del-game" aria-label="delete game">🗑</button>
    </div>
    <div id="gstatus"></div>
    <div class="boardwrap"><div class="board" id="board"></div></div>
    <div class="pad">
      <div class="bar">
        <button class="barbtn" id="t-undo" type="button">↩︎<span>Undo</span></button>
        <div class="numrow" id="numrow"></div>
        <button class="barbtn" id="t-erase" type="button">⌫<span>Erase</span></button>
      </div>
      <div class="row2">
        <button class="modechip ${gameCtx.mode === "normal" ? "on" : ""}" id="m-normal" type="button">Normal</button>
        <button class="modechip ${gameCtx.mode === "notes" ? "on" : ""}" id="m-cand" type="button">Candidate</button>
        <button class="modechip ${gameCtx.mode === "auto" ? "on" : ""}" id="m-auto" type="button">Auto Candidate</button>
        <button class="barbtn small" id="t-hint" type="button">✦<span>Hint</span></button>
      </div>
    </div>`;

  buildBoard(el);
  buildPad(el);
  bindTools(el);
  $("#bk", el).addEventListener("click", () => goHome());
  $("#gear", el).addEventListener("click", () => settingsSheet());
  $("#del-game", el).addEventListener("click", () => confirmDeleteSheet());
  onUnload(() => {
    c.closed = true;
    if (c.reconnectTimer) clearTimeout(c.reconnectTimer);
    try { if (c.ws) c.ws.close(); } catch {}
  });
  connect(gid, viaJoin);
}

function buildBoard(el) {
  const board = $("#board", el);
  const c = gameCtx;
  for (let i = 0; i < 81; i++) {
    const d = document.createElement("div");
    d.className = "cell";
    const col = i % 9, row = Math.floor(i / 9);
    if (col % 3 === 2 && col !== 8) d.classList.add("br3");
    if (row % 3 === 2 && row !== 8) d.classList.add("bb3");
    d.dataset.i = i;
    board.appendChild(d);
    c.cellsEls.push(d);
    d.addEventListener("click", () => tapCell(i));
  }
}
function buildPad(el) {
  const row = $("#numrow", el);
  for (let v = 1; v <= 9; v++) {
    const k = document.createElement("button");
    k.type = "button";
    k.className = "key";
    k.dataset.v = v;
    k.textContent = String(v);
    k.addEventListener("click", () => pressDigit(v));
    row.appendChild(k);
  }
}
function bindTools(el) {
  $("#t-erase", el).addEventListener("click", () => doErase());
  $("#t-undo", el).addEventListener("click", () => doUndo());
  $("#t-hint", el).addEventListener("click", () => doHint());
  $("#m-normal", el).addEventListener("click", () => { gameCtx.mode = "normal"; render(); });
  $("#m-cand", el).addEventListener("click", () => { gameCtx.mode = "notes"; render(); });
  $("#m-auto", el).addEventListener("click", () => { gameCtx.mode = "auto"; render(); });
}

function cellVal(g, i) {
  if (g.puzzle[i] !== "0") return +g.puzzle[i];
  const cell = g.cells[String(i)];
  return cell ? cell.v : 0;
}
function autoCandidates(g) {
  const out = {};
  for (let i = 0; i < 81; i++) {
    if (g.puzzle[i] !== "0" || g.cells[String(i)]) continue;
    const used = new Set();
    const r = Math.floor(i / 9), col = i % 9;
    const br = Math.floor(r / 3) * 3, bc = Math.floor(col / 3) * 3;
    for (let k = 0; k < 9; k++) {
      used.add(cellVal(g, r * 9 + k));
      used.add(cellVal(g, k * 9 + col));
      used.add(cellVal(g, (br + Math.floor(k / 3)) * 9 + bc + (k % 3)));
    }
    const cands = [];
    for (let d = 1; d <= 9; d++) if (!used.has(d)) cands.push(d);
    if (cands.length) out[i] = cands;
  }
  return out;
}
function conflicts(g) {
  const bad = new Set();
  const units = [];
  for (let r = 0; r < 9; r++) units.push(Array.from({ length: 9 }, (_, k) => r * 9 + k));
  for (let col = 0; col < 9; col++) units.push(Array.from({ length: 9 }, (_, k) => k * 9 + col));
  for (let br = 0; br < 9; br += 3) for (let bc = 0; bc < 9; bc += 3)
    units.push(Array.from({ length: 9 }, (_, k) => (br + Math.floor(k / 3)) * 9 + bc + (k % 3)));
  for (const unit of units) {
    const seen = {};
    for (const i of unit) {
      const v = cellVal(g, i);
      if (!v || g.puzzle[i] !== "0") continue;
      if (seen[v] !== undefined) { bad.add(i); bad.add(seen[v]); }
      else seen[v] = i;
    }
  }
  return bad;
}

function tapCell(i) {
  const c = gameCtx;
  const g = c.game;
  if (!g) return;
  if (g.puzzle[i] !== "0" && c.pendingDigit == null) { c.sel = i; render(); return; }
  c.sel = i;
  if (c.pendingDigit != null) {
    const v = c.pendingDigit;
    c.pendingDigit = null;
    flashKey(null);
    placeDigit(v);
  } else {
    render();
  }
}

function firstEmpty(g) {
  for (let i = 0; i < 81; i++) if (!cellVal(g, i)) return i;
  return 0;
}

function render() {
  const c = gameCtx;
  const g = c.game;
  if (!g) return;
  const el = $("#gd");
  if (!el) return;
  $("#gdiff", el).textContent = cap(g.difficulty);
  $("#gkind", el).textContent = g.kind === "coop" ? "Together" : "Solo";

  const tEl = $("#gtimer", el);
  tEl.style.visibility = settings.showTimer ? "visible" : "hidden";
  tEl.textContent = fmtClock(g.elapsed_ms);

  const metas = [];
  if (settings.errorCounter) {
    const mk = g.mistakes || {};
    if (g.kind === "coop") metas.push(`<span>✕ ${mk[me()] || 0}–${mk[partner()] || 0}</span>`);
    else metas.push(`<span>✕ ${mk[me()] || 0}</span>`);
  }
  if (g.kind === "coop" && g.state === "waiting") {
    metas.push(`<span class="m">·</span><span style="color:var(--green)">waiting for ${esc(cap(partner()))}…</span>`);
  }
  $("#gmeta", el).innerHTML = metas.join(" ");

  $("#m-normal", el).classList.toggle("on", c.mode === "normal");
  $("#m-cand", el).classList.toggle("on", c.mode === "notes");
  $("#m-auto", el).classList.toggle("on", c.mode === "auto");

  const pres = $("#pres", el);
  if (g.kind === "coop") {
    const on = c.online || [];
    pres.innerHTML = [me(), partner()].map((p) => {
      const onn = on.includes(p);
      return `<span class="p ${onn ? "on" : ""}"><i></i>${p === me() ? "you" : esc(cap(p))}</span>`;
    }).join("");
  } else pres.innerHTML = "";

  c.timer.base = g.elapsed_ms;
  c.timer.running = g.running && g.state !== "completed" && settings.showTimer;
  c.timer.at = Date.now();

  const auto = c.mode === "auto" ? autoCandidates(g) : null;
  const bad = settings.hlConflicts ? conflicts(g) : new Set();
  for (let i = 0; i < 81; i++) {
    const d = c.cellsEls[i];
    const given = g.puzzle[i] !== "0";
    const cell = g.cells[String(i)];
    const manualNotes = g.notes[String(i)] || [];
    let html = "";
    if (given) html = `<span>${g.puzzle[i]}</span>`;
    else if (cell) {
      html = `<span>${cell.v}</span>`;
      const prev = c.prevCells[String(i)];
      if (!prev || prev.v !== cell.v) {
        d.classList.remove("pop");
        void d.offsetWidth;
        d.classList.add("pop");
      }
    } else if (manualNotes.length) {
      html = `<div class="notes">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<i>${manualNotes.includes(n) ? n : ""}</i>`).join("")}</div>`;
    } else if (auto && auto[i]) {
      html = `<div class="notes auto">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<i>${auto[i].includes(n) ? n : ""}</i>`).join("")}</div>`;
    }
    d.classList.toggle("given", given);
    d.classList.toggle("user", !given && !!cell);
    d.classList.toggle("unchecked", !given && !!cell && !settings.check);
    d.classList.toggle("wrong", !given && !!cell && settings.check && cell.wrong);
    d.classList.toggle("by-partner", !given && cell && cell.by && cell.by !== me());
    d.classList.toggle("conflict", bad.has(i));
    d.innerHTML = html;
  }
  c.prevCells = JSON.parse(JSON.stringify(g.cells));

  const selIdx = c.sel != null ? c.sel : firstEmpty(g);
  const val = cellVal(g, selIdx);
  const sr = Math.floor(selIdx / 9), sc = selIdx % 9;
  const sbr = Math.floor(sr / 3), sbc = Math.floor(sc / 3);
  for (let j = 0; j < 81; j++) {
    const d = c.cellsEls[j];
    const row = Math.floor(j / 9), col = j % 9;
    d.classList.toggle("sel", j === selIdx);
    const inRowCol = row === sr || col === sc;
    const inBox = Math.floor(row / 3) === sbr && Math.floor(col / 3) === sbc;
    const hl = (settings.hlRowCol && inRowCol) || (settings.hlBox && inBox);
    d.classList.toggle("hl", hl && j !== selIdx);
    d.classList.toggle("same", settings.hlSame && !!val && j !== selIdx && cellVal(g, j) === val);
  }

  const st = $("#gstatus", el);
  st.innerHTML = "";
  if (g.kind === "coop" && g.state === "waiting") {
    st.innerHTML = `<div class="statusline">Waiting for ${esc(cap(partner()))} — they'll see this game on their home screen.</div>`;
  }

  if (g.state === "completed") showDone(g);
  else if ($("#doneov")) $("#doneov").remove();
}

/* ---------- delete game ---------- */
function confirmDeleteSheet() {
  const c = gameCtx;
  if (!c || !c.game) return;
  const g = c.game;
  const wrap = document.createElement("div");
  wrap.className = "sheet-wrap";
  const label = g.kind === "coop"
    ? `Delete this ${g.difficulty} game? It disappears for both of you.`
    : `Delete this ${g.difficulty} solo game?`;
  wrap.innerHTML = `<div class="sheet">
    <div class="grab"></div>
    <div class="sheet-head">
      <button class="sheet-back" id="sheet-back" aria-label="Back">‹</button>
      <h2>Delete game</h2>
      <span class="sheet-head-sp"></span>
    </div>
    <div class="delnote">${label}</div>
    <div class="btns">
      <button class="danger" id="del-yes" type="button">Delete</button>
      <button class="homebtn" id="del-no" type="button">Keep playing</button>
    </div>
  </div>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  $("#sheet-back", wrap).addEventListener("click", close);
  $("#del-no", wrap).addEventListener("click", close);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  $("#del-yes", wrap).addEventListener("click", async () => {
    const btn = $("#del-yes", wrap);
    btn.disabled = true;
    btn.textContent = "Deleting…";
    try {
      await api(`/api/games/${g.id}`, { method: "DELETE" });
    } catch (e) {
      toast(e.message);
    }
    wrap.remove();
    goHome();
  });
}

/* ---------- websocket ---------- */
function connect(gid, viaJoin) {
  const c = gameCtx;
  if (c.closed) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = LS.get("token");
  const url = `${proto}://${location.host}/ws/games/${gid}?player=${me()}&token=${encodeURIComponent(token)}`;
  setStatus("Connecting…", true);
  const ws = new WebSocket(url);
  c.ws = ws;
  c.pongOk = false;
  ws.onopen = () => { c.pongOk = true; };
  ws.onmessage = (m) => {
    let msg;
    try { msg = JSON.parse(m.data); } catch { return; }
    if (msg.type === "pong") { c.pongOk = true; return; }
    if (msg.type === "state") {
      const first = !c.game;
      c.game = msg.game;
      setStatus("");
      render();
      if (first && viaJoin) toast("Joined — happy solving!");
    } else if (msg.type === "presence") {
      c.online = msg.online;
      if (c.game) render();
    } else if (msg.type === "error") {
      toast(msg.error);
    }
  };
  ws.onclose = (ev) => {
    if (c.closed) return;
    if (ev.code === 4401) { goWelcome(); return; }
    if (ev.code === 4404) { toast("That game is gone"); goHome(); return; }
    if (ev.code === 4408) { setStatus("Reconnecting…", true); c.reconnectTimer = setTimeout(() => { if (!c.closed) connect(gid, false); }, 1200); return; }
    setStatus("Reconnecting…", true);
    c.reconnectTimer = setTimeout(() => { if (!c.closed) connect(gid, false); }, 1200);
  };
}
/* watchdog: ping every 20s; if a pong is missing twice in a row, the socket is
   half-open (common after iOS backgrounding) — kill and reconnect */
setInterval(() => {
  const c = gameCtx;
  if (!c || c.closed || !c.ws) return;
  if (c.ws.readyState !== 1) return;
  if (c.pongOk === false) {
    try { c.ws.close(); } catch {}
    return;
  }
  c.pongOk = false;
  try { c.ws.send(JSON.stringify({ type: "ping" })); } catch {}
}, 20000);
function setStatus(txt, warn) {
  const st = $("#gstatus");
  if (!st) return;
  st.innerHTML = txt ? `<div class="statusline ${warn ? "warnline" : ""}">${txt}</div>` : "";
}
function send(obj) {
  const c = gameCtx;
  if (c && c.ws && c.ws.readyState === 1) c.ws.send(JSON.stringify(obj));
}

/* ---------- play (NYT input: tap digit, then cell — or cell, then digit) ---------- */
function pushUndo(i, g) {
  const c = gameCtx;
  const cell = g.cells[String(i)];
  const notes = g.notes[String(i)] || [];
  c.undoStack.push({ idx: i, value: cell ? cell.v : 0, notes: [...notes] });
  if (c.undoStack.length > 150) c.undoStack.shift();
}
function pressDigit(v) {
  const c = gameCtx;
  const g = c.game;
  if (!g || g.state === "completed") return;
  if (c.sel != null && (g.puzzle[c.sel] === "0" || c.mode === "notes")) {
    placeDigit(v);
  } else {
    c.pendingDigit = v;
    flashKey(v);
    toast(`Placing ${v} — tap a square`);
  }
}
function flashKey(v) {
  $$(".key").forEach((k) => k.classList.toggle("flash", String(k.dataset.v) === String(v)));
}
function placeDigit(v) {
  const c = gameCtx;
  const g = c.game;
  const i = c.sel;
  if (g.puzzle[i] !== "0") { toast("That one's a given"); return; }
  if (c.mode === "notes") {
    if (g.cells[String(i)]) { toast("Erase the number first"); return; }
    pushUndo(i, g);
    send({ type: "note", idx: i, digit: v });
    return;
  }
  pushUndo(i, g);
  send({ type: "set", idx: i, value: v });
}
function doErase() {
  const c = gameCtx;
  const g = c.game;
  if (!g || g.state === "completed") return;
  if (c.sel == null) { toast("Tap a square first"); return; }
  const i = c.sel;
  if (g.puzzle[i] !== "0") return;
  if (!g.cells[String(i)] && !(g.notes[String(i)] || []).length) return;
  pushUndo(i, g);
  send({ type: "erase", idx: i });
}
function doUndo() {
  const c = gameCtx;
  const g = c.game;
  if (!g || g.state === "completed") return;
  const last = c.undoStack.pop();
  if (!last) { toast("Nothing to undo"); return; }
  send({ type: "undo", idx: last.idx, value: last.value, notes: last.notes });
}
function doHint() {
  const c = gameCtx;
  const g = c.game;
  if (!g || g.state === "completed") return;
  if (c.sel == null || g.puzzle[c.sel] !== "0") { toast("Tap an empty square first"); return; }
  send({ type: "hint", idx: c.sel });
}

/* ---------- completion ---------- */
function showDone(g) {
  if ($("#doneov")) return;
  playJingle();
  // per-player stats from the final board: every placed cell carries "by"
  const stats = {};
  const givens = [...g.puzzle].filter((ch) => ch !== "0").length;
  for (const c of Object.values(g.cells)) {
    const p = c.by || "?";
    stats[p] = (stats[p] || 0) + 1;
  }
  const p0N = stats[ROSTER[0]] || 0;
  const p1N = stats[ROSTER[1]] || 0;
  const wrap = document.createElement("div");
  wrap.className = "done-wrap";
  wrap.id = "doneov";
  const coopStats = g.kind === "coop" ? `
    <div class="winstats">
      <div class="ws-row"><span class="ws-dot" style="background:var(--evan)"></span>${cap(ROSTER[0])}</span><b>${p0N}</b></div>
      <div class="ws-row"><span class="ws-dot" style="background:var(--sarah-lav)"></span>${cap(ROSTER[1])}</span><b>${p1N}</b></div>
    </div>` : "";
  const mk = g.mistakes || {};
  wrap.innerHTML = `<div class="done">
    <div class="hearts" aria-hidden="true">
      ${[...Array(10)].map((_, i) => `<span style="--d:${(i * 0.35).toFixed(2)}s;--x:${Math.round(Math.random() * 100)}%">💗</span>`).join("")}
    </div>
    <div class="tick">🧩</div>
    <h2>Solved!</h2>
    <div class="big-time">${fmtClock(g.elapsed_ms)}</div>
    ${coopStats}
    <div class="sub">${g.kind === "coop" ? `${cap(ROSTER[0])} & ${cap(ROSTER[1])} — what a team 💕` : "A lovely solo solve ✨"}</div>
    <div class="sub">Mistakes — you ${mk[me()] || 0} · ${cap(partner())} ${mk[partner()] || 0}</div>
    <div class="btns">
      <button class="again" id="dn-again" type="button">Play again</button>
      <button class="homebtn" id="dn-home" type="button">Home</button>
    </div>
  </div>`;
  document.body.appendChild(wrap);
  $("#dn-again", wrap).addEventListener("click", () => { wrap.remove(); newGameSheet(g.kind); });
  $("#dn-home", wrap).addEventListener("click", () => { wrap.remove(); goHome(); });
}

/* ---------- timer tick ---------- */
setInterval(() => {
  const c = gameCtx;
  if (!c || !c.timer.running) return;
  const el = $("#gtimer");
  if (el) el.textContent = fmtClock(c.timer.base + (Date.now() - c.timer.at));
}, 500);

/* ---------- boot ---------- */
(async () => {
  try {
    const r = await fetch("/api/who");
    const d = await r.json();
    if (Array.isArray(d.players) && d.players.length === 2) ROSTER = d.players;
  } catch {}
  if (signedIn()) goHome();
  else goWelcome();
})();
