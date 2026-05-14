"""
arduino_ir.py — IR and RF control via Arduino Uno (USB serial) or ESP32 (WiFi HTTP).

Config mode:
  mode: serial  → Uno/clone over USB, sketch: ir_blaster_uno.ino
  mode: wifi    → ESP32/ESP8266 over WiFi, sketch: ir_blaster.ino

Device type in config:
  type: ir  (default) → uses SEND/LEARN serial commands
  type: rf            → uses RFSEND/RFLEARN serial commands
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

    def _post(self, path: str, json: dict) -> Tuple[bool, str]:
        try:
            import requests
            r = requests.post(f"{self.base}{path}", json=json, timeout=5)
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

        mode = config.get("mode", "wifi").lower()
        if mode == "serial":
            port = config.get("serial_port", "/dev/ttyACM0")
            baud = int(config.get("baud_rate", 9600))
            self._transport = _SerialTransport(port, baud)
            self._mode = "serial"
            logger.info(f"Arduino: serial mode on {port}")
        else:
            host = config.get("host", "")
            port = int(config.get("port", 80))
            self._transport = _HttpTransport(host, port) if host else None
            self._mode = "wifi"
            logger.info(f"Arduino: wifi mode → {host}:{port}")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_devices(self) -> List[dict]:
        return [
            {
                "id": dev_id,
                "name": info.get("name", dev_id),
                "type": info.get("type", "ir"),
                "protocol": info.get("protocol", "NEC" if info.get("type", "ir") == "ir" else 1),
                "bit_length": info.get("bit_length", 24),
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
        if not self._transport:
            return {"error": "Arduino not configured"}
        dev = self.devices_config.get(device_id)
        if not dev:
            return {"error": f"Device '{device_id}' not in config"}
        code = dev.get("commands", {}).get(command)
        if not code:
            return {"error": f"Command '{command}' not found for '{device_id}'"}

        dev_type = dev.get("type", "ir")
        if dev_type == "hunter_fan":
            bits = dev.get("bit_length", 66)
            ok, msg = await asyncio.get_event_loop().run_in_executor(
                None, self._transport.send_fan, code, bits
            )
        elif dev_type == "rf":
            bits     = dev.get("bit_length", 24)
            protocol = dev.get("protocol", 1)
            ok, msg  = await asyncio.get_event_loop().run_in_executor(
                None, self._transport.send_rf, code, bits, protocol
            )
        else:
            protocol = dev.get("protocol", "NEC")
            ok, msg  = await asyncio.get_event_loop().run_in_executor(
                None, self._transport.send_ir, protocol, code, 32
            )

        if ok:
            return {"sent": True, "device": device_id, "command": command, "code": code}
        return {"error": msg, "device": device_id, "command": command}

    async def learn_ir_command(self, device_id: str, command_name: str) -> dict:
        if not self._transport:
            return {"error": "Arduino not configured"}
        result = await asyncio.get_event_loop().run_in_executor(None, self._transport.learn_ir)
        return self._store_learned(result, device_id, command_name, "ir")

    async def learn_rf_command(self, device_id: str, command_name: str) -> dict:
        if not self._transport:
            return {"error": "Arduino not configured"}
        dev = self.devices_config.get(device_id, {})
        if dev.get("type") == "hunter_fan":
            result = await asyncio.get_event_loop().run_in_executor(None, self._transport.learn_fan)
            return self._store_learned(result, device_id, command_name, "hunter_fan")
        result = await asyncio.get_event_loop().run_in_executor(None, self._transport.learn_rf)
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
        if not self._transport:
            return {"error": "Arduino not configured"}
        ok = await asyncio.get_event_loop().run_in_executor(None, self._transport.garage_trigger)
        return {"triggered": True} if ok else {"error": "Arduino did not confirm GDOOR"}

    async def read_temp(self) -> Optional[dict]:
        if not self._transport:
            return None
        return await asyncio.get_event_loop().run_in_executor(None, self._transport.read_temp)

    async def ping(self) -> bool:
        if not self._transport:
            return False
        return await asyncio.get_event_loop().run_in_executor(None, self._transport.ping)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def host(self) -> str:
        if self._mode == "serial" and self._transport:
            return self._transport.port
        if self._mode == "wifi" and self._transport:
            return self._transport.base
        return ""
