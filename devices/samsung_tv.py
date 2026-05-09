import asyncio
import logging
import socket
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

_APP_NAME = "LCARS Home Control"

_SSDP_ADDR = "239.255.255.255"
_SSDP_PORT = 1900


def _probe_samsung(host: str) -> Optional[dict]:
    """Check if host is a Samsung TV by hitting the REST info endpoint."""
    try:
        r = httpx.get(f"http://{host}:8001/api/v2/", timeout=1.5)
        if r.status_code == 200:
            data = r.json()
            device = data.get("device", {})
            name = (device.get("name") or device.get("modelName")
                    or f"Samsung TV ({host})")
            mac = device.get("wifiMac") or device.get("mac") or ""
            return {"host": host, "port": 8002, "name": name, "mac": mac}
    except Exception:
        pass
    return None


def _wake_on_lan(mac: str, host: str = "") -> None:
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    magic = b"\xff" * 6 + mac_bytes * 16
    targets = []
    if host:
        targets.append(host)        # unicast directly to TV's IP (works over WiFi)
    targets.append("255.255.255.255")  # broadcast fallback
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr in targets:
            for port in (9, 7):
                s.sendto(magic, (addr, port))


def _ssdp_search(timeout: float) -> List[dict]:
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {_SSDP_ADDR}:{_SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 3\r\n"
        "ST: ssdp:all\r\n"
        "\r\n"
    ).encode()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    seen: set = set()
    try:
        sock.sendto(msg, (_SSDP_ADDR, _SSDP_PORT))
        while True:
            try:
                _, addr = sock.recvfrom(4096)
                seen.add(addr[0])
            except socket.timeout:
                break
    finally:
        sock.close()

    devices = []
    for host in seen:
        result = _probe_samsung(host)
        if result:
            devices.append(result)
    return devices


class SamsungTVController:
    def __init__(self, config: dict):
        self.host = config.get("host", "")
        self.port = int(config.get("port", 8002))
        self.token: Optional[str] = config.get("token") or None
        self.name = config.get("name", "Samsung TV")
        self.mac: str = config.get("mac", "")

    def is_configured(self) -> bool:
        return bool(self.host)

    def get_status(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "name": self.name,
            "paired": bool(self.token),
            "mac": self.mac,
        }

    def select(self, host: str, name: str = "", mac: str = "") -> None:
        if host != self.host:
            self.token = None
        self.host = host
        if name:
            self.name = name
        if mac:
            self.mac = mac

    async def wake(self) -> dict:
        if not self.host:
            return {"error": "Samsung TV not configured"}
        loop = asyncio.get_event_loop()
        # Send WoL and attempt WebSocket KEY_POWER concurrently; either may work
        # depending on whether the TV is in deep sleep or network standby.
        wol_task = None
        if self.mac:
            wol_task = loop.run_in_executor(None, _wake_on_lan, self.mac, self.host)
        ws_task = loop.run_in_executor(None, self._send, "KEY_POWER", self.token, 15)
        if wol_task:
            await asyncio.gather(wol_task, return_exceptions=True)
        try:
            await ws_task
            return {"sent": True, "method": "websocket"}
        except Exception:
            if self.mac:
                return {"sent": True, "method": "wol", "note": "TV may be in deep sleep — WoL sent but response not guaranteed"}
            return {"error": "TV unreachable — ensure network standby is enabled (Settings → General → Instant On)"}

    def _send(self, key: str, token: Optional[str], timeout: int = 5) -> Optional[str]:
        from samsungtvws import SamsungTVWS
        with SamsungTVWS(host=self.host, port=self.port, token=token,
                         timeout=timeout, name=_APP_NAME) as tv:
            tv.send_key(key)
            return tv.token

    async def send_key(self, key: str) -> dict:
        if not self.host:
            return {"error": "Samsung TV not configured"}
        try:
            loop = asyncio.get_event_loop()
            new_token = await loop.run_in_executor(None, self._send, key, self.token, 5)
            if new_token and new_token != self.token:
                self.token = new_token
            return {"sent": True, "key": key}
        except Exception as e:
            logger.error(f"Samsung send_key {key}: {e}")
            return {"error": str(e)}

    async def discover(self, timeout: float = 5.0) -> List[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _ssdp_search, timeout)

    async def pair(self) -> dict:
        """Connect without a token to trigger the TV's authorization popup.
        Blocks until the user accepts (up to 30 s) or times out."""
        if not self.host:
            return {"error": "Samsung TV not configured"}
        try:
            loop = asyncio.get_event_loop()
            token = await loop.run_in_executor(None, self._send, "KEY_MUTE", None, 30)
            if token:
                self.token = token
                return {"paired": True, "token": token}
            return {"error": "Connected but no token returned"}
        except Exception as e:
            logger.error(f"Samsung pair failed: {e}")
            return {"error": str(e)}
