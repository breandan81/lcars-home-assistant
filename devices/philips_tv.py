"""
Philips JointSpace REST API (port 1925).

Older models (API v1-v5): no auth required.
Newer Android TVs (API v6+): HTTP Digest auth; requires one-time PIN pairing.
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import socket
import time
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

_DEVICE_INFO = {
    "device_name": "LCARS Home Control",
    "device_os": "Android",
    "app_id": "lcars.home",
    "app_name": "LCARS Home Control",
    "type": "native",
}
# Known HMAC-SHA1 secret used by Philips JointSpace v6 pairing
_SECRET = base64.b64decode("ZmVay1EQVFOaZhwQ4Ku6RFdD0ANd+Ybv5LCaH4WdrI=")


def _ssdp_candidates(timeout: float) -> List[str]:
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.255:1900\r\n"
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
        sock.sendto(msg, ("239.255.255.255", 1900))
        while True:
            try:
                _, addr = sock.recvfrom(4096)
                seen.add(addr[0])
            except socket.timeout:
                break
    finally:
        sock.close()
    return list(seen)


def _probe_host(host: str) -> Optional[dict]:
    for api_v in (6, 1):
        try:
            r = httpx.get(f"http://{host}:1925/{api_v}/system", timeout=1.0)
            if r.status_code == 200:
                data = r.json()
                name = data.get("name") or f"Philips TV ({host})"
                return {"host": host, "port": 1925, "api_version": api_v, "name": name}
        except Exception:
            pass
    return None


class PhilipsTVController:
    def __init__(self, config: dict):
        self.host = config.get("host", "")
        self.port = int(config.get("port", 1925))
        self.api_version = int(config.get("api_version", 6))
        self.username: Optional[str] = config.get("username") or None
        self.password: Optional[str] = config.get("password") or None
        self.name = config.get("name", "Philips TV")
        self._pair_state: dict = {}

    @property
    def _base(self) -> str:
        return f"http://{self.host}:{self.port}/{self.api_version}"

    def _auth(self) -> Optional[httpx.DigestAuth]:
        if self.username and self.password:
            return httpx.DigestAuth(self.username, self.password)
        return None

    def is_configured(self) -> bool:
        return bool(self.host)

    def get_status(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "api_version": self.api_version,
            "name": self.name,
            "paired": bool(self.username),
            "needs_auth": self.api_version >= 6,
        }

    def select(self, host: str, port: int = 1925, api_version: int = 6, name: str = "") -> None:
        if host != self.host:
            self.username = None
            self.password = None
        self.host = host
        self.port = port
        self.api_version = api_version
        if name:
            self.name = name

    async def discover(self, timeout: float = 5.0) -> List[dict]:
        loop = asyncio.get_event_loop()
        candidates = await loop.run_in_executor(None, _ssdp_candidates, timeout / 2)
        results = await asyncio.gather(*[
            loop.run_in_executor(None, _probe_host, host)
            for host in candidates
        ])
        return [r for r in results if r is not None]

    async def send_key(self, key: str) -> dict:
        if not self.host:
            return {"error": "Philips TV not configured"}
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self._base}/input/key",
                    json={"key": key},
                    auth=self._auth(),
                    timeout=5,
                )
                if r.status_code in (200, 204):
                    return {"sent": True, "key": key}
                return {"error": f"HTTP {r.status_code}"}
        except Exception as e:
            logger.error(f"Philips send_key {key}: {e}")
            return {"error": str(e)}

    async def pair_request(self) -> dict:
        """Start pairing — TV will display a PIN code."""
        if not self.host:
            return {"error": "Philips TV not configured"}
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self._base}/pair/request",
                    json={"device": _DEVICE_INFO, "scope": ["read", "write", "control"]},
                    timeout=5,
                )
                data = r.json()
            if data.get("error_id") not in (None, "SUCCESS"):
                return {"error": data["error_id"]}
            self._pair_state = {
                "device_id": data["device_id"],
                "auth_key": data["auth_key"],
            }
            return {"ok": True, "message": "PIN is now shown on your TV"}
        except Exception as e:
            logger.error(f"Philips pair_request: {e}")
            return {"error": str(e)}

    async def pair_grant(self, pin: str) -> dict:
        """Complete pairing with the PIN shown on the TV."""
        if not self._pair_state:
            return {"error": "No pairing in progress — click Start Pairing first"}
        device_id = self._pair_state["device_id"]
        auth_key = self._pair_state["auth_key"]
        ts = str(int(time.time()))
        sig = base64.b64encode(
            hmac.new(_SECRET, (ts + auth_key).encode(), hashlib.sha1).digest()
        ).decode()
        payload = {
            "auth": {
                "auth_AppId": "1",
                "pin": pin,
                "auth_timestamp": ts,
                "auth_signature": sig,
            },
            "device": _DEVICE_INFO,
        }
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self._base}/pair/grant",
                    json=payload,
                    auth=httpx.DigestAuth(device_id, pin),
                    timeout=5,
                )
                data = r.json() if r.content else {}
            if r.status_code not in (200, 204) and data.get("error_id") not in (None, "SUCCESS"):
                return {"error": data.get("error_id", f"HTTP {r.status_code}")}
            self.username = device_id
            self.password = auth_key
            self._pair_state = {}
            return {"paired": True, "username": device_id, "password": auth_key}
        except Exception as e:
            logger.error(f"Philips pair_grant: {e}")
            return {"error": str(e)}
