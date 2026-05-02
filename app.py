import os
import time
import math
import random
import sqlite3
from dataclasses import dataclass
from threading import Lock
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

DB_PATH = os.path.join(os.path.dirname(__file__), "nexus.db")
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
    sid: str
    x: int
    y: int
    life: float
    hunger: float
    thirst: float
    temperature: float
    energy: float
    health: float
    dirty: bool = False


sessions_by_sid = {}
sessions_by_player_id = {}
last_save_ts = time.time()
world_state = {
    "day_time": 0.0,
    "day_index": 0,
    "season": "spring",
    "weather": "clear",
    "weather_intensity": 0.0,
}


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            x INTEGER NOT NULL DEFAULT 80,
            y INTEGER NOT NULL DEFAULT 80,
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
        );
        """
    )

    cur.execute(
        """
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
            UNIQUE(player_id, slot_index),
            UNIQUE(player_id, item_code, equipped)
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS world_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            biome TEXT,
            tile_x INTEGER NOT NULL,
            tile_y INTEGER NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_by_player_id INTEGER,
            hp REAL NOT NULL DEFAULT 100,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS world_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_world_entities_tile ON world_entities(tile_x, tile_y);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_player ON inventory(player_id);")

    now = int(time.time())
    for k, v in (("day_time", "0.0"), ("day_index", "0"), ("season", "spring"), ("weather", "clear"), ("weather_intensity", "0.0")):
        cur.execute(
            "INSERT OR IGNORE INTO world_state(key, value, updated_at) VALUES (?, ?, ?)",
            (k, str(v), now),
        )

    conn.commit()
    conn.close()


def load_world_state():
    conn = get_conn()
    cur = conn.execute("SELECT key, value FROM world_state")
    for row in cur.fetchall():
        if row["key"] in ("day_time", "weather_intensity"):
            world_state[row["key"]] = float(row["value"])
        elif row["key"] == "day_index":
            world_state[row["key"]] = int(row["value"])
        else:
            world_state[row["key"]] = row["value"]
    conn.close()


