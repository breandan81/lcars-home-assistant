import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

try:
    from kasa import Discover, SmartPlug, SmartStrip, SmartDevice
    KASA_AVAILABLE = True
except ImportError:
    KASA_AVAILABLE = False
    logger.warning("python-kasa not installed")


class KasaController:
    def __init__(self, config: dict):
        self.config = config
        self._devices: Dict[str, Any] = {}
        self._pinned = config.get("devices") or []

    async def discover(self) -> List[dict]:
        if not KASA_AVAILABLE:
            return []
        try:
            found = await Discover.discover(timeout=5)
            self._devices = {}
            for host, dev in found.items():
                await dev.update()
                self._devices[dev.alias or host] = dev
            # Also add any pinned devices not found by broadcast
            for p in self._pinned:
                if p["alias"] not in self._devices:
                    try:
                        dev = SmartPlug(p["host"])
                        await dev.update()
                        self._devices[p["alias"]] = dev
                    except Exception as e:
                        logger.warning(f"Pinned Kasa device {p['alias']} unreachable: {e}")
            return [self._dev_to_dict(alias, d) for alias, d in self._devices.items()]
        except Exception as e:
            logger.error(f"Kasa discover error: {e}")
            return []

    async def get_all_status(self) -> List[dict]:
        if not self._devices:
            await self.discover()
        result = []
        for alias, dev in self._devices.items():
            try:
                await dev.update()
                result.append(self._dev_to_dict(alias, dev))
            except Exception as e:
                result.append({"alias": alias, "error": str(e)})
        return result

    async def set_power(self, alias: str, state: bool) -> dict:
        if alias not in self._devices:
            await self.discover()
        dev = self._devices.get(alias)
        if not dev:
            raise ValueError(f"Device '{alias}' not found")
        if state:
            await dev.turn_on()
        else:
            await dev.turn_off()
        await dev.update()
        return self._dev_to_dict(alias, dev)

    def _dev_to_dict(self, alias: str, dev) -> dict:
        try:
            return {
                "alias": alias,
                "host": dev.host,
                "model": dev.model,
                "is_on": dev.is_on,
                "type": "strip" if hasattr(dev, "children") else "plug",
                "children": [
                    {"alias": c.alias, "is_on": c.is_on}
                    for c in (dev.children or [])
                ] if hasattr(dev, "children") else [],
            }
        except Exception:
            return {"alias": alias, "host": getattr(dev, "host", "?"), "error": "parse_error"}
