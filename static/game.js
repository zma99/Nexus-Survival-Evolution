const socket = io();
const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');
const hud = document.getElementById('hud');
const help = document.getElementById('help');
const chatInput = document.getElementById('chatInput');
const auth = document.getElementById('auth');
const authMsg = document.getElementById('authMsg');
const usernameEl = document.getElementById('username');
const passwordEl = document.getElementById('password');
const charNameEl = document.getElementById('charName');
const spriteEl = document.getElementById('sprite');

const TILE = 32;
let me = null;
let world = { w: 192, h: 192, weather: 'clear', season: 'spring', day_time: 0 };
const players = new Map();
const bubbles = new Map();
let hint = '';

function tileKind(x, y) {
  const a = Math.abs(((x * 73856093) ^ (y * 19349663)) % 1000) / 1000;
  const b = Math.abs((((x + 13) * 73856093) ^ ((y - 7) * 19349663)) % 1000) / 1000;
  const c = Math.abs((((x - 31) * 73856093) ^ ((y + 17) * 19349663)) % 1000) / 1000;
  const n = (a + b + c) / 3;
  if (x === 0 || y === 0 || x === world.w - 1 || y === world.h - 1) return 'wall';
  if (n < 0.2) return 'water';
  if (n > 0.82) return 'mountain';
  if (n > 0.58) return 'forest';
  return 'plain';
}

const tileColor = { water: '#2a77b3', mountain: '#61656c', forest: '#2f7d32', wall: '#222', plain: '#82a95b' };

function drawPlayer(p, sx, sy, self=false) {
  ctx.fillStyle = self ? '#ffd166' : '#ff6b6b';
  ctx.fillRect(sx + 10, sy + 6, 12, 14);
  ctx.fillStyle = '#f2d3b0';
  ctx.fillRect(sx + 11, sy + 1, 10, 6);
  ctx.fillStyle = '#151515';
  if (p.sprite === 'miner') ctx.fillRect(sx + 9, sy + 1, 14, 2);
  if (p.sprite === 'ranger') ctx.fillRect(sx + 8, sy + 4, 3, 12);

  ctx.fillStyle = '#fff'; ctx.font = '10px monospace';
  ctx.fillText(p.n || p.u || 'player', sx - 4, sy - 4);

  const b = bubbles.get(p.id);
  if (b && Date.now() - b.ts < 5000) {
    const w = ctx.measureText(b.msg).width + 10;
    ctx.fillStyle = 'rgba(0,0,0,0.65)'; ctx.fillRect(sx - 5, sy - 30, w, 16);
    ctx.fillStyle = '#fff'; ctx.fillText(b.msg, sx - 1, sy - 18);
  }
}

function render() {
  requestAnimationFrame(render);
  if (!me) return;

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const tilesX = Math.ceil(canvas.width / TILE) + 2;
  const tilesY = Math.ceil(canvas.height / TILE) + 2;
  const startX = me.x - Math.floor(tilesX / 2);
  const startY = me.y - Math.floor(tilesY / 2);

  for (let j = 0; j < tilesY; j++) {
    for (let i = 0; i < tilesX; i++) {
      const tx = startX + i, ty = startY + j;
      if (tx < 0 || ty < 0 || tx >= world.w || ty >= world.h) continue;
      const kind = tileKind(tx, ty);
      const sx = i * TILE, sy = j * TILE;
      ctx.fillStyle = tileColor[kind];
      ctx.fillRect(sx, sy, TILE, TILE);
      if (kind === 'forest') { ctx.fillStyle = '#1f4f20'; ctx.fillRect(sx + 11, sy + 8, 10, 16); }
      if (kind === 'mountain') { ctx.fillStyle = '#d2d5d9'; ctx.beginPath(); ctx.moveTo(sx + 7, sy + 25); ctx.lineTo(sx + 16, sy + 6); ctx.lineTo(sx + 25, sy + 25); ctx.fill(); }
      if (kind === 'water') { ctx.fillStyle = '#61b4f355'; ctx.fillRect(sx, sy, TILE, TILE); }
    }
  }

  players.forEach((p) => {
    const sx = canvas.width / 2 + (p.x - me.x) * TILE;
    const sy = canvas.height / 2 + (p.y - me.y) * TILE;
    if (sx > -TILE && sy > -TILE && sx < canvas.width + TILE && sy < canvas.height + TILE) {
      drawPlayer(p, sx, sy, p.id === me.id);
    }
  });

  hud.innerHTML = `<b>${me.n || me.u}</b> (${me.x},${me.y})<br>
  Vida ${me.life?.toFixed(1)} | Salud ${me.health?.toFixed(1)}<br>
  Hambre ${me.hunger?.toFixed(1)} | Sed ${me.thirst?.toFixed(1)} | Energía ${me.energy?.toFixed(1)}<br>
  Temp ${me.temperature?.toFixed(1)}°C | Clima ${world.weather}<br>
  Mochila: madera ${me.wood||0}, piedra ${me.stone||0}, mineral ${me.ore||0}, fibra ${me.fiber||0}`;

  help.innerHTML = `<b>Controles</b><br>WASD/Flechas: mover<br>E: recolectar<br>G: beber (junto a agua)<br>R: descansar<br>F: fogata<br>T: herramienta<br>H: trade rápido con adyacente<br>${hint ? `<hr>${hint}` : ''}`;
}

