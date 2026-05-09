import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_APP_NAME = "LCARS Home Control"


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
