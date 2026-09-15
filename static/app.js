/* Our Sudoku — app logic (no build step, no external requests) */
"use strict";

const $ = (sel, el) => (el || document).querySelector(sel);
const $$ = (sel, el) => Array.from((el || document).querySelectorAll(sel));
const LS = {
  get(k, d) { try { const v = localStorage.getItem("sud." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("sud." + k, JSON.stringify(v)); } catch {} },
};
const app = $("#app");
let toastTimer = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2400);
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
function partner() { return me() === "one" ? "two" : "one"; }
function signedIn() { return !!(me() && LS.get("token")); }
function signOut() {
  LS.set("token", null); LS.set("player", null);
  goWelcome();
}

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

/* ---------- welcome / sign-in ---------- */
function goWelcome() {
  unloadView();
  const el = setView(`
    <div class="welcome">
      <div class="logo" aria-hidden="true"><span>5</span><span>3</span><span>·</span><span>6</span><span>·</span><span>·</span><span>·</span><span>9</span><span>8</span></div>
      <h1 class="wordmark">Our Sudoku</h1>
      <p class="tag">A little puzzle place for two</p>
      <div class="passcard">
        <label for="pc0">Our secret code</label>
        <div class="passcode" id="pcode">
          ${[0, 1, 2, 3].map((i) => `<input id="pc${i}" inputmode="numeric" autocomplete="off" maxlength="1" aria-label="digit ${i + 1}">`).join("")}
        </div>
        <div class="who">
          <button id="who-one"><span class="em">👦</span>One</button>
          <button id="who-two"><span class="em">👧</span>Two</button>
        </div>
        <div class="err" id="werr"></div>
        <button class="btn-primary" id="enter" disabled>Enter</button>
        <div class="hint">Just us two. No accounts, ever.</div>
      </div>
    </div>`);
  const digits = $$("#pcode input");
  const who = { one: false, two: false };
  const err = $("#werr");
  const enterBtn = $("#enter");
  let picked = null;
  $$(".who button", el).forEach((b) => {
    b.addEventListener("click", () => {
      picked = b.id.replace("who-", "");
      $$(".who button").forEach((x) => (x.className = ""));
      b.classList.add("sel-" + picked);
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
  function ready() {
    return picked && digits.every((d) => d.value !== "");
  }
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
}

/* ---------- home ---------- */
let homePoll = null;
function goHome() {
  unloadView();
  const el = setView(`
    <div>
      <div class="homehead">
        <h1 class="wordmark">Our Sudoku</h1>
        <div class="me-chip"><span class="dot" id="pdot"></span><span id="pstat">${cap(partner())} offline</span></div>
      </div>
      <div class="homesub" id="greet"></div>

      <div class="sect" id="s-continue" hidden>
        <div class="sect-title">Playing together</div>
        <div id="continue-cards"></div>
      </div>

      <div class="sect" id="s-join" hidden>
        <div class="sect-title">${esc(cap(partner()))} made these — join in</div>
        <div id="join-cards"></div>
      </div>

      <div class="sect" id="s-open" hidden>
        <div class="sect" style="margin-bottom:0"><div class="sect-title">Waiting for ${esc(cap(partner()))}</div><div id="open-cards"></div></div>
      </div>

      <div class="sect">
        <button class="newbtn big" id="new-coop">✚&ensp;New game together</button>
        <div class="solorow">
          <button class="newbtn" id="new-solo">Solo · new</button>
          <button class="newbtn" id="resume-solo" hidden>Continue solo</button>
        </div>
      </div>

      <div class="sect" id="s-recent" hidden>
        <div class="sect-title">Our games</div>
        <div class="hist" id="recent-cards"></div>
      </div>
    </div>`);

  const render = (data) => {
    const greet = $("#greet", el);
    const hour = new Date().getHours();
    const hi = hour < 5 ? "Up late" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    greet.textContent = `${hi}, ${me() === "one" ? "One" : "Two"}.`;

    const dot = $("#pdot", el), pstat = $("#pstat", el);
    if (data.partner_online) { dot.classList.add("on"); pstat.textContent = `${cap(partner())} online`; }
    else { dot.classList.remove("on"); pstat.textContent = `${cap(partner())} offline`; }

    // continue (active coop)
    const items = [];
    if (data.continue) items.push(data.continue);
    items.push(...(data.also_active || []));
    showSect("s-continue", items.length > 0, () => {
      $("#continue-cards", el).innerHTML = items.map((g) => coopActiveCard(g)).join("");
      $$("#continue-cards .card", el).forEach((c, i) => c.addEventListener("click", () => openGame(items[i].id, false)));
    });

    // joinable (created by partner)
    showSect("s-join", data.joinable.length > 0, () => {
      $("#join-cards", el).innerHTML = data.joinable.map((g) => joinCard(g)).join("");
      $$("#join-cards .card", el).forEach((c, i) => c.addEventListener("click", () => openGame(data.joinable[i].id, true)));
    });

    // my open invitations
    showSect("s-open", data.my_open.length > 0, () => {
      $("#open-cards", el).innerHTML = data.my_open.map((g) => openCard(g)).join("");
      $$("#open-cards .card", el).forEach((c, i) => c.addEventListener("clic" + "k", () => openGame(data.my_open[i].id, false)));
    });

    // solo
    const rs = $("#resume-solo", el);
    if (data.solo) {
      rs.hidden = false;
      rs.textContent = `Continue solo · ${cap(data.solo.difficulty)} · ${data.solo.progress}%`;
    } else rs.hidden = true;

    // recent
    const rec = data.recent || [];
    showSect("s-recent", rec.length > 0, () => {
      $("#recent-cards", el).innerHTML = rec.map((g) => histCard(g)).join("");
      $$("#recent-cards .h", el).forEach((c, i) => c.addEventListener("click", () => openGame(rec[i].id, false)));
    });
  };

  function showSect(id, show, fill) {
    const s = $("#" + id, el);
    if (!show) { s.hidden = true; return; }
    s.hidden = false;
    fill();
  }

  async function load() {
    try { render(await api("/api/home")); } catch (e) { if (String(e.message) !== "signed out") toast(e.message); }
  }
  load();
  homePoll = setInterval(load, 15000);
  onUnload(() => clearInterval(homePoll));

  $("#new-coop", el).addEventListener("click", () => newGameSheet("coop"));
  $("#new-solo", el).addEventListener("click", () => newGameSheet("solo"));
  $("#resume-solo", el).addEventListener("click", () => data.solo && openGame(data.solo.id, false));
  $("#resume-solo", el).addEventListener("click", () => openGame(soloId, false));
}
let soloId = null;
let data = null;

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
    <div class="waiting-em">✉️</div>
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
    <h2>${kind === "coop" ? "New game together" : "New solo game"}</h2>
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

/* ---------- game ---------- */
let gameCtx = null;
function openGame(gid, viaJoin) {
  unloadView();
  const el = setView(`<div class="game" id="gd"></div>`, "");
  gameCtx = { gid, ws: null, closed: false, sel: null, noteMode: false, game: null, undoStack: [], lastVals: {}, cellsEls: [], timer: { base: 0, running: false, at: 0 }, flash: {} };
  const c = gameCtx;
  el.innerHTML = `
    <div class="ghead">
      <button class="back" id="bk" aria-label="home">‹</button>
      <div class="mid">
        <div class="tl"><span class="diff" id="gdiff"></span><span class="sep">·</span><span id="gkind"></span></div>
        <div class="sub" id="gmeta"></div>
      </div>
      <div style="text-align:right">
        <div class="timer" id="gtimer">0:00</div>
        <div class="presence" id="pres"></div>
      </div>
    </div>
    <div class="pbar"><i id="pbar-i"></i></div>
    <div id="gstatus"></div>
    <div class="boardwrap"><div class="board" id="board"></div></div>
    <div class="pad">
      <div class="padrow" id="padrow"></div>
      <div class="tools">
        <button class="tool" id="t-note"><span class="ic">✎<small id="notecount"></small></span>Notes</button>
        <button class="tool" id="t-erase"><span class="ic">⌫</span>Erase</button>
        <button class="tool" id="t-undo"><span class="ic">↩︎</span>Undo</button>
        <button class="tool" id="t-hint"><span class="ic">✦</span>Hint</button>
      </div>
    </div>`;

  buildBoard(el);
  buildPad(el);
  bindTools(el);

  $("#bk", el).addEventListener("click", () => { goHome(); });

  connect(gid, viaJoin);
}

function buildBoard(el) {
  const board = $("#board", el);
  const c = gameCtx;
  for (let i = 0; i < 81; i++) {
    const d = document.createElement("div");
    const col = i % 9, row = Math.floor(i / 9);
    if (col % 3 === 2 && col !== 8) d.classList.add("br3");
    if (row % 3 === 2 && row !== 8) d.classList.add("bb3");
    d.dataset.i = i;
    board.appendChild(d);
    c.cellsEls.push(d);
    d.addEventListener("click", () => selectCell(i));
  }
}
function buildPad(el) {
  const row = $("#padrow", el);
  for (let v = 1; v <= 9; v++) {
    const k = document.createElement("button");
    k.className = "key";
    k.dataset.v = v;
    k.innerHTML = `<span class="left" id="left-${v}"></span>${v}`;
    row.appendChild(k);
    k.addEventListener("click", () => pressDigit(v));
  }
}
function bindTools(el) {
  const c = gameCtx;
  $("#t-note", el).addEventListener("click", () => {
    c.noteMode = !c.noteMode;
    $("#t-note", el).classList.toggle("on", c.noteMode);
  });
  $("#t-erase", el).addEventListener("click", () => doErase());
  $("#t-undo", el).onCLick = null;
  $("#t-undo", el).addEventListener("click", () => doUndo());
  $("#t-hint", el).addEventListener("click", () => doHint());
}

function selectCell(i) {
  const c = gameCtx;
  const g = c.game;
  if (!g) return;
  c.sel = i;
  const val = cellVal(g, i);
  c.cellsEls.forEach((d, j) => {
    d.classList.toggle("sel", j === i);
    const row = Math.floor(j / 9), col = j % 9;
    const sr = Math.floor(i / 9), sc = i % 9;
    const hl = row === sr || col === sc || (Math.floor(row / 3) === Math.floor(sr / 3) && Math.floor(col / 3) === Math.floor(sc / 3));
    d.classList.toggle("hl", hl && j !== i);
    d.classList.toggle("same", !!val && cellVal(g, j) === val && j !== i);
  });
}
function cellVal(g, i) {
  if (g.puzzle[i] !== "0") return +g.puzzle[i];
  const cell = g.cells[String(i)];
  return cell ? cell.v : 0;
}
function render() {
  const c = gameCtx;
  const g = c.game;
  if (!g) return;
  const el = $("#gd");
  $("#gdiff", el).textContent = cap(g.difficulty);
  $("#gkind", el).textContent = g.kind === "coop" ? "Together" : "Solo";
  const metas = [];
  metas.push(`<span>${g.progress}%</span>`);
  if (g.kind === "coop") {
    metas.push('<span class="m">·</span>');
    metas.push(`<span>${esc(cap(g.creator))} started</span>`);
    const mk = g.mistakes || {};
    const mine = mk[me()] || 0, theirs = mk[partner()] || 0;
    metas.push('<span class="m">·</span>');
    metas.push(`<span class="m">mistakes ${mine}–${theirs}</span>`);

    if (g.creator === me() && g.state === "waiting") {
      metas.push('<span class="m">·</span>');
      metas.push(`<span class="playing">waiting for ${esc(cap(partner()))}…</span>
        <button id="startnow" style="color:var(--accent);font-weight:600;font-size:12.5px">start now</button>`);
    }
  }
  $("#gmeta", el).innerHTML = metas.join(" ");
  const sn = $("#startnow", el);
  if (sn) sn.addEventListener("click", (e) => { e.stopPropagation(); send({ type: "start" }); });

  // presence
  const pres = $("#pres", el);
  if (g.kind === "coop") {
    const on = c.online || [];
    pres.innerHTML = [me(), partner()].map((p) => {
      const onn = on.includes(p);
      return `<span class="p ${onn ? "on" : ""}"><i></i>${p === me() ? "you" : esc(cap(p))}</span>`;
    }).join("");
  } else pres.innerHTML = "";

  // timer base
  c.timer.base = g.elapsed_ms;
  c.timer.running = g.running && g.state !== "completed";
  c.timer.at = Date.now();

  // board cells
  for (let i = 0; i < 81; i++) {
    const d = c.cellsEls[i];
    const given = g.puzzle[i] !== "0";
    const cell = g.cells[String(i)];
    const notes = g.notes[String(i)] || [];
    let html = "";
    if (given) html = `<span>${g.puzzle[i]}</span>`;
    else if (cell) {
      const pop = c.flash[i] !== undefined && c.flash[i] !== cell.t;
      html = `<span>${cell.v}</span>`;
      if (pop) d.classList.remove("pop"), void d.offsetWidth, d.classList.add("pop");
    }
    d.classList.toggle("given", given);
    d.classList.toggle("user", !given && !!cell);
    d.classList.toggle("by-two", !given && cell && cell.by === "two");
    d.classList.toggle("wrong", !given && cell && cell.wrong);
    if (!given && !cell && notes.length) {
      html = `<div class="notes">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<i class="${n === c.lastVal ? "" : ""}">${notes.includes(n) ? n : ""}</i>`).join("")}</div>`;
    }
    d.innerHTML = html;
  }
  // note-count indicators: value → how many left
  const left = {};
  for (let v = 1; v <= 9; v++) {
    let placed = 0;
    for (let i = 0; i < 81; i++) if (cellVal(g, i) === v) placed++;
    left[v] = 9 - placed;
  }
  for (let v = 1; v <= 9; v++) {
    const el2 = document.getElementById(`left-${v}`);
    if (el2) { el2.textContent = left[v] > 0 ? left[v] : ""; el2.parentElement.classList.toggle("done", left[v] === 0); }
  }
  // progress bar
  $("#pbar-i", el).style.width = g.progress + "%";
  // status line
  const st = $("#gstatus", el);
  st.innerHTML = "";
  if (g.state === "completed") showDone(g);
  if (g.kind === "coop" && g.state === "waiting") {
    st.innerHTML = `<div class="status">Waiting for ${esc(cap(partner()))} to open the app and join. The board is ready.</div>`;
  }
  selectCell(c.sel ?? firstEmpty(g));
}
function firstEmpty(g) {
  for (let i = 0; i < 81; i++) if (!cellVal(g, i)) return i;
  return 0;
}

/* ---------- ws ---------- */
function connect(gid, viaJoin) {
  const c = gameCtx;
  if (c.closed) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = LS.get("token");
  const url = `${proto}://${location.host}/ws/games/${gid}?player=${me()}&token=${encodeURIComponent(token)}`;
  let opened = false;
  setStatus("Connecting…", "warn");
  const ws = new WebSocket(url);
  c.ws = ws;
  ws.onopen = () => { opened = true; };
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "state") {
      const first = !c.game;
      c.game = msg.game;
      c.flash = {};
      render();
      if (first && viaJoin) toast("Joined!");
    } else if (msg.type === "presence") {
      c.online = msg.online;
      if (c.game) render();
    } else if (msg.type === "error") {
      toast(msg.error);
    }
  };
  ws.onclose = () => {
    if (c.closed) return;
    setStatus("Reconnecting…", "warn");
    setTimeout(() => connect(gid, false), 1200);
  };
}
function setStatus(txt, cls) {
  const st = $("#gstatus");
  if (!st) return;
  st.innerHTML = txt ? `<div class="status ${cls || ""}">${txt}</div>` : "";
}
function send(obj) {
  const c = gameCtx;
  if (c && c.ws && c.ws.readyState === 1) c.ws.send(JSON.stringify(obj));
}

/* ---------- play ---------- */
function pushUndo(i, g) {
  const c = gameCtx;
  const cell = g.cells[String(i)];
  const notes = g.notes[String(i)] || [];
  c.undoStack.push({ idx: i, value: cell ? cell.v : 0, notes: [...notes] });
  if (c.undoStack.length > 120) c.undoStack.shift();
}
function pressDigit(v) {
  const c = gameCtx;
  const g = c.game;
  if (!g || g.state === "completed") return;
  if (g.kind === "coop" && g.state === "waiting" && g.creator === me()) {
    send({ type: "start" });
    // fall through: server will broadcast active state; still apply locally optimistic? keep simple: wait for server
  }
  if (c.sel == null) { toast("Tap a square first"); return; }
  const i = c.sel;
  if (g.puzzle[i] !== "0") return;
  pushUndo(i, g);
  if (c.noteMode) {
    const cell = g.cells[String(i)];
    if (cell) { toast("Clear the number first"); return; }
    send({ type: "note", idx: i, digit: v });
    return;
  }
  c.lastVal = v;
  send({ type: "set", idx: i, value: v });
}
function doErase() {
  const c = gameCtx;
  const g = c.game;
  if (!g || c.sel == null || g.state === "completed") return;
  const i = c.sel;
  if (g.puzzle[i] !== "0") return;
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
  const empties = [];
  for (let i = 0; i < 81; i++) {
    if (g.puzzle[i] === "0" && !g.cells[String(i)]) empties.push(i);
  }
  if (!empties.length) return;
  // ask server: hint reveals a correct value in a random empty cell; costs a mistake? keep free
  send({ type: "hint" });
}

/* ---------- done overlay ---------- */
function showDone(g) {
  if ($("#doneov")) return;
  const wrap = document.createElement("div");
  wrap.className = "done-wrap";
  wrap.id = "doneov";
  wrap.innerHTML = `<div class="done">
    <div class="tick">🎉</div>
    <h2>Solved!</h2>
    <div class="big-time">${fmtClock(g.elapsed_ms)}</div>
    <div class="sub">${g.kind === "coop" ? "Two & One, together as always" : "A clean solo solve"}</div>
    <div class="sub">Mistakes — you ${(g.mistakes || {})[me()] || 0} · ${cap(partner())} ${(g.mistakes || {})[partner()] || 0}</div>
    <div class="btns">
      <button class="again" id="dn-again">Play again</button>
      <button class="autohome" id="dn-home">Home</button>
  </div>`;
  document.body.appendChild(wrap);
  $("#dn-again", wrap).addEventListener("click", async () => {
    wrap.remove();
    newGameSheet(g.kind);
  });
  $("#dn-home", wrap). poll = null;
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
if (signedIn()) goHome(); else goWelcome();
