"""
Philips Android TV — control via Android TV Remote protocol (port 6466/6467).
Works with Funai-made North American Philips TVs and any other Android TV.
"""

import asyncio
import logging
import socket
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

_CERT_FILE = "philips_cert.pem"
_KEY_FILE  = "philips_key.pem"
_CLIENT_NAME = "LCARS Home Control"


def _probe_android_tv(host: str) -> Optional[dict]:
    """Check if host is an Android TV by probing port 6466 and reading the DIAL name."""
    try:
        sock = socket.create_connection((host, 6466), timeout=1.5)
        sock.close()
    except OSError:
        return None
    name = f"Android TV ({host})"
    try:
        r = httpx.get(f"http://{host}:8008/ssdp/device-desc.xml", timeout=1.5)
        if r.status_code == 200:
            import re
            m = re.search(r"<friendlyName>([^<]+)</friendlyName>", r.text)
            if m:
                name = m.group(1)
    except Exception:
        pass
    return {"host": host, "name": name}


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


class PhilipsTVController:
    def __init__(self, config: dict):
        self.host = config.get("host", "")
        self.name = config.get("name", "Philips TV")
        self._atv = None          # AndroidTVRemote instance (persistent connection)
        self._connected = False
        self._pairing_atv = None  # held open between pair_request and pair_grant

    def _is_paired(self) -> bool:
        return Path(_CERT_FILE).exists() and Path(_KEY_FILE).exists()

    def get_status(self) -> dict:
        return {
            "host": self.host,
            "name": self.name,
            "paired": self._is_paired(),
            "connected": self._connected,
        }

    def select(self, host: str, name: str = "") -> None:
        if host != self.host:
            self._disconnect()
        self.host = host
        if name:
            self.name = name

    def _disconnect(self):
        if self._atv:
            self._atv.disconnect()
            self._atv = None
        self._connected = False

    async def startup(self):
        """Auto-connect on server start if already configured and paired."""
        if self.host and self._is_paired():
            await self._connect()

    async def _connect(self):
        from androidtvremote2 import AndroidTVRemote, CannotConnect, InvalidAuth
        self._disconnect()
        atv = AndroidTVRemote(_CLIENT_NAME, _CERT_FILE, _KEY_FILE, self.host)
        await atv.async_generate_cert_if_missing()

        def on_available(available: bool):
            self._connected = available

        atv.add_is_available_updated_callback(on_available)
        try:
            await atv.async_connect()
            self._atv = atv
            self._connected = True
            atv.keep_reconnecting()
            logger.info(f"Philips TV connected: {self.host}")
        except (CannotConnect, InvalidAuth) as e:
            logger.warning(f"Philips TV connect failed: {e}")
            atv.disconnect()

    async def discover(self, timeout: float = 5.0) -> List[dict]:
        loop = asyncio.get_event_loop()
        candidates = await loop.run_in_executor(None, _ssdp_candidates, timeout / 2)
        results = await asyncio.gather(*[
            loop.run_in_executor(None, _probe_android_tv, host)
            for host in candidates
        ])
        return [r for r in results if r is not None]

    async def pair_request(self) -> dict:
        if not self.host:
            return {"error": "TV not configured"}
        from androidtvremote2 import AndroidTVRemote, CannotConnect
        if self._pairing_atv:
            self._pairing_atv.disconnect()
        atv = AndroidTVRemote(_CLIENT_NAME, _CERT_FILE, _KEY_FILE, self.host)
        await atv.async_generate_cert_if_missing()
        try:
            await atv.async_start_pairing()
            self._pairing_atv = atv
            return {"ok": True}
        except CannotConnect as e:
            atv.disconnect()
            return {"error": f"Cannot connect to TV: {e}"}
        except Exception as e:
            atv.disconnect()
            logger.error(f"Philips pair_request: {e}")
            return {"error": str(e)}

    async def pair_grant(self, pin: str) -> dict:
        if not self._pairing_atv:
            return {"error": "No pairing in progress — click Start Pairing first"}
        from androidtvremote2 import ConnectionClosed, InvalidAuth
        try:
            await self._pairing_atv.async_finish_pairing(pin)
            self._pairing_atv.disconnect()
            self._pairing_atv = None
            await self._connect()
            return {"paired": True}
        except InvalidAuth:
            return {"error": "Wrong PIN — try pairing again"}
        except ConnectionClosed:
            return {"error": "Connection lost — try pairing again"}
        except Exception as e:
            logger.error(f"Philips pair_grant: {e}")
            return {"error": str(e)}

    async def send_key(self, key: str) -> dict:
        if not self.host:
            return {"error": "TV not configured"}
        if not self._is_paired():
            return {"error": "TV not paired — complete pairing first"}
        if not self._atv or not self._connected:
            await self._connect()
        if not self._atv:
            return {"error": "TV unreachable"}
        from androidtvremote2 import ConnectionClosed
        try:
            self._atv.send_key_command(key)
            return {"sent": True, "key": key}
        except ConnectionClosed:
            self._connected = False
            return {"error": "Connection lost — TV may be off"}
        except Exception as e:
            logger.error(f"Philips send_key {key}: {e}")
            return {"error": str(e)}
