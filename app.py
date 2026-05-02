import os
import time
import json
import random
import sqlite3
import hashlib
from dataclasses import dataclass, asdict
import math
import random
import sqlite3
from dataclasses import dataclass
from threading import Lock
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

DB_PATH = os.path.join(os.path.dirname(__file__), "nexus.db")
SERVER_TICK_RATE = 8
SAVE_INTERVAL_SECONDS = 10
WORLD_WIDTH = 192
WORLD_HEIGHT = 192
VIEW_RADIUS = 14
SERVER_TICK_RATE = 5  # 5Hz para CPU limitada
SAVE_INTERVAL_SECONDS = 15
WORLD_WIDTH = 160
WORLD_HEIGHT = 160
VIEW_RADIUS = 18

BIOMES = ["forest", "mountain", "water", "plain"]
RESOURCE_TYPES = ["wood", "stone", "ore", "fiber"]

app = Flask(__name__)
app.config["SECRET_KEY"] = "nexus_dev_secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

lock = Lock()


@dataclass
class SessionPlayer:
    player_id: int
    username: str
    char_name: str
    sprite: str
    sid: str
    x: int
    y: int
    life: float
    hunger: float
    thirst: float
    temperature: float
    energy: float
    health: float
    wood: int
    stone: int
    ore: int
    fiber: int
    dirty: bool = False


