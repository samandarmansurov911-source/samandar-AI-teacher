// Ikkala sahifa uchun umumiy yordamchilar
const $ = (sel, root = document) => root.querySelector(sel);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch (e) {
    return null;
  }
}

let toastTimer;
function toast(text) {
  let el = $(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
}

// Uzilib qolsa o'zi qayta ulanadigan WebSocket
function connect({ onOpen, onMessage }) {
  let ws;
  let retry = 0;
  const badge = document.createElement("div");
  badge.className = "conn hidden";
  badge.textContent = "Ulanmoqda…";
  document.body.appendChild(badge);

  const api = {
    send(obj) {
      if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
    },
  };

  function open() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      retry = 0;
      badge.classList.add("hidden");
      onOpen && onOpen();
    };
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    ws.onclose = () => {
      badge.classList.remove("hidden");
      setTimeout(open, Math.min(5000, 500 * 2 ** retry++));
    };
  }
  open();
  return api;
}

function medal(rank) {
  return { 1: "🥇", 2: "🥈", 3: "🥉" }[rank] || rank;
}

function boardHTML(rows, meId, limit) {
  const list = limit ? rows.slice(0, limit) : rows;
  if (!list.length) return '<p class="center" style="opacity:.8">Hali hech kim yo\'q</p>';
  return (
    '<ul class="board">' +
    list
      .map((r) => {
        const mv = r.move > 0 ? `<span class="mv up">▲${r.move}</span>` : r.move < 0 ? `<span class="mv down">▼${-r.move}</span>` : '<span class="mv"></span>';
        const fire = r.streak >= 2 ? `<span class="fire">🔥${r.streak}</span>` : "";
        return `<li class="${r.id === meId ? "me" : ""} ${r.online ? "" : "off"}" data-id="${r.id}">
          <span class="rk">${medal(r.rank)}</span><span class="nm">${esc(r.name)}</span>${fire}${mv}<span class="sc">${r.score}</span></li>`;
      })
      .join("") +
    "</ul>"
  );
}

function podiumHTML(rows) {
  const top = rows.slice(0, 3);
  const order = [top[1], top[0], top[2]];
  const cls = ["p2", "p1", "p3"];
  return (
    '<div class="podium">' +
    order
      .map((r, i) =>
        r
          ? `<div class="${cls[i]} pop"><div class="nm">${esc(r.name)}</div><div class="bar"><span class="medal">${medal(r.rank)}</span>${r.score}</div></div>`
          : `<div class="${cls[i]}"></div>`
      )
      .join("") +
    "</div>"
  );
}

// Savol taymeri: serverdan kelgan qolgan vaqt asosida
function startTimer(q, bar, label) {
  const ends = Date.now() + q.remaining;
  clearInterval(startTimer.id);
  const tick = () => {
    const left = Math.max(0, ends - Date.now());
    if (bar) bar.style.width = (100 * left) / (q.duration * 1000) + "%";
    if (label) label.textContent = Math.ceil(left / 1000);
    if (!left) clearInterval(startTimer.id);
  };
  tick();
  startTimer.id = setInterval(tick, 200);
}
