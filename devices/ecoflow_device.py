"""
EcoFlow Wave 2 — local MQTT or cloud MQTT mode.

Local mode (mode: mqtt_local):
  Requires Mosquitto running locally and DNS redirect of mqtt.ecoflow.com
  to this machine. See README for full setup.

Cloud mode (mode: cloud):
  Fetches MQTT credentials from EcoFlow's IoT API on startup.
  Needs access_key and secret_key from developer.ecoflow.com.
  No local broker or DNS changes required.
"""

import hashlib
import hmac
import json
import logging
import random
import string
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    logger.warning("paho-mqtt not installed")

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


WAVE2_PARAMS = {
    "temp": ("Temperature °C", "int"),
    "setTemp": ("Set Temp °C", "int"),
    "fanLevel": ("Fan Level 0-2", "int"),
    "workMode": ("Mode 0=cool 1=heat 2=fan", "int"),
    "mainSwitch": ("Power", "bool"),
    "condenser": ("Compressor", "bool"),
    "batSoc": ("Battery %", "int"),
    "batInputWatts": ("Charging W", "int"),
    "outWatts": ("AC draw W", "int"),
}

ECOFLOW_API = "https://api-e.ecoflow.com"


class EcoflowController:
    def __init__(self, config: dict):
        self.config = config
        self.sn = config.get("serial_number", "")
        self.mode = config.get("mode", "mqtt_local")
        self._state: dict = {}
        self._client: Optional[object] = None
        self._connected = False
        self._cloud_prefix = ""

        if not MQTT_AVAILABLE or not self.sn:
            return

        if self.mode == "cloud":
            t = threading.Thread(target=self._start_cloud_mqtt, daemon=True)
            t.start()
        elif self.mode == "mqtt_local":
            self._start_local_mqtt()

    # ── Local MQTT ────────────────────────────────────────────────────────────

    def _start_local_mqtt(self):
        host = self.config.get("mqtt_host", "127.0.0.1")
        port = int(self.config.get("mqtt_port", 1883))
        client = mqtt.Client()
        client.on_connect = self._on_connect_local
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        def _run():
            try:
                client.connect(host, port, keepalive=60)
                client.loop_forever()
            except Exception as e:
                logger.error(f"EcoFlow MQTT connection failed: {e}")

        self._client = client
        threading.Thread(target=_run, daemon=True).start()

    def _on_connect_local(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            client.subscribe([
                (f"/sys/{self.sn}/cmd/set_reply", 0),
                (f"/sys/{self.sn}/app/get_message", 0),
            ])
            logger.info(f"EcoFlow local MQTT connected, SN={self.sn}")
            self._request_status_local(client)
        else:
            logger.error(f"EcoFlow local MQTT connect failed rc={rc}")

    def _request_status_local(self, client=None):
        c = client or self._client
        if not c:
            return
        payload = json.dumps({
            "id": int(time.time()), "version": "1.0", "sn": self.sn,
            "moduleType": 3, "operateType": "latestQuotas", "params": {}
        })
        c.publish(f"/sys/{self.sn}/app/get_message", payload)

    # ── Cloud MQTT ────────────────────────────────────────────────────────────

    def _start_cloud_mqtt(self):
        access_key = self.config.get("access_key", "")
        secret_key = self.config.get("secret_key", "")
        if not access_key or not secret_key:
            logger.error("EcoFlow cloud: access_key and secret_key required in config")
            return
        try:
            creds = self._fetch_cloud_credentials(access_key, secret_key)
        except Exception as e:
            logger.error(f"EcoFlow cloud credential fetch failed: {e}")
            return

        self._cloud_prefix = f"/open/{access_key}/{self.sn}"
        client_id = f"LCARS_{''.join(random.choices(string.ascii_lowercase, k=6))}"
        client = mqtt.Client(client_id=client_id)
        client.username_pw_set(creds["certificateAccount"], creds["certificatePassword"])

        if creds.get("protocol", "mqtt") == "mqtts":
            client.tls_set()

        client.on_connect = self._on_connect_cloud
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        def _run():
            try:
                client.connect(creds["url"], int(creds["port"]), keepalive=60)
                client.loop_forever()
            except Exception as e:
                logger.error(f"EcoFlow cloud MQTT failed: {e}")

        self._client = client
        threading.Thread(target=_run, daemon=True).start()

    def _fetch_cloud_credentials(self, access_key: str, secret_key: str) -> dict:
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests library not installed")
        nonce = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        timestamp = str(int(time.time() * 1000))
        params_str = f"accessKey={access_key}&nonce={nonce}&timestamp={timestamp}"
        sign = hmac.new(secret_key.encode(), params_str.encode(), hashlib.sha256).hexdigest()
        headers = {"accessKey": access_key, "nonce": nonce, "timestamp": timestamp, "sign": sign}
        r = _requests.get(f"{ECOFLOW_API}/iot-open/sign/certification", headers=headers, timeout=10)
        data = r.json()
        if str(data.get("code")) != "0":
            raise ValueError(f"EcoFlow API error: {data.get('message', data)}")
        return data["data"]

    def _on_connect_cloud(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            client.subscribe([
                (f"{self._cloud_prefix}/get_reply", 0),
                (f"{self._cloud_prefix}/status", 0),
            ])
            logger.info(f"EcoFlow cloud MQTT connected, prefix={self._cloud_prefix}")
            client.publish(f"{self._cloud_prefix}/get", json.dumps({"sn": self.sn}))
        else:
            logger.error(f"EcoFlow cloud MQTT connect failed rc={rc}")

    # ── Shared ────────────────────────────────────────────────────────────────

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        logger.warning("EcoFlow MQTT disconnected")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            params = payload.get("params", payload)
            if isinstance(params, dict):
                self._state.update(params)
            logger.debug(f"EcoFlow state update: {params}")
        except Exception as e:
            logger.error(f"EcoFlow MQTT parse error: {e}")

    def _publish_command(self, params: dict) -> dict:
        if not self._client or not self._connected:
            return {"error": "MQTT not connected — check config and connection"}
        topic = (f"{self._cloud_prefix}/set" if self.mode == "cloud"
                 else f"/sys/{self.sn}/cmd/set")
        payload = json.dumps({
            "id": int(time.time()), "version": "1.0", "sn": self.sn,
            "moduleType": 3, "operateType": "latestQuotas", "params": params
        })
        self._client.publish(topic, payload)
        return {"status": "sent", "params": params}

    # ── Public API ────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "serial_number": self.sn,
            "mode": self.mode,
            "state": self._state,
        }

    def set_power(self, state: bool) -> dict:
        return self._publish_command({"mainSwitch": 1 if state else 0})

    def set_temperature(self, temp_c: int) -> dict:
        return self._publish_command({"setTemp": max(16, min(30, temp_c))})

    def set_mode(self, mode: str) -> dict:
        mode_map = {"cool": 0, "heat": 1, "fan": 2}
        if mode not in mode_map:
            return {"error": f"Unknown mode '{mode}', valid: cool, heat, fan"}
        return self._publish_command({"workMode": mode_map[mode]})

    def set_fan_speed(self, speed: str) -> dict:
        speed_map = {"low": 0, "medium": 1, "high": 2}
        if speed not in speed_map:
            return {"error": f"Unknown fan speed '{speed}', valid: low, medium, high"}
        return self._publish_command({"fanLevel": speed_map[speed]})