sessions_by_sid = {}
sessions_by_player_id = {}
last_save_ts = time.time()
world_state = {"day_time": 420.0, "day_index": 0, "season": "spring", "weather": "clear", "weather_intensity": 0.0}


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def ph(pw: str) -> str:
    return hashlib.sha256((pw + "::nexus-salt").encode()).hexdigest()


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS players (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      char_name TEXT NOT NULL DEFAULT 'survivor',
      sprite TEXT NOT NULL DEFAULT 'scout',
      x INTEGER NOT NULL DEFAULT 10,
      y INTEGER NOT NULL DEFAULT 10,
      life REAL NOT NULL DEFAULT 100,
      hunger REAL NOT NULL DEFAULT 100,
      thirst REAL NOT NULL DEFAULT 100,
      temperature REAL NOT NULL DEFAULT 37,
      energy REAL NOT NULL DEFAULT 100,
      health REAL NOT NULL DEFAULT 100,
      disease_level REAL NOT NULL DEFAULT 0,
      last_login_at INTEGER,
      last_logout_at INTEGER,
      created_at INTEGER NOT NULL
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      player_id INTEGER NOT NULL,
      item_code TEXT NOT NULL,
      quantity INTEGER NOT NULL DEFAULT 0,
      slot_index INTEGER NOT NULL DEFAULT 0,
      equipped INTEGER NOT NULL DEFAULT 0,
      durability REAL NOT NULL DEFAULT 100,
      updated_at INTEGER NOT NULL,
      FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
      UNIQUE(player_id, slot_index)
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS world_entities (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      entity_type TEXT NOT NULL,
      tile_x INTEGER NOT NULL,
      tile_y INTEGER NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',
      hp REAL NOT NULL DEFAULT 100,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS world_state (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at INTEGER NOT NULL
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_world_entities_tile ON world_entities(tile_x, tile_y)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_player ON inventory(player_id)")
    now = int(time.time())
    for k, v in world_state.items():
        c.execute("INSERT OR IGNORE INTO world_state(key,value,updated_at) VALUES(?,?,?)", (k, str(v), now))
    conn.commit()
    conn.close()


def load_world_state():
    conn = get_conn()
    for r in conn.execute("SELECT key,value FROM world_state"):
        if r["key"] in ("day_time", "weather_intensity"):
            world_state[r["key"]] = float(r["value"])
        elif r["key"] == "day_index":
            world_state[r["key"]] = int(r["value"])
        else:
            world_state[r["key"]] = r["value"]
    conn.close()


def noise(x, y):
    return (hash((x * 73856093) ^ (y * 19349663)) % 1000) / 1000.0


def tile_kind(x, y):
    n = (noise(x, y) + noise(x + 13, y - 7) + noise(x - 31, y + 17)) / 3
    if x in (0, WORLD_WIDTH - 1) or y in (0, WORLD_HEIGHT - 1):
        return "wall"
    if n < 0.2:
        return "water"
    if n > 0.82:
        return "mountain"
    if n > 0.58:
        return "forest"
    return "plain"


def is_blocked(x, y):
    return tile_kind(x, y) in ("water", "mountain", "wall")


def find_spawn():
    for _ in range(2000):
        x = random.randint(2, WORLD_WIDTH - 3)
        y = random.randint(2, WORLD_HEIGHT - 3)
        if tile_kind(x, y) == "plain":
            return x, y
    return 10, 10


def create_account(username, password, char_name, sprite):
    conn = get_conn()
    now = int(time.time())
    x, y = find_spawn()
    try:
        conn.execute(
            "INSERT INTO players(username,password_hash,char_name,sprite,x,y,created_at) VALUES(?,?,?,?,?,?,?)",
            (username, ph(password), char_name, sprite, x, y, now),
        )
        conn.commit()
        ok = True
    except sqlite3.IntegrityError:
        ok = False
    conn.close()
    return ok


def login_account(username, password):
    conn = get_conn()
    row = conn.execute("SELECT * FROM players WHERE username=?", (username,)).fetchone()
    if not row or row["password_hash"] != ph(password):
        conn.close()
        return None
    conn.execute("UPDATE players SET last_login_at=? WHERE id=?", (int(time.time()), row["id"]))
    conn.commit()
    conn.close()
    return row


def to_session(row, sid):
    conn = get_conn()
    res = {r["item_code"]: r["quantity"] for r in conn.execute("SELECT item_code,quantity FROM inventory WHERE player_id=?", (row["id"],)).fetchall()}
    conn.close()
    sp = SessionPlayer(row["id"], row["username"], row["char_name"], row["sprite"], sid, row["x"], row["y"], row["life"], row["hunger"], row["thirst"], row["temperature"], row["energy"], row["health"], res.get("wood", 0), res.get("stone", 0), res.get("ore", 0), res.get("fiber", 0))
    sessions_by_sid[sid] = sp
    sessions_by_player_id[sp.player_id] = sp
    return sp


def persist_player(sp):
    conn = get_conn(); now = int(time.time())
    conn.execute("UPDATE players SET x=?,y=?,life=?,hunger=?,thirst=?,temperature=?,energy=?,health=?,last_logout_at=? WHERE id=?", (sp.x, sp.y, sp.life, sp.hunger, sp.thirst, sp.temperature, sp.energy, sp.health, now, sp.player_id))
    inv = {"wood": sp.wood, "stone": sp.stone, "ore": sp.ore, "fiber": sp.fiber}
    slot = 0
    for item, qty in inv.items():
        conn.execute("INSERT INTO inventory(player_id,item_code,quantity,slot_index,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(player_id,slot_index) DO UPDATE SET item_code=excluded.item_code, quantity=excluded.quantity, updated_at=excluded.updated_at", (sp.player_id, item, qty, slot, now)); slot += 1
    conn.commit(); conn.close(); sp.dirty = False


def nearby(sp):
    arr = []
    for p in sessions_by_player_id.values():
        if abs(p.x - sp.x) <= VIEW_RADIUS and abs(p.y - sp.y) <= VIEW_RADIUS:
            arr.append({"id": p.player_id, "u": p.username, "n": p.char_name, "sprite": p.sprite, "x": p.x, "y": p.y})
    return arr


def apply_decay(sp, dt):
    sp.hunger = max(0, sp.hunger - 0.17 * dt); sp.thirst = max(0, sp.thirst - 0.25 * dt); sp.energy = max(0, sp.energy - 0.15 * dt)
    if sp.hunger < 20 or sp.thirst < 20: sp.life = max(0, sp.life - 0.4 * dt)
    if world_state["weather"] == "storm": sp.temperature -= 0.03 * dt
    else: sp.temperature += (37 - sp.temperature) * 0.03 * dt
    if sp.temperature < 35: sp.health = max(0, sp.health - 0.03 * dt)


def gather(sp):
    t = tile_kind(sp.x, sp.y)
    if t == "forest": sp.wood += 1; sp.fiber += 1
    elif t == "mountain": sp.stone += 1; sp.ore += 1
    elif t == "plain": sp.fiber += 1
    sp.energy = max(0, sp.energy - 0.7); sp.dirty = True


def drink(sp):
    for ox, oy in ((0,1),(1,0),(-1,0),(0,-1)):
        if tile_kind(sp.x+ox, sp.y+oy) == "water":
            sp.thirst = min(100, sp.thirst + 30); sp.temperature = min(37, sp.temperature+0.2); sp.dirty = True; return True
    return False


@socketio.on("register")
def on_register(data):
    u = (data.get("username") or "").strip()[:20]
    p = (data.get("password") or "").strip()[:40]
    n = (data.get("char_name") or "Survivor").strip()[:20]
    s = (data.get("sprite") or "scout").strip()[:10]
    if len(u) < 3 or len(p) < 4:
        return emit("auth", {"ok": False, "error": "Usuario o clave demasiado corta."})
    ok = create_account(u, p, n, s)
    emit("auth", {"ok": ok, "mode": "register", "error": None if ok else "Usuario ya existe."})


@socketio.on("login")
def on_login(data):
    u = (data.get("username") or "").strip()[:20]
    p = (data.get("password") or "").strip()[:40]
    row = login_account(u, p)
    if not row:
        return emit("auth", {"ok": False, "error": "Credenciales inválidas."})
    sp = to_session(row, request.sid)
    emit("auth", {"ok": True, "mode": "login"})
    emit("bootstrap", {"self": asdict(sp), "world": {**world_state, "w": WORLD_WIDTH, "h": WORLD_HEIGHT}, "players": nearby(sp)})


@socketio.on("move")
def on_move(data):
    sp = sessions_by_sid.get(request.sid)
    if not sp: return
    dx, dy = int(max(-1, min(1, data.get("dx", 0)))), int(max(-1, min(1, data.get("dy", 0))))
    nx, ny = sp.x + dx, sp.y + dy
    if 0 <= nx < WORLD_WIDTH and 0 <= ny < WORLD_HEIGHT and not is_blocked(nx, ny):
        sp.x, sp.y = nx, ny; sp.energy = max(0, sp.energy - 0.08); sp.dirty = True
    else:
        emit("hint", {"msg": "No puedes pasar: hay agua o barrera."})


@socketio.on("action")
def on_action(data):
    sp = sessions_by_sid.get(request.sid)
    if not sp: return
    a = data.get("kind")
    if a == "gather": gather(sp)
    elif a == "drink":
        if not drink(sp): emit("hint", {"msg": "Necesitas estar junto al agua para beber."})
    elif a == "rest": sp.energy = min(100, sp.energy + 18); sp.temperature = min(37, sp.temperature + 0.1)
    elif a == "craft_fire" and sp.wood >= 3 and sp.stone >= 2:
        sp.wood -= 3; sp.stone -= 2; sp.temperature = min(37, sp.temperature + 1.5); emit("hint", {"msg": "Fogata creada, recuperas temperatura."})
    elif a == "craft_tool" and sp.wood >= 2 and sp.stone >= 1:
        sp.wood -= 2; sp.stone -= 1; sp.ore += 1; emit("hint", {"msg": "Herramienta básica creada (+1 ore)."})
    sp.dirty = True


@socketio.on("chat")
def on_chat(data):
    sp = sessions_by_sid.get(request.sid)
    if not sp: return
    msg = (data.get("msg") or "").strip()[:120]
    if msg: emit("chat_bubble", {"id": sp.player_id, "msg": msg, "ts": int(time.time())}, broadcast=True)


@socketio.on("trade_request")
def on_trade(data):
    sp = sessions_by_sid.get(request.sid)
    if not sp: return
    target = sessions_by_player_id.get(int(data.get("target_id", -1)))
    item = data.get("item")
    qty = int(data.get("qty", 0))
    if not target or qty <= 0 or abs(target.x - sp.x) > 1 or abs(target.y - sp.y) > 1: return
    if item not in ("wood", "stone", "ore", "fiber"): return
    if getattr(sp, item) < qty: return
    setattr(sp, item, getattr(sp, item) - qty); setattr(target, item, getattr(target, item) + qty)
    sp.dirty = target.dirty = True
    emit("hint", {"msg": f"Intercambiaste {qty} {item} con {target.char_name}."})


@socketio.on("disconnect")
def on_disc():
    sp = sessions_by_sid.pop(request.sid, None)
    if sp:
        sessions_by_player_id.pop(sp.player_id, None); persist_player(sp)


@app.route("/")
def index(): return render_template("index.html")


def game_loop():
    global last_save_ts
    prev = time.time()
    while True:
        now = time.time(); dt = now - prev; prev = now
        with lock:
            world_state["day_time"] = (world_state["day_time"] + dt * 1.2) % 1440
            if random.random() < 0.003:
                world_state["weather"] = random.choice(["clear", "fog", "rain", "storm"]); world_state["weather_intensity"] = round(random.random(), 2)
            changed = []
            for sp in list(sessions_by_player_id.values()):
                apply_decay(sp, dt)
                changed.append({"id": sp.player_id, "x": sp.x, "y": sp.y, "life": round(sp.life,1), "hunger": round(sp.hunger,1), "thirst": round(sp.thirst,1), "temperature": round(sp.temperature,1), "energy": round(sp.energy,1), "health": round(sp.health,1), "wood": sp.wood, "stone": sp.stone, "ore": sp.ore, "fiber": sp.fiber, "n": sp.char_name, "sprite": sp.sprite, "u": sp.username})
            if changed: socketio.emit("delta", {"players": changed, "world": world_state})
            if now - last_save_ts > SAVE_INTERVAL_SECONDS:
                conn = get_conn(); ts = int(now)
                for k, v in world_state.items(): conn.execute("UPDATE world_state SET value=?,updated_at=? WHERE key=?", (str(v), ts, k))
                conn.commit(); conn.close()
                for sp in list(sessions_by_player_id.values()):
                    if sp.dirty: persist_player(sp)
                last_save_ts = now
        socketio.sleep(1 / SERVER_TICK_RATE)


if __name__ == "__main__":
    init_db(); load_world_state(); socketio.start_background_task(game_loop)
    socketio.run(app, host="0.0.0.0", port=5000)
