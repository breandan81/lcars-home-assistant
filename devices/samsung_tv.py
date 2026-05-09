import asyncio
import logging
import socket
from typing import List, Optional

logger = logging.getLogger(__name__)

_APP_NAME = "LCARS Home Control"


_SSDP_ADDR = "239.255.255.255"
_SSDP_PORT = 1900
_SSDP_ST   = "urn:samsung.com:device:RemoteControlReceiver:1"


def _ssdp_search(timeout: float) -> List[dict]:
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {_SSDP_ADDR}:{_SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 3\r\n"
        f"ST: {_SSDP_ST}\r\n"
        "\r\n"
    ).encode()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    try:
        sock.sendto(msg, (_SSDP_ADDR, _SSDP_PORT))
        seen: set = set()
        devices: List[dict] = []
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                host = addr[0]
                if host in seen:
                    continue
                seen.add(host)
                text = data.decode(errors="replace")
                name = f"Samsung TV ({host})"
                for line in text.splitlines():
                    if line.upper().startswith("SERVER:"):
                        name = line.split(":", 1)[1].strip()
                        break
                devices.append({"host": host, "port": 8002, "name": name})
            except socket.timeout:
                break
    finally:
        sock.close()
    return devices


class SamsungTVController:
    def __init__(self, config: dict):
        self.host = config.get("host", "")
        self.port = int(config.get("port", 8002))
        self.token: Optional[str] = config.get("token") or None
        self.name = config.get("name", "Samsung TV")

    def is_configured(self) -> bool:
        return bool(self.host)

    def get_status(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "name": self.name,
            "paired": bool(self.token),
        }

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

    def select(self, host: str, name: str = "") -> None:
        if host != self.host:
            self.token = None
        self.host = host
        if name:
            self.name = name

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
