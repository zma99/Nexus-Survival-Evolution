# Nexus Survival: Evolution

Versión mejorada estilo "Minecraft recortado" (pixel-art 2D top-down), con login/registro, personaje, colisiones naturales, crafting, recolección y trade local en tiempo real.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar en LAN

```bash
python app.py
```

Abrir en navegador:
- `http://127.0.0.1:5000`
- `http://192.168.1.205:5000`

## Controles

- Movimiento: `WASD` o flechas.
- `E`: recolectar recursos del bioma actual.
- `G`: beber agua (solo adyacente a agua).
- `R`: descansar.
- `F`: crear fogata (3 madera + 2 piedra).
- `T`: crear herramienta (2 madera + 1 piedra).
- `H`: trade rápido (1 madera) con jugador adyacente.
- `Enter`: enviar chat bubble.

## Reglas naturales implementadas

- Bordes del mapa son barreras (wall).
- Agua es bloqueante (no se puede atravesar).
- Montaña es bloqueante (simula paredes).
- Si intentas pasar, el servidor rechaza movimiento y envía mensaje.

## Persistencia SQLite

- `players`: credenciales, personaje, posición, stats vitales.
- `inventory`: inventario persistente por jugador.
- `world_entities`: espacio para construcciones/drops.
- `world_state`: estado global (clima, tiempo de día).
