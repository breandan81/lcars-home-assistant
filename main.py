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
from devices.aidot_device import AidotController
from devices.ecoflow_device import EcoflowController
from devices.arduino_ir import ArduinoIRController
from devices.roku_device import RokuController
from devices.samsung_tv import SamsungTVController
from devices.philips_tv import PhilipsTVController

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Load config ----------------------------------------------------------------
config: dict = {}
_config_path = Path("config.yaml")
for name in ("config.yaml", "config.yml"):
    p = Path(name)
    if p.exists():
        with open(p) as f:
            config = yaml.safe_load(f) or {}
        _config_path = p
        break

if not config:
    logger.warning("No config.yaml found — copy config.yaml.example and fill in your devices.")

# Controllers ----------------------------------------------------------------
kasa      = KasaController(config.get("kasa") or {})
aidot     = AidotController(config.get("aidot") or {})
ecoflow   = EcoflowController(config.get("ecoflow") or {})
arduino   = ArduinoIRController(config.get("arduino_ir") or {})
roku      = RokuController(config.get("roku") or {})
samsung   = SamsungTVController(config.get("samsung_tv") or {})
philips   = PhilipsTVController(config.get("philips_tv") or {})

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
    return aidot.get_all_status()

@app.post("/api/lighting/refresh")
async def lighting_refresh():
    await aidot.start()
    devices = aidot.get_all_status()
    return {"count": len(devices), "devices": devices}

@app.post("/api/lighting/{name}/power")
async def lighting_power(name: str, state: bool):
    result = await aidot.set_power(name, state)
    await broadcast({"type": "aidot", "name": name, "is_on": state})
    return result

@app.post("/api/lighting/{name}/brightness")
async def lighting_brightness(name: str, value: int):
    return await aidot.set_brightness(name, value)

@app.post("/api/lighting/{name}/color")
async def lighting_color(name: str, h: int, s: int, v: int):
    return await aidot.set_color(name, h, s, v)

@app.post("/api/lighting/{name}/temp")
async def lighting_temp(name: str, kelvin: int):
    return await aidot.set_color_temp(name, kelvin)

@app.get("/api/lighting/groups")
async def lighting_groups():
    return aidot.get_groups_status()

@app.post("/api/lighting/group/{name}/power")
async def lighting_group_power(name: str, state: bool):
    result = await aidot.set_group_power(name, state)
    await broadcast({"type": "aidot_group", "name": name, "is_on": state})
    return result

@app.post("/api/lighting/group/{name}/brightness")
async def lighting_group_brightness(name: str, value: int):
    return await aidot.set_group_brightness(name, value)

@app.post("/api/lighting/group/{name}/color")
async def lighting_group_color(name: str, h: int, s: int, v: int):
    return await aidot.set_group_color(name, h, s, v)

@app.post("/api/lighting/group/{name}/temp")
async def lighting_group_temp(name: str, kelvin: int):
    return await aidot.set_group_color_temp(name, kelvin)


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

