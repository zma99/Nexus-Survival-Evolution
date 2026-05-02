const socket = io();
const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');
const hud = document.getElementById('hud');
const chatInput = document.getElementById('chatInput');

const TILE = 32;
let world = { w: 160, h: 160, day_time: 0, season: 'spring', weather: 'clear', weather_intensity: 0 };
let me = null;
let players = new Map();
let bubbles = new Map();

function biomeAt(x, y) {
  const n = (Math.sin(x * 0.21) + Math.cos(y * 0.17) + Math.sin((x + y) * 0.09)) / 3;
  if (n < -0.18) return 'water';
  if (n < 0.05) return 'plain';
  if (n < 0.26) return 'forest';
  return 'mountain';
}

function drawTile(tx, ty, sx, sy) {
  const b = biomeAt(tx, ty);
  if (b === 'water') ctx.fillStyle = '#245a86';
  else if (b === 'forest') ctx.fillStyle = '#2f6b2d';
  else if (b === 'mountain') ctx.fillStyle = '#6f7075';
  else ctx.fillStyle = '#6e8c4f';
  ctx.fillRect(sx, sy, TILE, TILE);

  if (b === 'forest' && ((tx + ty) % 4 === 0)) {
    ctx.fillStyle = '#173c19';
    ctx.fillRect(sx + 10, sy + 6, 10, 18);
  } else if (b === 'mountain' && ((tx * 3 + ty) % 5 === 0)) {
    ctx.fillStyle = '#b5b9bf';
    ctx.beginPath();
    ctx.moveTo(sx + 8, sy + 24);
    ctx.lineTo(sx + 16, sy + 6);
    ctx.lineTo(sx + 24, sy + 24);
    ctx.fill();
  }
}

function drawPlayer(p, self = false) {
  if (!me) return;
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  const sx = cx + (p.x - me.x) * TILE;
  const sy = cy + (p.y - me.y) * TILE;
  if (sx < -TILE || sy < -TILE || sx > canvas.width + TILE || sy > canvas.height + TILE) return;

  ctx.fillStyle = self ? '#ffd166' : '#f94144';
  ctx.beginPath();
  ctx.arc(sx + TILE / 2, sy + TILE / 2, 10, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#fff';
  ctx.font = '12px Arial';
  ctx.fillText(p.u, sx - 2, sy - 4);

  const b = bubbles.get(p.id);
  if (b && Date.now() - b.ts < 5000) {
    const txt = b.msg;
    const w = ctx.measureText(txt).width + 10;
    ctx.fillStyle = 'rgba(0,0,0,.6)';
    ctx.fillRect(sx - 4, sy - 28, w, 18);
    ctx.fillStyle = '#fff';
    ctx.fillText(txt, sx, sy - 14);
  }
}

function render() {
  if (!me) return requestAnimationFrame(render);
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const viewTilesX = Math.ceil(canvas.width / TILE) + 2;
  const viewTilesY = Math.ceil(canvas.height / TILE) + 2;

  const startX = me.x - Math.floor(viewTilesX / 2);
  const startY = me.y - Math.floor(viewTilesY / 2);

  for (let y = 0; y < viewTilesY; y++) {
    for (let x = 0; x < viewTilesX; x++) {
      const tx = startX + x;
      const ty = startY + y;
      if (tx < 0 || ty < 0 || tx >= world.w || ty >= world.h) continue;
      drawTile(tx, ty, x * TILE, y * TILE);
    }
  }

  players.forEach(p => drawPlayer(p, p.id === me.id));
  drawHUD();
  requestAnimationFrame(render);
}

function drawHUD() {
  hud.innerHTML = `
    <div><strong>${me.u}</strong> (${me.x},${me.y})</div>
    <div>Vida: ${me.life.toFixed(1)} | Salud: ${me.health.toFixed(1)}</div>
    <div>Hambre: ${me.hunger.toFixed(1)} | Sed: ${me.thirst.toFixed(1)}</div>
    <div>Energía: ${me.energy.toFixed(1)} | Temp: ${me.temperature.toFixed(1)}°C</div>
    <div>Mundo: ${world.season} / ${world.weather} (${world.weather_intensity})</div>
    <div>Mochila: [madera x4, piedra x3]</div>
  `;
}

socket.on('bootstrap', (data) => {
  me = data.self;
  world = data.world;
  players.clear();
  for (const p of data.players) players.set(p.id, p);
  players.set(me.id, me);
});

socket.on('delta', (data) => {
  if (data.world) world = { ...world, ...data.world };
  for (const p of data.players || []) {
    const current = players.get(p.id) || {};
    const next = { ...current, ...p };
    players.set(p.id, next);
    if (me && p.id === me.id) me = next;
  }
});

socket.on('chat_bubble', (payload) => {
  bubbles.set(payload.id, { msg: payload.msg, ts: Date.now() });
});

window.addEventListener('keydown', (e) => {
  if (!me) return;
  let dx = 0, dy = 0;
  if (e.key === 'ArrowUp' || e.key === 'w') dy = -1;
  if (e.key === 'ArrowDown' || e.key === 's') dy = 1;
  if (e.key === 'ArrowLeft' || e.key === 'a') dx = -1;
  if (e.key === 'ArrowRight' || e.key === 'd') dx = 1;
  if (dx || dy) socket.emit('move', { dx, dy });
});

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const msg = chatInput.value.trim();
    if (msg) socket.emit('chat', { msg });
    chatInput.value = '';
  }
});

const username = `player_${Math.floor(Math.random() * 9999)}`;
socket.emit('join', { username });
requestAnimationFrame(render);
