"""
arduino_ir.py — IR/RF control across one or more blasters (USB Uno or WiFi ESP).

Multi-blaster config (preferred):
  arduino_ir:
    blasters:
      living_room: { mode: serial, serial_port: /dev/ttyUSB0, baud_rate: 9600 }
      bedroom:     { mode: wifi,   host: 192.168.68.72 }
    default_blaster: living_room   # optional; falls back to first
    garage_blaster:  living_room   # which blaster owns /garage/trigger
    temp_blaster:    living_room   # which blaster owns the DHT sensor
    devices:
      projector:  { name: ..., blaster: living_room, protocol: NEC, commands: {...} }
      bedroom_tv: { name: ..., blaster: bedroom,     protocol: NEC, commands: {...} }

Legacy single-blaster config (still supported — synthesizes blaster "default"):
  arduino_ir:
    mode: serial
    serial_port: /dev/ttyUSB0
    baud_rate: 9600
    devices: { ... }      # devices without a `blaster:` use the default

Device type in config:
  type: ir         (default) → SEND / LEARN
  type: rf                   → RFSEND / RFLEARN
  type: hunter_fan           → FANSEND / FANLEARN (66-bit RF)
"""

import asyncio
import glob
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Serial transport ──────────────────────────────────────────────────────────

class _SerialTransport:
    WATCHDOG_INTERVAL = 30   # seconds between health checks
    BACKOFF_MAX       = 60   # seconds

    def __init__(self, port: str, baud: int = 9600):
        self.port = port
        self.baud = baud
        self._ser  = None
        self._lock = threading.Lock()
        self._connect()
        threading.Thread(target=self._watchdog, daemon=True, name="serial-watchdog").start()

    def close(self):
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass
        self._ser = None

    def _connect(self):
        import serial as _serial
        # Close cleanly first so the old object doesn't toggle DTR on GC.
        self.close()

        # Try configured port first, then scan all ttyUSB*/ttyACM* ports.
        # Only the IR blaster sketch responds PONG to PING, so this isolates
        # it from any other Arduinos on the bus.
        candidates = [self.port] if self.port else []
        for pattern in ('/dev/ttyUSB*', '/dev/ttyACM*'):
            for p in sorted(glob.glob(pattern)):
                if p not in candidates:
                    candidates.append(p)

        for port in candidates:
            try:
                ser = _serial.Serial(port, self.baud, timeout=2)
                time.sleep(2.2)  # wait for bootloader after DTR reset
                ser.reset_input_buffer()
                ser.write(b'PING\n')
                if ser.readline().decode(errors='replace').strip() == 'PONG':
                    self._ser = ser
                    self.port = port
                    logger.info("Arduino found at %s @ %d", port, self.baud)
                    return
                ser.close()
            except Exception as e:
                logger.debug("Port %s: %s", port, e)

        logger.error("No Arduino found (tried: %s)", ', '.join(candidates))

    def _watchdog(self):
        backoff = 1
        while True:
            time.sleep(self.WATCHDOG_INTERVAL)
            if self.ping():
                backoff = 1
                continue
            logger.warning("Serial watchdog: %s unresponsive, reconnecting in %ds", self.port, backoff)
            time.sleep(backoff)
            with self._lock:
                self._connect()
            if self.ping():
                logger.info("Serial watchdog: %s recovered", self.port)
                backoff = 1
            else:
                backoff = min(backoff * 2, self.BACKOFF_MAX)

    def _cmd(self, line: str, read_timeout: float = 2.0) -> str:
        with self._lock:
            if self._ser is None or not self._ser.is_open:
                self._connect()
            if self._ser is None:
                return "ERROR not connected"
            try:
                self._ser.timeout = read_timeout
                self._ser.reset_input_buffer()
                self._ser.write((line + '\n').encode())
                return self._ser.readline().decode(errors='replace').strip()
            except Exception as e:
                logger.error("Serial cmd '%s' failed: %s", line, e)
                self._ser = None
                return f"ERROR {e}"

    def ping(self) -> bool:
        return self._cmd("PING") == "PONG"

    # IR
    def send_ir(self, protocol: str, code: str, bits: int = 32) -> Tuple[bool, str]:
        hex_code = code.upper().lstrip("0X") or "0"
        resp = self._cmd(f"SEND {protocol.upper()} {hex_code} {bits}")
        return resp == "OK", resp

    def learn_ir(self) -> Optional[dict]:
        resp = self._cmd("LEARN", read_timeout=12.0)
        if resp.startswith("CODE"):
            parts = resp.split()
            if len(parts) >= 4:
                return {"protocol": parts[1], "code": "0x" + parts[2], "bits": int(parts[3])}
        return None

    # RF
    def send_rf(self, code: str, bits: int = 24, protocol: int = 1) -> Tuple[bool, str]:
        hex_code = code.upper().lstrip("0X") or "0"
        resp = self._cmd(f"RFSEND {hex_code} {bits} {protocol}")
        return resp == "OK", resp

    def learn_rf(self) -> Optional[dict]:
        resp = self._cmd("RFLEARN", read_timeout=12.0)
        if resp.startswith("RFCODE"):
            parts = resp.split()
            if len(parts) >= 4:
                return {"code": "0x" + parts[1], "bits": int(parts[2]), "protocol": int(parts[3])}
        return None

    def send_fan(self, hex_str: str, bits: int = 66) -> Tuple[bool, str]:
        hex_code = hex_str.upper().lstrip("0X") or "0"
        resp = self._cmd(f"FANSEND {hex_code} {bits}")
        return resp == "OK", resp

    def learn_fan(self, timeout_ms: int = 12000) -> Optional[dict]:
        resp = self._cmd("FANLEARN", read_timeout=timeout_ms / 1000 + 2.0)
        if resp.startswith("FANCODE"):
            parts = resp.split()
            if len(parts) >= 3:
                return {"code": parts[1], "bits": int(parts[2])}
        return None

    def read_temp(self) -> Optional[dict]:
        resp = self._cmd("TEMP")
        if resp.startswith("TEMP"):
            parts = resp.split()
            if len(parts) == 3:
                return {"temp_c": float(parts[1]), "humidity": float(parts[2])}
        return None

    def garage_trigger(self) -> bool:
        return self._cmd("GDOOR") == "OK"