@app.post("/api/ir/save-code")
async def ir_save_code(device_id: str, command_name: str, code: str):
    dev = arduino.devices_config.get(device_id)
    if dev is None:
        return {"error": f"Device '{device_id}' not found in config"}
    dev.setdefault("commands", {})[command_name] = code
    try:
        with open(_config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return {"saved": True, "device": device_id, "command": command_name, "code": code}
    except Exception as e:
        return {"error": f"Saved in memory but config write failed: {e}"}


# ── Roku ─────────────────────────────────────────────────────────────────────

class RokuSelectRequest(BaseModel):
    url: str

@app.get("/api/roku/discover")
async def roku_discover():
    devices = await roku.discover()
    return devices

@app.post("/api/roku/select")
async def roku_select(req: RokuSelectRequest):
    host = roku.select(req.url)
    if not config.get("roku"):
        config["roku"] = {}
    config["roku"]["host"] = host
    try:
        with open(_config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as e:
        return {"host": host, "error": f"Config write failed: {e}"}
    return {"host": host}

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


# ── Samsung TV ───────────────────────────────────────────────────────────────

@app.get("/api/samsung/discover")
async def samsung_discover():
    return await samsung.discover()

@app.get("/api/samsung/probe")
async def samsung_probe(host: str):
    loop = asyncio.get_event_loop()
    from devices.samsung_tv import _probe_samsung
    result = await loop.run_in_executor(None, _probe_samsung, host)
    if result:
        return result
    raise HTTPException(status_code=404, detail="No Samsung TV found at that IP")

@app.post("/api/samsung/select")
async def samsung_select(host: str, name: str = "", mac: str = ""):
    samsung.select(host, name, mac)
    cfg = config.setdefault("samsung_tv", {})
    cfg["host"] = host
    if name:
        cfg["name"] = name
    if mac:
        cfg["mac"] = mac
    cfg["token"] = ""
    try:
        with open(_config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as e:
        return {**samsung.get_status(), "warning": f"Config save failed: {e}"}
    return samsung.get_status()

@app.post("/api/samsung/wake")
async def samsung_wake():
    return await samsung.wake()

@app.get("/api/samsung/status")
async def samsung_status():
    return samsung.get_status()

@app.post("/api/samsung/pair")
async def samsung_pair():
    result = await samsung.pair()
    if result.get("paired"):
        config.setdefault("samsung_tv", {})["token"] = result["token"]
        try:
            with open(_config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as e:
            result["warning"] = f"Paired but config save failed: {e}"
    return result

@app.post("/api/samsung/keypress/{key}")
async def samsung_key(key: str):
    result = await samsung.send_key(key)
    if samsung.token and samsung.token != config.get("samsung_tv", {}).get("token"):
        config.setdefault("samsung_tv", {})["token"] = samsung.token
        try:
            with open(_config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception:
            pass
    return result


# ── Philips TV ────────────────────────────────────────────────────────────────

def _save_philips_config():
    cfg = config.setdefault("philips_tv", {})
    cfg.update({"host": philips.host, "name": philips.name})
    with open(_config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

@app.get("/api/philips/discover")
async def philips_discover():
    return await philips.discover()

@app.get("/api/philips/probe")
async def philips_probe(host: str):
    loop = asyncio.get_event_loop()
    from devices.philips_tv import _probe_android_tv
    result = await loop.run_in_executor(None, _probe_android_tv, host)
    if result:
        return result
    raise HTTPException(status_code=404, detail="No Philips TV found at that IP")

@app.post("/api/philips/select")
async def philips_select(host: str, name: str = ""):
    philips.select(host, name)
    try:
        _save_philips_config()
    except Exception as e:
        return {**philips.get_status(), "warning": f"Config save failed: {e}"}
    if philips._is_paired():
        asyncio.create_task(philips._connect())
    return philips.get_status()

@app.post("/api/philips/connect")
async def philips_connect():
    if not philips.host:
        raise HTTPException(status_code=400, detail="TV not configured")
    await philips._connect()
    return philips.get_status()

@app.get("/api/philips/status")
async def philips_status():
    return philips.get_status()

@app.post("/api/philips/pair/request")
async def philips_pair_request():
    return await philips.pair_request()

@app.post("/api/philips/pair/grant")
async def philips_pair_grant(pin: str):
    result = await philips.pair_grant(pin)
    if result.get("paired"):
        try:
            _save_philips_config()
        except Exception as e:
            result["warning"] = f"Paired but config save failed: {e}"
    return result

@app.post("/api/philips/keypress/{key}")
async def philips_key(key: str):
    return await philips.send_key(key)


# ── Scenes ───────────────────────────────────────────────────────────────────

@app.post("/api/scene/movie")
async def scene_movie():
    steps = {}

    async def _kasa_off():
        try:
            return await kasa.set_power("office", False)
        except Exception as e:
            return {"error": str(e)}

    # Step 1: fire simultaneously — Kasa off, projector on
    r1, r2 = await asyncio.gather(
        _kasa_off(),
        arduino.send_command("projector", "power_on"),
    )
    steps["office_plug_off"] = r1
    steps["projector_on"]    = r2

    # Step 2: soundbar on (slight delay so projector warm-up starts first)
    await asyncio.sleep(1.5)
    steps["soundbar_on"] = await arduino.send_command("soundbar", "power")

    # Step 3: soundbar optical — wait for soundbar to finish booting
    await asyncio.sleep(4)
    steps["soundbar_optical"] = await arduino.send_command("soundbar", "optical")

    return {"scene": "movie", "steps": steps}


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
        await aidot.start()
        await philips.startup()
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
