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
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Serial transport ──────────────────────────────────────────────────────────

class _SerialTransport:
    def __init__(self, port: str, baud: int = 9600):
        self.port = port
        self.baud = baud
        self._ser = None
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        try:
            import serial as _serial
            self._ser = _serial.Serial(self.port, self.baud, timeout=2)
            # Uno resets on DTR assert — wait for bootloader to finish.
            time.sleep(2.2)
            self._ser.reset_input_buffer()
            logger.info(f"Serial connected: {self.port} @ {self.baud}")
        except Exception as e:
            logger.error(f"Serial connect failed ({self.port}): {e}")
            self._ser = None

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
                logger.error(f"Serial cmd '{line}' failed: {e}")
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


# ── Controller ────────────────────────────────────────────────────────────────

class ArduinoIRController:
    def __init__(self, config: dict):
        self.config = config
        self.devices_config: Dict[str, Any] = config.get("devices", {})

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
        if dev_type == "rf":
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