# ── HTTP transport (ESP32 / ESP8266) ──────────────────────────────────────────

class _HttpTransport:
    def __init__(self, host: str, port: int = 80):
        self.base = f"http://{host}:{port}"

    def _post(self, path: str, params: dict) -> Tuple[bool, str]:
        # Note: ESP sketch consumes query params, not JSON bodies — the
        # AsyncCallbackJsonWebHandler in the current ESPAsyncWebServer fork
        # crashes the ESP8266 with Exception 9 on body parse. Query params
        # work fine for the small payloads we send.
        try:
            import requests
            r = requests.post(f"{self.base}{path}", params=params, timeout=5)
            r.raise_for_status()
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def _get(self, path: str, timeout: float = 15) -> Optional[dict]:
        try:
            import requests
            r = requests.get(f"{self.base}{path}", timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"HTTP GET {path} failed: {e}")
            return None

    def ping(self) -> bool:
        try:
            import requests
            return requests.get(f"{self.base}/ping", timeout=3).status_code == 200
        except Exception:
            return False

    def send_ir(self, protocol: str, code: str, bits: int = 32) -> Tuple[bool, str]:
        return self._post("/ir/send", {"protocol": protocol, "code": code, "bits": bits})

    def learn_ir(self) -> Optional[dict]:
        data = self._get("/ir/learn")
        return data if data and "code" in data else None

    def send_rf(self, code: str, bits: int = 24, protocol: int = 1) -> Tuple[bool, str]:
        return self._post("/rf/send", {"code": code, "bits": bits, "protocol": protocol})

    def learn_rf(self) -> Optional[dict]:
        return self._get("/rf/learn")

    def read_temp(self) -> Optional[dict]:
        data = self._get("/temp")
        if data and "temp_c" in data:
            return data
        return None

    def send_fan(self, hex_str: str, bits: int = 66) -> Tuple[bool, str]:
        return self._post("/fan/send", {"hex": hex_str, "bits": bits})

    def learn_fan(self, timeout_ms: int = 12000) -> Optional[dict]:
        data = self._get(f"/fan/learn?timeout={timeout_ms}", timeout=timeout_ms / 1000 + 5)
        if data and "hex" in data:
            return {"code": data["hex"], "bits": data.get("bits", 66)}
        return None

    def garage_trigger(self) -> bool:
        ok, _ = self._post("/garage/trigger", {})
        return ok


# ── Controller ────────────────────────────────────────────────────────────────

