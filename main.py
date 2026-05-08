import asyncio
import logging
from pathlib import Path
from typing import Any, List

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from devices.kasa_device import KasaController
from devices.tuya_device import TuyaController
from devices.ecoflow_device import EcoflowController
from devices.arduino_ir import ArduinoIRController
from devices.roku_device import RokuController

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Load config ----------------------------------------------------------------
config: dict = {}
for name in ("config.yaml", "config.yml"):
    p = Path(name)
    if p.exists():
        with open(p) as f:
            config = yaml.safe_load(f) or {}
        break

if not config:
    logger.warning("No config.yaml found — copy config.yaml.example and fill in your devices.")

# Controllers ----------------------------------------------------------------
kasa      = KasaController(config.get("kasa") or {})
tuya      = TuyaController(config.get("tuya") or {})
ecoflow   = EcoflowController(config.get("ecoflow") or {})
arduino   = ArduinoIRController(config.get("arduino_ir") or {})
roku      = RokuController(config.get("roku") or {})

# App ------------------------------------------------------------------------
app = FastAPI(title="LCARS Home Control", docs_url="/api/docs")

ws_clients: List[WebSocket] = []


async def broadcast(msg: dict):
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


# ── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


# ── Kasa ─────────────────────────────────────────────────────────────────────

@app.get("/api/kasa/discover")
async def kasa_discover():
    return await kasa.discover()

@app.get("/api/kasa/devices")
async def kasa_devices():
    return await kasa.get_all_status()

@app.post("/api/kasa/{alias}/power")
async def kasa_power(alias: str, state: bool):
    result = await kasa.set_power(alias, state)
    await broadcast({"type": "kasa", "alias": alias, "is_on": state})
    return result


# ── Lighting / Tuya ──────────────────────────────────────────────────────────

@app.get("/api/lighting/devices")
async def lighting_devices():
    return tuya.get_all_status()

@app.post("/api/lighting/{name}/power")
async def lighting_power(name: str, state: bool):
    result = tuya.set_power(name, state)
    await broadcast({"type": "tuya", "name": name, "is_on": state})
    return result

@app.post("/api/lighting/{name}/brightness")
async def lighting_brightness(name: str, value: int):
    return tuya.set_brightness(name, value)

@app.post("/api/lighting/{name}/color")
async def lighting_color(name: str, h: int, s: int, v: int):
    return tuya.set_color(name, h, s, v)

@app.post("/api/lighting/{name}/temp")
async def lighting_temp(name: str, kelvin: int):
    return tuya.set_color_temp(name, kelvin)


# ── EcoFlow ──────────────────────────────────────────────────────────────────

@app.get("/api/climate/status")
async def climate_status():
    return ecoflow.get_status()

@app.post("/api/climate/power")
async def climate_power(state: bool):
    result = ecoflow.set_power(state)
    await broadcast({"type": "ecoflow", "power": state})
    return result

@app.post("/api/climate/temperature")
async def climate_temp(temp: int):
    return ecoflow.set_temperature(temp)

@app.post("/api/climate/mode")
async def climate_mode(mode: str):
    return ecoflow.set_mode(mode)

@app.post("/api/climate/fan")
async def climate_fan(speed: str):
    return ecoflow.set_fan_speed(speed)


# ── Arduino IR + RF ──────────────────────────────────────────────────────────

@app.get("/api/ir/devices")
async def ir_devices():
    return arduino.get_devices()

@app.get("/api/ir/codes")
async def ir_codes():
    return arduino.get_all_codes()

@app.post("/api/ir/{device_id}/{command}")
async def ir_send(device_id: str, command: str):
    # Routes to IR or RF automatically based on device type in config.
    return await arduino.send_command(device_id, command)

@app.get("/api/ir/learn")
async def ir_learn(device: str, command: str):
    return await arduino.learn_ir_command(device, command)

@app.get("/api/rf/learn")
async def rf_learn(device: str, command: str):
    return await arduino.learn_rf_command(device, command)

@app.get("/api/ir/ping")
async def ir_ping():
    ok = await arduino.ping()
    return {"online": ok, "host": arduino.host, "mode": arduino.mode}


# ── Roku ─────────────────────────────────────────────────────────────────────

@app.get("/api/roku/discover")
async def roku_discover():
    devices = await roku.discover()
    return devices

@app.get("/api/roku/status")
async def roku_status():
    return await roku.get_status()

@app.get("/api/roku/apps")
async def roku_apps():
    return await roku.get_apps()

@app.post("/api/roku/keypress/{key}")
async def roku_key(key: str):
    return await roku.keypress(key)

@app.post("/api/roku/launch/{app_id}")
async def roku_launch(app_id: str):
    return await roku.launch_app(app_id)

@app.get("/api/roku/keys")
async def roku_keys():
    return roku.all_keys()


# ── Frontend -----------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ── Background polling ────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    asyncio.create_task(_poll_loop())


async def _poll_loop():
    # Initial discovery
    await asyncio.sleep(2)
    try:
        await kasa.discover()
        await roku.discover()
    except Exception as e:
        logger.error(f"Initial discovery error: {e}")

    while True:
        await asyncio.sleep(15)
        try:
            kasa_status = await kasa.get_all_status()
            await broadcast({"type": "poll_kasa", "devices": kasa_status})
        except Exception as e:
            logger.debug(f"Kasa poll: {e}")

        try:
            eco_status = ecoflow.get_status()
            await broadcast({"type": "poll_ecoflow", "status": eco_status})
        except Exception as e:
            logger.debug(f"EcoFlow poll: {e}")
