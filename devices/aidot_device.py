import asyncio
import colorsys
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import aiohttp
    from aidot.client import AidotClient
    AIDOT_AVAILABLE = True
except ImportError:
    AIDOT_AVAILABLE = False
    logger.warning("python-aidot not installed — run: pip install python-aidot")


class AidotController:
    def __init__(self, config: dict):
        self.config = config
        self._session: Optional[Any] = None
        self._client = None
        self._devices: Dict[str, Any] = {}  # name -> DeviceClient

    async def start(self):
        if not AIDOT_AVAILABLE:
            return
        username = self.config.get("username")
        password = self.config.get("password")
        if not username or not password:
            logger.info("AiDot: no credentials configured, skipping")
            return
        try:
            self._session = aiohttp.ClientSession()
            self._client = AidotClient(
                session=self._session,
                country_code=self.config.get("country_code", "US"),
                username=username,
                password=password,
            )
            await self._client.async_post_login()
            resp = await self._client.async_get_all_device()
            device_list = (resp or {}).get("device_list") or []
            for dev in device_list:
                dc = self._client.get_device_client(dev)
                name = dev.get("name") or dev.get("id", "unknown")
                self._devices[name] = dc
            logger.info(f"AiDot: logged in, {len(self._devices)} device(s) found")
        except Exception as e:
            logger.error(f"AiDot start failed: {e}")

    def get_all_status(self) -> List[dict]:
        result = []
        for name, dc in self._devices.items():
            try:
                s = dc.status
                info = dc.info
                result.append({
                    "name": name,
                    "id": info.dev_id if info else "",
                    "online": s.online if s else False,
                    "is_on": s.on if s else False,
                    "brightness": int(s.dimming * 1000 / 255) if (s and s.dimming is not None) else 0,
                    "cct": s.cct if s else 0,
                    "rgbw": list(s.rgbw) if (s and s.rgbw) else [0, 0, 0, 0],
                    "mode": "color" if (s and s.rgbw and any(s.rgbw[:3])) else "white",
                })
            except Exception as e:
                result.append({"name": name, "error": str(e)})
        return result

    async def set_power(self, name: str, state: bool) -> dict:
        dc = self._get_dc(name)
        try:
            if state:
                await dc.async_turn_on()
            else:
                await dc.async_turn_off()
            return {"name": name, "is_on": state}
        except ConnectionError:
            return {"error": f"'{name}' is offline — not yet locally connected"}
        except Exception as e:
            return {"error": str(e)}

    async def set_brightness(self, name: str, value: int) -> dict:
        dc = self._get_dc(name)
        try:
            brightness = max(0, min(255, int(value * 255 / 1000)))
            await dc.async_set_brightness(brightness)
            return {"name": name, "brightness": value}
        except ConnectionError:
            return {"error": f"'{name}' is offline"}
        except Exception as e:
            return {"error": str(e)}

    async def set_color(self, name: str, h: int, s: int, v: int) -> dict:
        dc = self._get_dc(name)
        try:
            r, g, b = colorsys.hsv_to_rgb(h / 360, s / 100, v / 100)
            rgbw = (int(r * 255), int(g * 255), int(b * 255), 0)
            await dc.async_set_rgbw(rgbw)
            return {"name": name, "rgbw": rgbw}
        except ConnectionError:
            return {"error": f"'{name}' is offline"}
        except Exception as e:
            return {"error": str(e)}

    async def set_color_temp(self, name: str, kelvin: int) -> dict:
        dc = self._get_dc(name)
        try:
            info = dc.info
            if info and getattr(info, "enable_cct", False):
                cct_min = getattr(info, "cct_min", None) or 2700
                cct_max = getattr(info, "cct_max", None) or 6500
                cct = max(cct_min, min(cct_max, int(
                    cct_min + (kelvin - 2700) * (cct_max - cct_min) / (6500 - 2700)
                )))
            else:
                cct = kelvin
            await dc.async_set_cct(cct)
            return {"name": name, "cct": cct}
        except ConnectionError:
            return {"error": f"'{name}' is offline"}
        except Exception as e:
            return {"error": str(e)}

    def get_groups_status(self) -> List[dict]:
        result = []
        for group in (self.config.get("groups") or []):
            gname = group["name"]
            members = group.get("devices") or []
            any_on = False
            member_status = []
            for dev_name in members:
                dc = self._devices.get(dev_name)
                s = dc.status if dc else None
                on = bool(s.on) if s else False
                if on:
                    any_on = True
                member_status.append({"name": dev_name, "online": bool(s.online) if s else False, "is_on": on})
            result.append({"name": gname, "devices": member_status, "is_on": any_on})
        return result

    def _group_members(self, group_name: str) -> List[str]:
        for group in (self.config.get("groups") or []):
            if group["name"] == group_name:
                return group.get("devices") or []
        raise ValueError(f"Group '{group_name}' not found")

    async def set_group_power(self, group_name: str, state: bool) -> dict:
        members = self._group_members(group_name)
        await asyncio.gather(*[self.set_power(m, state) for m in members])
        return {"group": group_name, "is_on": state}

    async def set_group_brightness(self, group_name: str, value: int) -> dict:
        members = self._group_members(group_name)
        await asyncio.gather(*[self.set_brightness(m, value) for m in members])
        return {"group": group_name, "brightness": value}

    async def set_group_color(self, group_name: str, h: int, s: int, v: int) -> dict:
        members = self._group_members(group_name)
        await asyncio.gather(*[self.set_color(m, h, s, v) for m in members])
        return {"group": group_name}

    async def set_group_color_temp(self, group_name: str, kelvin: int) -> dict:
        members = self._group_members(group_name)
        await asyncio.gather(*[self.set_color_temp(m, kelvin) for m in members])
        return {"group": group_name, "kelvin": kelvin}

    def device_names(self) -> List[str]:
        return list(self._devices.keys())

    def _get_dc(self, name: str):
        dc = self._devices.get(name)
        if not dc:
            raise ValueError(f"AiDot device '{name}' not found")
        return dc

    async def close(self):
        if self._client:
            try:
                await self._client.async_close()
            except Exception:
                pass
        if self._session:
            await self._session.close()
