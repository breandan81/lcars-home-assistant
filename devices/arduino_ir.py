"""
arduino_ir.py — supports two transport modes:

  mode: wifi    → HTTP to an ESP32/ESP8266 running ir_blaster.ino
  mode: serial  → USB serial to an Arduino Uno running ir_blaster_uno.ino

Set arduino_ir.mode in config.yaml.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

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
            # Arduino Uno resets when DTR is asserted on connect — wait for it.
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
                resp = self._ser.readline().decode(errors='replace').strip()
                return resp
            except Exception as e:
                logger.error(f"Serial cmd '{line}' failed: {e}")
                self._ser = None
                return f"ERROR {e}"

    def ping(self) -> bool:
        return self._cmd("PING") == "PONG"

    def send_ir(self, protocol: str, code: str, bits: int = 32) -> Tuple[bool, str]:
        hex_code = code.upper().lstrip("0X") or "0"
        resp = self._cmd(f"SEND {protocol.upper()} {hex_code} {bits}")
        return resp == "OK", resp

    def learn(self) -> Optional[dict]:
        resp = self._cmd("LEARN", read_timeout=12.0)
        if resp.startswith("CODE"):
            parts = resp.split()
            if len(parts) >= 4:
                return {
                    "protocol": parts[1],
                    "code": "0x" + parts[2].lstrip("0").upper() or "0",
                    "bits": int(parts[3]),
                }
        return None  # TIMEOUT or error


# ── HTTP transport (ESP32 / ESP8266) ──────────────────────────────────────────

class _HttpTransport:
    def __init__(self, host: str, port: int = 80):
        self.base = f"http://{host}:{port}"

    def ping(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self.base}/ping", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def send_ir(self, protocol: str, code: str, bits: int = 32) -> Tuple[bool, str]:
        try:
            import requests
            r = requests.post(
                f"{self.base}/ir/send",
                json={"protocol": protocol, "code": code, "bits": bits},
                timeout=5,
            )
            r.raise_for_status()
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def learn(self) -> Optional[dict]:
        try:
            import requests
            r = requests.get(f"{self.base}/ir/learn", timeout=15)
            r.raise_for_status()
            data = r.json()
            if "code" in data:
                return data
        except Exception as e:
            logger.error(f"HTTP learn failed: {e}")
        return None


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
            logger.info(f"Arduino IR: serial mode on {port}")
        else:
            host = config.get("host", "")
            port = int(config.get("port", 80))
            self._transport = _HttpTransport(host, port) if host else None
            self._mode = "wifi"
            logger.info(f"Arduino IR: wifi mode → {host}:{port}")

    # ── Public API (all async — wraps blocking transport in executor) ─────────

    def get_devices(self) -> List[dict]:
        return [
            {
                "id": dev_id,
                "name": info.get("name", dev_id),
                "protocol": info.get("protocol", "NEC"),
                "commands": list(info.get("commands", {}).keys()),
            }
            for dev_id, info in self.devices_config.items()
        ]

    def get_all_codes(self) -> dict:
        return {
            dev_id: {
                "name": info.get("name", dev_id),
                "protocol": info.get("protocol", "NEC"),
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

        protocol = dev.get("protocol", "NEC")
        ok, msg = await asyncio.get_event_loop().run_in_executor(
            None, self._transport.send_ir, protocol, code, 32
        )
        if ok:
            return {"sent": True, "device": device_id, "command": command, "code": code}
        return {"error": msg, "device": device_id, "command": command}

    async def learn_command(self, device_id: str, command_name: str) -> dict:
        if not self._transport:
            return {"error": "Arduino not configured"}

        result = await asyncio.get_event_loop().run_in_executor(
            None, self._transport.learn
        )
        if result:
            if device_id not in self.devices_config:
                self.devices_config[device_id] = {"name": device_id, "commands": {}}
            self.devices_config[device_id].setdefault("commands", {})[command_name] = result["code"]
            logger.info(f"Learned {device_id}/{command_name} = {result['code']}")
            return {**result, "device": device_id, "command": command_name}
        return {"error": "timeout — no IR signal received"}

    async def ping(self) -> bool:
        if not self._transport:
            return False
        return await asyncio.get_event_loop().run_in_executor(None, self._transport.ping)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def host(self) -> str:
        if self._mode == "wifi" and self._transport:
            return self._transport.base
        if self._mode == "serial" and self._transport:
            return self._transport.port
        return ""
