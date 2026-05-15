"""
EcoFlow Wave 2 — private app API (same as mobile app).

Config (config.yaml):
  ecoflow:
    serial_number: KT21ZAH5HG2P1003
    access_key:    <from developer.ecoflow.com>  # REST state reads
    secret_key:    <from developer.ecoflow.com>  # REST state reads
    email:         <EcoFlow account email>
    password:      <EcoFlow account password>    # base64'd by login endpoint

Auth flow (private API — same as mobile app):
  1. POST /auth/login  → token + userId
  2. GET  /iot-auth/app/certification  → MQTT certificateAccount/Password
  3. Connect mqtts://mqtt.ecoflow.com:8883

MQTT topics (private API, prefix = /app/{userId}/{sn}):
  Subscribe: /app/device/property/{sn}         — real-time state pushes
             {prefix}/thing/property/set_reply  — command ACKs
  Publish:   {prefix}/thing/property/set        — send commands
             {prefix}/thing/property/get        — request full state

Wave 2 command reference (moduleType=1):
  operateType  params
  powerMode    {powerMode: 1=on, 2=standby, 3=off}
  setTemp      {setTemp: 16-30 °C}
  mainMode     {mainMode: 0=cool, 1=heat, 2=fan}
  fanValue     {fanValue: 0=low, 1=med, 2=high}

State param names from Open API REST:
  pd.powerMode, pd.pdSubMode, pd.fanValue, pd.setTempCel,
  pd.heatEnv (÷100=°C), bms.bmsSoc, bms.outWatts
"""

import base64
import hashlib
import hmac
import json
import logging
import random
import string
import threading
import time
import uuid
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

ECOFLOW_API = "https://api.ecoflow.com"


