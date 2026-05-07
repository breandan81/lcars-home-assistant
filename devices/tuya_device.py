import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

try:
    import tinytuya
    TUYA_AVAILABLE = True
except ImportError:
    TUYA_AVAILABLE = False
    logger.warning("tinytuya not installed")


class TuyaController:
    def __init__(self, config: dict):
        self.config = config
        self._devices: Dict[str, Any] = {}
        self._build_devices()

    def _build_devices(self):
        for d in self.config.get("devices", []):
            try:
                bulb = tinytuya.BulbDevice(
                    dev_id=d["id"],
                    address=d["ip"],
                    local_key=d["key"],
                    version=float(d.get("version", "3.3")),
                )
                bulb.set_socketTimeout(3)
                bulb.set_socketRetryLimit(2)
                self._devices[d["name"]] = {"device": bulb, "config": d}
            except Exception as e:
                logger.error(f"Failed to init Tuya device {d.get('name')}: {e}")

    def _get_status(self, name: str) -> dict:
        entry = self._devices.get(name)
        if not entry:
            return {"name": name, "error": "not_found"}
        try:
            dev = entry["device"]
            status = dev.status()
            dps = status.get("dps", {})
            return {
                "name": name,
                "id": entry["config"]["id"],
                "ip": entry["config"]["ip"],
                "is_on": dps.get("1", False),
                "brightness": dps.get("3", 0),
                "color_temp": dps.get("4", 0),
                "color": dps.get("5", ""),
                "mode": dps.get("2", "white"),
            }
        except Exception as e:
            return {"name": name, "error": str(e)}

    def get_all_status(self) -> List[dict]:
        return [self._get_status(name) for name in self._devices]

    def set_power(self, name: str, state: bool) -> dict:
        dev = self._get_dev(name)
        if state:
            dev.turn_on()
        else:
            dev.turn_off()
        return self._get_status(name)

    def set_brightness(self, name: str, brightness: int) -> dict:
        dev = self._get_dev(name)
        dev.set_brightness(max(10, min(1000, brightness)))
        return self._get_status(name)

    def set_color(self, name: str, h: int, s: int, v: int) -> dict:
        dev = self._get_dev(name)
        dev.set_hsv(h, s / 100.0, v / 100.0)
        return self._get_status(name)

    def set_color_temp(self, name: str, kelvin: int) -> dict:
        dev = self._get_dev(name)
        # Tuya uses 0–1000 range; map 2700K–6500K
        val = int((kelvin - 2700) / (6500 - 2700) * 1000)
        dev.set_colourtemp(max(0, min(1000, val)))
        return self._get_status(name)

    def set_scene(self, name: str, scene: int) -> dict:
        dev = self._get_dev(name)
        dev.set_scene(scene)
        return self._get_status(name)

    def _get_dev(self, name: str):
        entry = self._devices.get(name)
        if not entry:
            raise ValueError(f"Tuya device '{name}' not found")
        return entry["device"]

    def device_names(self) -> List[str]:
        return list(self._devices.keys())
