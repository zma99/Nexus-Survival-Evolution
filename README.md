# Nexus Survival: Evolution

Implementación base de un juego de supervivencia multijugador en navegador, optimizado para hardware limitado (PC Stick con Atom/Celeron), usando Flask + Socket.IO + SQLite.

## Requisitos

- Python 3.10+
- pip

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecución

```bash
python app.py
```

Servidor disponible en:

- Local: `http://127.0.0.1:5000`
- LAN: `http://192.168.1.205:5000`

## Estructura

- `app.py`: servidor Flask-SocketIO, loop de juego, persistencia SQLite.
- `templates/index.html`: entrada del cliente.
- `static/game.js`: renderizado canvas, HUD, input, chat bubble y sincronización.
- `nexus.db`: base de datos SQLite autogenerada.

## Esquema de datos (SQLite)

- `players`: credenciales, stats de supervivencia, posición y timestamps de sesión.
- `inventory`: inventario y equipamiento por jugador.
- `world_entities`: objetos del mundo, drops y construcciones persistentes.
- `world_state`: ciclo día/noche, estación y clima global.

## Optimización aplicada

- Tick rate bajo: `5 Hz` para carga estable en CPU limitada.
- Broadcast de `delta` (solo cambios de estado), no snapshot completo en cada frame.
- Guardado periódico cada 15s + guardado al desconectar.
- SQLite en modo `WAL` y `synchronous=NORMAL`.