class EcoflowController:
    def __init__(self, config: dict):
        self.config      = config
        self.sn          = config.get("serial_number", "").strip()
        self._access_key = config.get("access_key", "").strip()
        self._secret_key = config.get("secret_key", "").strip()
        self._email      = config.get("email", "").strip()
        self._password   = config.get("password", "").strip()

        self._state: dict  = {}
        self._client       = None
        self._connected    = False
        self._user_id: str = ""
        self._cmd_prefix   = ""  # /app/{userId}/{sn}

        if not self.sn:
            return

        threading.Thread(target=self._init, daemon=True).start()

    # ── Open API REST (state reads) ───────────────────────────────────────────

    def _open_api_headers(self) -> dict:
        nonce = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        ts    = str(int(time.time() * 1000))
        s     = f"accessKey={self._access_key}&nonce={nonce}&timestamp={ts}"
        sign  = hmac.new(self._secret_key.encode(), s.encode(), hashlib.sha256).hexdigest()
        return {"accessKey": self._access_key, "nonce": nonce,
                "timestamp": ts, "sign": sign, "Content-Type": "application/json"}

    def _fetch_rest_status(self) -> dict:
        if not REQUESTS_AVAILABLE or not self._access_key:
            return {}
        try:
            r = _requests.get(
                f"{ECOFLOW_API}/iot-open/sign/device/quota/all?sn={self.sn}",
                headers=self._open_api_headers(), timeout=10,
            )
            data = r.json()
            if str(data.get("code")) == "0":
                return data.get("data", {})
            logger.warning(f"EcoFlow REST: {data.get('message')}")
        except Exception as e:
            logger.warning(f"EcoFlow REST failed: {e}")
        return {}

    # ── Private app API login ─────────────────────────────────────────────────

    def _app_login(self) -> dict:
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests not installed")
        # Password must be base64-encoded (not MD5 — confirmed from HA integration source)
        pwd_b64 = base64.b64encode(self._password.encode()).decode()
        r = _requests.post(
            f"{ECOFLOW_API}/auth/login",
            json={"email": self._email, "password": pwd_b64,
                  "scene": "IOT_APP", "userType": "ECOFLOW"},
            headers={"Content-Type": "application/json", "lang": "en_US"},
            timeout=10,
        )
        data = r.json()
        if str(data.get("code")) != "0":
            raise ValueError(f"EcoFlow login failed: {data.get('message', data)}")
        return data["data"]

    def _fetch_app_mqtt_creds(self, token: str, user_id: str) -> dict:
        hdrs = {"lang": "en_US", "authorization": f"Bearer {token}",
                "Content-Type": "application/json"}
        r = _requests.get(
            f"{ECOFLOW_API}/iot-auth/app/certification",
            headers=hdrs, json={"userId": user_id}, timeout=10,
        )
        data = r.json()
        if str(data.get("code")) != "0":
            raise ValueError(f"EcoFlow MQTT cert failed: {data.get('message', data)}")
        return data["data"]

    # ── MQTT ──────────────────────────────────────────────────────────────────

    def _start_mqtt(self, creds: dict, user_id: str):
        self._user_id    = user_id
        self._cmd_prefix = f"/app/{user_id}/{self.sn}"

        client_id = f"ANDROID_{uuid.uuid4().hex.upper()}_{user_id}"
        client = mqtt.Client(client_id=client_id)
        client.username_pw_set(creds["certificateAccount"], creds["certificatePassword"])
        client.tls_set()
        client.on_connect    = self._on_connect
        client.on_message    = self._on_message
        client.on_disconnect = self._on_disconnect

        def _run():
            try:
                client.connect(creds.get("url", "mqtt.ecoflow.com"),
                               int(creds.get("port", 8883)), keepalive=15)
                client.loop_forever()
            except Exception as e:
                logger.error(f"EcoFlow MQTT failed: {e}")

        self._client = client
        threading.Thread(target=_run, daemon=True).start()

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            logger.error(f"EcoFlow MQTT connect failed rc={rc}")
            return
        self._connected = True
        p = self._cmd_prefix
        result = client.subscribe([
            (f"/app/device/property/{self.sn}",    0),
            (f"{p}/thing/property/set_reply",       0),
            (f"{p}/thing/property/get_reply",       0),
        ])
        logger.info(f"EcoFlow MQTT connected user={self._user_id} granted={result}")
        # Request full state via private MQTT (get_reply will populate self._state)
        client.publish(f"{p}/thing/property/get", json.dumps({
            "id": str(random.randint(900000, 999999)), "version": "1.0",
            "sn": self.sn,
        }))

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        logger.warning("EcoFlow MQTT disconnected")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if "code" in payload:
                logger.info(f"EcoFlow set_reply: operateType={payload.get('operateType')} code={payload.get('code')}")
            params  = payload.get("params", payload)
            if isinstance(params, dict):
                self._state.update(params)
                logger.debug(f"EcoFlow state ({msg.topic}): {list(params.keys())[:6]}")
        except Exception as e:
            logger.error(f"EcoFlow MQTT parse error: {e}")

    # ── Startup ───────────────────────────────────────────────────────────────

    def _init(self):
        rest = self._fetch_rest_status()
        if rest:
            self._state.update(rest)
            logger.info(f"EcoFlow seeded {len(rest)} keys from REST")

        if not MQTT_AVAILABLE or not self._email or not self._password:
            logger.info("EcoFlow: no app credentials, REST-only mode")
            threading.Thread(target=self._rest_poll_loop, daemon=True).start()
            return
        try:
            login_data = self._app_login()
            token   = login_data["token"]
            user_id = str(login_data["user"]["userId"])
            logger.info(f"EcoFlow login OK userId={user_id}")
            creds = self._fetch_app_mqtt_creds(token, user_id)
            self._start_mqtt(creds, user_id)
        except Exception as e:
            logger.error(f"EcoFlow init failed: {e}")
        threading.Thread(target=self._rest_poll_loop, daemon=True).start()

    def _rest_poll_loop(self):
        """Refresh configuration fields from REST every 60s (MQTT only pushes sensor deltas)."""
        while True:
            time.sleep(60)
            rest = self._fetch_rest_status()
            if rest:
                # Only update config fields that MQTT doesn't push reliably
                config_keys = {k: v for k, v in rest.items()
                               if any(k.startswith(p) for p in ("pd.setTemp", "pd.powerMode", "pd.pdSubMode", "pd.mainMode", "pd.tempSys", "bms.bmsSoc"))}
                self._state.update(config_keys)
                logger.debug(f"EcoFlow REST refresh: {list(config_keys.keys())}")

    # ── Commands ──────────────────────────────────────────────────────────────

    def _publish_command(self, operate_type: str, params: dict) -> dict:
        if not self._client or not self._connected:
            return {"error": "MQTT not connected — commands unavailable"}
        payload = json.dumps({
            "id":          random.randint(100000, 999999),  # must be integer, not string
            "version":     "1.0",
            "from":        "App",                           # required by Wave 2 firmware
            "sn":          self.sn,
            "moduleType":  1,
            "operateType": operate_type,
            "params":      params,
        })
        self._client.publish(f"{self._cmd_prefix}/thing/property/set", payload, qos=1)
        logger.info(f"EcoFlow cmd {operate_type}: {params}")
        self._state.update(params)
        return {"status": "sent", "operateType": operate_type, "params": params}

    # ── Public API ────────────────────────────────────────────────────────────

    def _use_fahrenheit(self) -> bool:
        return self._state.get("pd.tempSys", 0) == 1

    def get_status(self) -> dict:
        state    = self._state if self._state else self._fetch_rest_status()
        heat_env = state.get("pd.heatEnv")
        temp_c   = round(heat_env / 100, 1) if heat_env is not None else None
        # pd.setTemp is the authoritative displayed setpoint, in the device's display unit
        set_temp_raw = state.get("pd.setTemp")
        use_f = self._use_fahrenheit()
        if set_temp_raw is not None:
            set_temp_c = round((set_temp_raw - 32) * 5 / 9) if use_f else set_temp_raw
        else:
            set_temp_c = state.get("pd.setTempCel")
        mode_map = {0: "cool", 1: "heat", 2: "fan", 3: "auto"}
        fan_map  = {0: "low",  1: "medium", 2: "high"}
        return {
            "connected":   self._connected,
            "serial":      self.sn,
            "power":       bool(state.get("pd.powerMode", 0)),
            "mode":        mode_map.get(state.get("pd.pdSubMode"), "unknown"),
            "fan":         fan_map.get(state.get("pd.fanValue"),   "unknown"),
            "temp_c":      temp_c,
            "temp_unit":   "C",
            "set_temp_c":  set_temp_c,
            "battery_pct": state.get("bms.bmsSoc"),
            "ac_watts":    state.get("bms.outWatts"),
            "state":       state,
        }

    def set_power(self, on: bool) -> dict:
        # 1=startup, 2=standby, 3=shutdown
        return self._publish_command("powerMode", {"powerMode": 1 if on else 3})

    def set_temperature(self, temp_c: int) -> dict:
        # UI always sends Celsius; device expects its display unit
        if self._use_fahrenheit():
            temp_val = max(60, min(86, round(temp_c * 9 / 5 + 32)))
        else:
            temp_val = max(16, min(30, temp_c))
        return self._publish_command("setTemp", {"setTemp": temp_val})

    def set_mode(self, mode: str) -> dict:
        mode_map = {"cool": 0, "heat": 1, "fan": 2}
        if mode not in mode_map:
            return {"error": f"Unknown mode '{mode}', valid: cool, heat, fan"}
        return self._publish_command("mainMode", {"mainMode": mode_map[mode]})

    def set_fan_speed(self, speed: str) -> dict:
        speed_map = {"low": 0, "medium": 1, "high": 2}
        if speed not in speed_map:
            return {"error": f"Unknown fan speed '{speed}', valid: low, medium, high"}
        return self._publish_command("fanValue", {"fanValue": speed_map[speed]})