def ensure_player(username: str, password_hash: str = "dev"):
    conn = get_conn()
    now = int(time.time())
    conn.execute(
        "INSERT OR IGNORE INTO players(username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM players WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row


def update_player_session(player_row, sid):
    sp = SessionPlayer(
        player_id=player_row["id"],
        username=player_row["username"],
        sid=sid,
        x=player_row["x"],
        y=player_row["y"],
        life=player_row["life"],
        hunger=player_row["hunger"],
        thirst=player_row["thirst"],
        temperature=player_row["temperature"],
        energy=player_row["energy"],
        health=player_row["health"],
    )
    sessions_by_sid[sid] = sp
    sessions_by_player_id[sp.player_id] = sp
    return sp


def persist_player(sp: SessionPlayer):
    conn = get_conn()
    conn.execute(
        """
        UPDATE players
        SET x=?, y=?, life=?, hunger=?, thirst=?, temperature=?, energy=?, health=?, last_logout_at=?
        WHERE id=?
        """,
        (sp.x, sp.y, sp.life, sp.hunger, sp.thirst, sp.temperature, sp.energy, sp.health, int(time.time()), sp.player_id),
    )
    conn.commit()
    conn.close()
    sp.dirty = False


def persist_world_state():
    conn = get_conn()
    now = int(time.time())
    for key, value in world_state.items():
        conn.execute(
            "UPDATE world_state SET value=?, updated_at=? WHERE key=?",
            (str(value), now, key),
        )
    conn.commit()
    conn.close()


def apply_survival_decay(sp: SessionPlayer, dt: float):
    sp.hunger = max(0.0, sp.hunger - 0.14 * dt)
    sp.thirst = max(0.0, sp.thirst - 0.22 * dt)
    sp.energy = max(0.0, sp.energy - 0.12 * dt)

    if sp.hunger <= 0 or sp.thirst <= 0:
        sp.life = max(0.0, sp.life - 0.50 * dt)
    if world_state["weather"] == "storm":
        sp.temperature -= 0.02 * (1 + world_state["weather_intensity"]) * dt
    else:
        sp.temperature += (37.0 - sp.temperature) * 0.04 * dt

    if sp.temperature < 35.0:
        sp.health = max(0.0, sp.health - (35.0 - sp.temperature) * 0.02 * dt)

    sp.dirty = True


def move_player(sp: SessionPlayer, dx: int, dy: int):
    nx = max(0, min(WORLD_WIDTH - 1, sp.x + dx))
    ny = max(0, min(WORLD_HEIGHT - 1, sp.y + dy))
    if nx != sp.x or ny != sp.y:
        sp.x, sp.y = nx, ny
        sp.energy = max(0.0, sp.energy - 0.15)
        sp.dirty = True


def nearby_players_for(sp: SessionPlayer):
    out = []
    for other in sessions_by_player_id.values():
        if abs(other.x - sp.x) <= VIEW_RADIUS and abs(other.y - sp.y) <= VIEW_RADIUS:
            out.append({
                "id": other.player_id,
                "u": other.username,
                "x": other.x,
                "y": other.y,
            })
    return out


def tick_world(dt: float):
    world_state["day_time"] += dt * 0.5
    if world_state["day_time"] >= 1440:
        world_state["day_time"] -= 1440
        world_state["day_index"] += 1
        season_id = (world_state["day_index"] // 30) % 4
        world_state["season"] = ["spring", "summer", "autumn", "winter"][season_id]

    if random.random() < 0.004:
        world_state["weather"] = random.choice(["clear", "fog", "rain", "storm"])
        world_state["weather_intensity"] = round(random.random(), 2)


@socketio.on("connect")
def on_connect():
    emit("connected", {"ok": True})


@socketio.on("join")
def on_join(data):
    username = data.get("username", "guest").strip()[:20] or "guest"
    player = ensure_player(username)

    conn = get_conn()
    conn.execute("UPDATE players SET last_login_at=? WHERE id=?", (int(time.time()), player["id"]))
    conn.commit()
    conn.close()

    sp = update_player_session(player, request.sid)

    emit(
        "bootstrap",
        {
            "self": {
                "id": sp.player_id,
                "u": sp.username,
                "x": sp.x,
                "y": sp.y,
                "life": sp.life,
                "hunger": sp.hunger,
                "thirst": sp.thirst,
                "temperature": sp.temperature,
                "energy": sp.energy,
                "health": sp.health,
            },
            "world": {
                "w": WORLD_WIDTH,
                "h": WORLD_HEIGHT,
                "day_time": world_state["day_time"],
                "season": world_state["season"],
                "weather": world_state["weather"],
                "weather_intensity": world_state["weather_intensity"],
            },
            "players": nearby_players_for(sp),
        },
    )


@socketio.on("move")
def on_move(data):
    sp = sessions_by_sid.get(request.sid)
    if not sp:
        return
    dx = int(max(-1, min(1, data.get("dx", 0))))
    dy = int(max(-1, min(1, data.get("dy", 0))))
    move_player(sp, dx, dy)


@socketio.on("chat")
def on_chat(data):
    sp = sessions_by_sid.get(request.sid)
    if not sp:
        return
    msg = (data.get("msg", "") or "").strip()[:120]
    if not msg:
        return
    emit("chat_bubble", {"id": sp.player_id, "msg": msg, "ts": int(time.time())}, broadcast=True)


@socketio.on("disconnect")
def on_disconnect():
    sp = sessions_by_sid.pop(request.sid, None)
    if not sp:
        return
    sessions_by_player_id.pop(sp.player_id, None)
    persist_player(sp)


@app.route("/")
def index():
    return render_template("index.html")


def game_loop():
    global last_save_ts
    prev = time.time()
    while True:
        now = time.time()
        dt = now - prev
        prev = now

        with lock:
            tick_world(dt)
            changed = []
            for sp in list(sessions_by_player_id.values()):
                apply_survival_decay(sp, dt)
                changed.append({
                    "id": sp.player_id,
                    "x": sp.x,
                    "y": sp.y,
                    "life": round(sp.life, 1),
                    "hunger": round(sp.hunger, 1),
                    "thirst": round(sp.thirst, 1),
                    "temperature": round(sp.temperature, 2),
                    "energy": round(sp.energy, 1),
                    "health": round(sp.health, 1),
                })

            if changed:
                socketio.emit(
                    "delta",
                    {
                        "players": changed,
                        "world": {
                            "day_time": world_state["day_time"],
                            "season": world_state["season"],
                            "weather": world_state["weather"],
                            "weather_intensity": world_state["weather_intensity"],
                        },
                    },
                )

            if now - last_save_ts >= SAVE_INTERVAL_SECONDS:
                for sp in list(sessions_by_player_id.values()):
                    if sp.dirty:
                        persist_player(sp)
                persist_world_state()
                last_save_ts = now

        socketio.sleep(1.0 / SERVER_TICK_RATE)


if __name__ == "__main__":
    init_db()
    load_world_state()
    socketio.start_background_task(game_loop)
    socketio.run(app, host="0.0.0.0", port=5000)
