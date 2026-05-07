import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class ArduinoIRController:
    def __init__(self, config: dict):
        self.host = config.get("host", "")
        self.port = int(config.get("port", 80))
        self.devices_config: Dict[str, Any] = config.get("devices", {})
        self._base_url = f"http://{self.host}:{self.port}" if self.host else ""

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
        if not self._base_url:
            return {"error": "Arduino host not configured"}

        dev = self.devices_config.get(device_id)
        if not dev:
            return {"error": f"Device '{device_id}' not in config"}

        code = dev.get("commands", {}).get(command)
        if not code:
            return {"error": f"Command '{command}' not found for device '{device_id}'"}

        protocol = dev.get("protocol", "NEC")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self._base_url}/ir/send",
                    json={"protocol": protocol, "code": code, "bits": 32},
                )
                resp.raise_for_status()
                return {"sent": True, "device": device_id, "command": command, "code": code}
        except httpx.ConnectError:
            return {"error": f"Cannot reach Arduino at {self.host}:{self.port}"}
        except Exception as e:
            return {"error": str(e)}

    async def learn_command(self, device_id: str, command_name: str) -> dict:
        """Ask the ESP32 to capture the next IR signal it sees."""
        if not self._base_url:
            return {"error": "Arduino host not configured"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self._base_url}/ir/learn", timeout=15.0)
                resp.raise_for_status()
                data = resp.json()
                if "code" in data:
                    # Save it into our runtime config (not persisted — update config.yaml manually)
                    if device_id not in self.devices_config:
                        self.devices_config[device_id] = {"name": device_id, "commands": {}}
                    self.devices_config[device_id].setdefault("commands", {})[command_name] = data["code"]
                    logger.info(f"Learned {device_id}/{command_name} = {data['code']}")
                return {**data, "device": device_id, "command": command_name}
        except httpx.ConnectError:
            return {"error": f"Cannot reach Arduino at {self.host}:{self.port}"}
        except Exception as e:
            return {"error": str(e)}

    async def ping(self) -> bool:
        if not self._base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._base_url}/ping")
                return resp.status_code == 200
        except Exception:
            return False
