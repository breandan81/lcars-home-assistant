import asyncio
import logging
import socket
import struct
import xml.etree.ElementTree as ET
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

ROKU_SSDP_ADDR = "239.255.255.250"
ROKU_SSDP_PORT = 1900
ROKU_SSDP_MX = 3
ROKU_ECP_PORT = 8060

SSDP_REQUEST = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {ROKU_SSDP_ADDR}:{ROKU_SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    f"MX: {ROKU_SSDP_MX}\r\n"
    'ST: roku:ecp\r\n'
    "\r\n"
)

ALL_KEYS = [
    "Home", "Back", "Select", "Up", "Down", "Left", "Right",
    "Play", "Pause", "Rev", "Fwd", "Info", "Backspace", "Search",
    "VolumeUp", "VolumeDown", "VolumeMute",
    "PowerOn", "PowerOff", "InputTuner", "InputHDMI1", "InputHDMI2",
    "InputHDMI3", "InputHDMI4", "InputAV1",
    "ChannelUp", "ChannelDown", "FindRemote",
]


def _ssdp_discover(timeout: int = 3) -> List[str]:
    """Multicast SSDP discovery, returns list of Roku base URLs."""
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(timeout)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(SSDP_REQUEST.encode(), (ROKU_SSDP_ADDR, ROKU_SSDP_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                response = data.decode(errors="ignore")
                for line in response.splitlines():
                    if line.lower().startswith("location:"):
                        url = line.split(":", 1)[1].strip()
                        if url not in found:
                            found.append(url)
            except socket.timeout:
                break
    finally:
        sock.close()
    return found


class RokuController:
    def __init__(self, config: dict):
        self.config = config
        self._base_url: Optional[str] = None
        if config.get("host"):
            self._base_url = f"http://{config['host']}:{ROKU_ECP_PORT}"

    async def discover(self) -> List[dict]:
        urls = await asyncio.get_event_loop().run_in_executor(None, _ssdp_discover)
        devices = []
        for url in urls:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(f"{url}query/device-info")
                    if resp.status_code == 200:
                        info = self._parse_device_info(resp.text)
                        info["base_url"] = url
                        devices.append(info)
                        # Auto-set first discovered device
                        if not self._base_url:
                            self._base_url = url
            except Exception as e:
                logger.warning(f"Roku probe failed for {url}: {e}")
        # If pinned host wasn't discovered via SSDP, add it
        if self.config.get("host") and not devices:
            url = f"http://{self.config['host']}:{ROKU_ECP_PORT}/"
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(f"{url}query/device-info")
                    info = self._parse_device_info(resp.text)
                    info["base_url"] = url
                    devices.append(info)
            except Exception as e:
                devices.append({"base_url": url, "error": str(e)})
        return devices

    async def get_status(self) -> dict:
        if not self._base_url:
            return {"error": "No Roku found. Run /api/roku/discover first."}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                info_resp = await client.get(f"{self._base_url}query/device-info")
                app_resp = await client.get(f"{self._base_url}query/active-app")
                info = self._parse_device_info(info_resp.text)
                info["active_app"] = self._parse_active_app(app_resp.text)
                return info
        except Exception as e:
            return {"error": str(e)}

    async def get_apps(self) -> List[dict]:
        if not self._base_url:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._base_url}query/apps")
                if resp.status_code != 200:
                    logger.error(f"Roku apps HTTP {resp.status_code}: {resp.text[:200]}")
                    return []
                root = ET.fromstring(resp.text)
                return [
                    {"id": app.get("id"), "name": app.text, "version": app.get("version")}
                    for app in root.findall("app")
                ]
        except Exception as e:
            logger.error(f"Roku get_apps: {e}")
            return []


    async def keypress(self, key: str) -> dict:
        if not self._base_url:
            return {"error": "No Roku found"}
        if key not in ALL_KEYS:
            return {"error": f"Unknown key '{key}'", "valid_keys": ALL_KEYS}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(f"{self._base_url}keypress/{key}")
                return {"sent": True, "key": key, "status": resp.status_code}
        except Exception as e:
            return {"error": str(e)}

    async def launch_app(self, app_id: str) -> dict:
        if not self._base_url:
            return {"error": "No Roku found"}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(f"{self._base_url}launch/{app_id}")
                return {"launched": app_id, "status": resp.status_code}
        except Exception as e:
            return {"error": str(e)}

    def _parse_device_info(self, xml_text: str) -> dict:
        try:
            root = ET.fromstring(xml_text)
            return {child.tag.replace("-", "_"): child.text for child in root}
        except Exception:
            return {}

    def _parse_active_app(self, xml_text: str) -> dict:
        try:
            root = ET.fromstring(xml_text)
            app = root.find("app")
            if app is not None:
                return {"id": app.get("id"), "name": app.text}
        except Exception:
            pass
        return {}

    @staticmethod
    def all_keys() -> List[str]:
        return ALL_KEYS