class ArduinoIRController:
    def __init__(self, config: dict):
        self.config = config
        self.devices_config: Dict[str, Any] = config.get("devices") or {}

        blasters_cfg = config.get("blasters") or {}
        if not blasters_cfg:
            # Legacy flat config — synthesize a single blaster called "default".
            mode = config.get("mode", "wifi").lower()
            if mode == "serial" and config.get("serial_port"):
                blasters_cfg = {"default": {
                    "mode": "serial",
                    "serial_port": config["serial_port"],
                    "baud_rate":   config.get("baud_rate", 9600),
                }}
            elif config.get("host"):
                blasters_cfg = {"default": {
                    "mode": "wifi",
                    "host": config["host"],
                    "port": config.get("port", 80),
                }}

        self._transports: Dict[str, Any] = {}
        for name, bcfg in blasters_cfg.items():
            mode = (bcfg.get("mode") or "wifi").lower()
            try:
                if mode == "serial":
                    port = bcfg.get("serial_port", "/dev/ttyACM0")
                    baud = int(bcfg.get("baud_rate", 9600))
                    self._transports[name] = _SerialTransport(port, baud)
                    logger.info(f"Blaster '{name}': serial on {port} @ {baud}")
                elif bcfg.get("host"):
                    host = bcfg["host"]
                    port = int(bcfg.get("port", 80))
                    self._transports[name] = _HttpTransport(host, port)
                    logger.info(f"Blaster '{name}': wifi → {host}:{port}")
                else:
                    logger.warning(f"Blaster '{name}': skipped (no host/serial_port)")
            except Exception as e:
                logger.error(f"Blaster '{name}' init failed: {e}")

        self._default_blaster: Optional[str] = (
            config.get("default_blaster") or next(iter(self._transports), None)
        )
        self._garage_blaster:   Optional[str] = config.get("garage_blaster")   or self._default_blaster
        self._temp_blaster:     Optional[str] = config.get("temp_blaster")     or self._default_blaster
        # All learn operations route to the receiver-equipped blaster, regardless
        # of which blaster will eventually transmit the learned code.
        self._receiver_blaster: Optional[str] = config.get("receiver_blaster") or self._default_blaster

    # ── Routing ───────────────────────────────────────────────────────────────

    def _transport_for(self, device_id: str):
        dev = self.devices_config.get(device_id) or {}
        name = dev.get("blaster") or self._default_blaster
        return self._transports.get(name) if name else None

    def _blaster_name_for(self, device_id: str) -> Optional[str]:
        dev = self.devices_config.get(device_id) or {}
        return dev.get("blaster") or self._default_blaster

    def close_all(self):
        for t in self._transports.values():
            close = getattr(t, "close", None)
            if callable(close):
                try: close()
                except Exception: pass

    # ── Public API ────────────────────────────────────────────────────────────

    def get_devices(self) -> List[dict]:
        return [
            {
                "id": dev_id,
                "name": info.get("name", dev_id),
                "type": info.get("type", "ir"),
                "protocol": info.get("protocol", "NEC" if info.get("type", "ir") == "ir" else 1),
                "bit_length": info.get("bit_length", 24),
                "blaster": info.get("blaster") or self._default_blaster,
                "commands": list(info.get("commands", {}).keys()),
            }
            for dev_id, info in self.devices_config.items()
        ]

    def get_all_codes(self) -> dict:
        return {
            dev_id: {
                "name": info.get("name", dev_id),
                "type": info.get("type", "ir"),
                "protocol": info.get("protocol", "NEC"),
                "bit_length": info.get("bit_length", 24),
                "commands": info.get("commands", {}),
            }
            for dev_id, info in self.devices_config.items()
        }

    async def send_command(self, device_id: str, command: str) -> dict:
        dev = self.devices_config.get(device_id)
        if not dev:
            return {"error": f"Device '{device_id}' not in config"}
        transport = self._transport_for(device_id)
        if not transport:
            return {"error": f"No blaster '{self._blaster_name_for(device_id)}' for '{device_id}'"}
        code = dev.get("commands", {}).get(command)
        if not code:
            return {"error": f"Command '{command}' not found for '{device_id}'"}

        dev_type = dev.get("type", "ir")
        loop = asyncio.get_event_loop()
        if dev_type == "hunter_fan":
            bits = dev.get("bit_length", 66)
            ok, msg = await loop.run_in_executor(None, transport.send_fan, code, bits)
        elif dev_type == "rf":
            bits     = dev.get("bit_length", 24)
            protocol = dev.get("protocol", 1)
            ok, msg  = await loop.run_in_executor(None, transport.send_rf, code, bits, protocol)
        else:
            protocol = dev.get("protocol", "NEC")
            ok, msg  = await loop.run_in_executor(None, transport.send_ir, protocol, code, 32)

        blaster = self._blaster_name_for(device_id)
        if ok:
            return {"sent": True, "device": device_id, "command": command, "code": code, "blaster": blaster}
        return {"error": msg, "device": device_id, "command": command, "blaster": blaster}

    async def learn_ir_command(self, device_id: str, command_name: str) -> dict:
        transport = self._transports.get(self._receiver_blaster) if self._receiver_blaster else None
        if not transport:
            return {"error": f"No receiver_blaster configured (looked for '{self._receiver_blaster}')"}
        result = await asyncio.get_event_loop().run_in_executor(None, transport.learn_ir)
        return self._store_learned(result, device_id, command_name, "ir")

    async def learn_rf_command(self, device_id: str, command_name: str) -> dict:
        transport = self._transports.get(self._receiver_blaster) if self._receiver_blaster else None
        if not transport:
            return {"error": f"No receiver_blaster configured (looked for '{self._receiver_blaster}')"}
        dev = self.devices_config.get(device_id, {})
        loop = asyncio.get_event_loop()
        if dev.get("type") == "hunter_fan":
            result = await loop.run_in_executor(None, transport.learn_fan)
            return self._store_learned(result, device_id, command_name, "hunter_fan")
        result = await loop.run_in_executor(None, transport.learn_rf)
        return self._store_learned(result, device_id, command_name, "rf")

    def _store_learned(self, result: Optional[dict], device_id: str, command_name: str, dev_type: str) -> dict:
        if not result:
            return {"error": "timeout — no signal received"}
        if device_id not in self.devices_config:
            self.devices_config[device_id] = {"name": device_id, "type": dev_type, "commands": {}}
        self.devices_config[device_id].setdefault("commands", {})[command_name] = result.get("code", "")
        logger.info(f"Learned {device_id}/{command_name} = {result}")
        return {**result, "device": device_id, "command": command_name}

    async def trigger_garage(self) -> dict:
        t = self._transports.get(self._garage_blaster) if self._garage_blaster else None
        if not t:
            return {"error": f"No garage_blaster configured (looked for '{self._garage_blaster}')"}
        ok = await asyncio.get_event_loop().run_in_executor(None, t.garage_trigger)
        return {"triggered": True, "blaster": self._garage_blaster} if ok \
            else {"error": "Blaster did not confirm GDOOR", "blaster": self._garage_blaster}

    async def read_temp(self) -> Optional[dict]:
        t = self._transports.get(self._temp_blaster) if self._temp_blaster else None
        if not t:
            return None
        return await asyncio.get_event_loop().run_in_executor(None, t.read_temp)

    async def ping(self) -> bool:
        """Returns True if the default blaster is online (backwards-compat)."""
        t = self._transports.get(self._default_blaster) if self._default_blaster else None
        if not t:
            return False
        return await asyncio.get_event_loop().run_in_executor(None, t.ping)

    async def ping_all(self) -> Dict[str, dict]:
        """Ping every blaster; returns {name: {online, host, mode}}."""
        loop = asyncio.get_event_loop()
        out: Dict[str, dict] = {}
        for name, t in self._transports.items():
            online = await loop.run_in_executor(None, t.ping)
            if isinstance(t, _SerialTransport):
                host, mode = t.port, "serial"
            else:
                host, mode = t.base, "wifi"
            out[name] = {"online": online, "host": host, "mode": mode}
        return out

    # ── Legacy single-blaster compatibility ───────────────────────────────────
    # Existing callers read these to display "the" arduino's connection info.
    # We surface the default blaster's details so old endpoints keep working.

    @property
    def mode(self) -> str:
        t = self._transports.get(self._default_blaster) if self._default_blaster else None
        if isinstance(t, _SerialTransport): return "serial"
        if isinstance(t, _HttpTransport):   return "wifi"
        return ""

    @property
    def host(self) -> str:
        t = self._transports.get(self._default_blaster) if self._default_blaster else None
        if isinstance(t, _SerialTransport): return t.port
        if isinstance(t, _HttpTransport):   return t.base
        return ""

    @property
    def _transport(self):
        """Legacy alias: returns the default blaster's transport (used by shutdown handler)."""
        return self._transports.get(self._default_blaster) if self._default_blaster else None
