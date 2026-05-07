"""
EcoFlow Wave 2 — local MQTT mode.

Setup:
  1. Install Mosquitto:  sudo apt install mosquitto mosquitto-clients
  2. Edit /etc/mosquitto/mosquitto.conf, add:
       listener 1883
       allow_anonymous true
  3. Restart: sudo systemctl restart mosquitto
  4. Redirect Wave 2 traffic to your machine:
     Option A — router DNS override: add DNS entry mqtt.ecoflow.com -> <your-server-ip>
     Option B — hosts file on the machine running this app (if the app acts as MQTT proxy).
     Option C — Use the EcoFlow IoT platform to get MQTT credentials, then:
       set mqtt_host to your machine IP in config.
  5. The Wave 2 will reconnect to your broker and start publishing status.

Topics (replace {SN} with your serial number):
  Status:  /sys/{SN}/cmd/set_reply
  Command: /sys/{SN}/cmd/set
"""

import json
import logging
import time
import threading
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    logger.warning("paho-mqtt not installed")


WAVE2_PARAMS = {
    # dp_id: (display_name, type)
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


class EcoflowController:
    def __init__(self, config: dict):
        self.config = config
        self.sn = config.get("serial_number", "")
        self.mode = config.get("mode", "mqtt_local")
        self._state: dict = {}
        self._client: Optional[object] = None
        self._connected = False

        if self.mode == "mqtt_local" and MQTT_AVAILABLE and self.sn:
            self._start_mqtt()

    def _start_mqtt(self):
        host = self.config.get("mqtt_host", "127.0.0.1")
        port = int(self.config.get("mqtt_port", 1883))

        client = mqtt.Client()
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        def _run():
            try:
                client.connect(host, port, keepalive=60)
                client.loop_forever()
            except Exception as e:
                logger.error(f"EcoFlow MQTT connection failed: {e}")

        self._client = client
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            topic_status = f"/sys/{self.sn}/cmd/set_reply"
            topic_quota = f"/sys/{self.sn}/app/get_message"
            client.subscribe([(topic_status, 0), (topic_quota, 0)])
            logger.info(f"EcoFlow MQTT connected, subscribed to {topic_status}")
            # Request current state
            self._request_status(client)
        else:
            logger.error(f"EcoFlow MQTT connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        logger.warning("EcoFlow MQTT disconnected")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            params = payload.get("params", payload)
            self._state.update(params)
            logger.debug(f"EcoFlow state update: {params}")
        except Exception as e:
            logger.error(f"EcoFlow MQTT parse error: {e}")

    def _request_status(self, client=None):
        if not (client or self._client):
            return
        c = client or self._client
        topic = f"/sys/{self.sn}/app/get_message"
        payload = json.dumps({
            "id": int(time.time()),
            "version": "1.0",
            "sn": self.sn,
            "moduleType": 3,
            "operateType": "latestQuotas",
            "params": {}
        })
        c.publish(topic, payload)

    def _publish_command(self, params: dict) -> dict:
        if not self._client or not self._connected:
            return {"error": "MQTT not connected — see README for setup"}
        topic = f"/sys/{self.sn}/cmd/set"
        payload = json.dumps({
            "id": int(time.time()),
            "version": "1.0",
            "sn": self.sn,
            "moduleType": 3,
            "operateType": "latestQuotas",
            "params": params
        })
        self._client.publish(topic, payload)
        return {"status": "sent", "params": params}

    def get_status(self) -> dict:
        if self.mode == "mqtt_local":
            return {
                "connected": self._connected,
                "serial_number": self.sn,
                "mode": self.mode,
                "state": self._state,
            }
        return {"error": "Cloud mode not enabled", "hint": "Set mode: mqtt_local in config"}

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