socket.on('auth', (d) => {
  authMsg.textContent = d.ok ? 'OK ✔' : (d.error || 'Error');
  if (d.ok && d.mode === 'login') auth.style.display = 'none';
});

socket.on('bootstrap', (d) => {
  world = d.world;
  me = d.self;
  me.id = me.player_id;
  players.clear();
  (d.players || []).forEach((p) => players.set(p.id, p));
  players.set(me.id, me);
});

socket.on('delta', (d) => {
  world = { ...world, ...(d.world || {}) };
  (d.players || []).forEach((p) => {
    const cur = players.get(p.id) || {};
    const next = { ...cur, ...p };
    players.set(p.id, next);
    if (me && p.id === me.id) me = { ...me, ...p };
  });
});

socket.on('chat_bubble', (d) => bubbles.set(d.id, { msg: d.msg, ts: Date.now() }));
socket.on('hint', (d) => { hint = d.msg; setTimeout(() => { if (hint === d.msg) hint = ''; }, 3000); });

document.getElementById('loginBtn').addEventListener('click', () => {
  socket.emit('login', { username: usernameEl.value.trim(), password: passwordEl.value });
});

document.getElementById('registerBtn').addEventListener('click', () => {
  socket.emit('register', {
    username: usernameEl.value.trim(),
    password: passwordEl.value,
    char_name: charNameEl.value.trim() || 'Survivor',
    sprite: spriteEl.value,
  });
});

window.addEventListener('keydown', (e) => {
  if (!me) return;
  let dx = 0, dy = 0;
  if (e.key === 'w' || e.key === 'ArrowUp') dy = -1;
  if (e.key === 's' || e.key === 'ArrowDown') dy = 1;
  if (e.key === 'a' || e.key === 'ArrowLeft') dx = -1;
  if (e.key === 'd' || e.key === 'ArrowRight') dx = 1;
  if (dx || dy) socket.emit('move', { dx, dy });

  if (e.key === 'e') socket.emit('action', { kind: 'gather' });
  if (e.key === 'g') socket.emit('action', { kind: 'drink' });
  if (e.key === 'r') socket.emit('action', { kind: 'rest' });
  if (e.key === 'f') socket.emit('action', { kind: 'craft_fire' });
  if (e.key === 't') socket.emit('action', { kind: 'craft_tool' });
  if (e.key === 'h') {
    const target = [...players.values()].find((p) => p.id !== me.id && Math.abs(p.x - me.x) <= 1 && Math.abs(p.y - me.y) <= 1);
    if (target) socket.emit('trade_request', { target_id: target.id, item: 'wood', qty: 1 });
    else hint = 'No hay jugador adyacente para intercambio.';
  }
});

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const msg = chatInput.value.trim();
    if (msg) socket.emit('chat', { msg });
    chatInput.value = '';
  }
});

requestAnimationFrame(render);
