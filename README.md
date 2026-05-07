# LCARS Home Control

A locally-hosted Star Trek LCARS interface for:
- **TP-Link Kasa** smart plugs (local, no cloud)
- **AiDot bulbs** via local Tuya protocol (no cloud)
- **EcoFlow Wave 2** via local MQTT
- **Arduino IR blaster** (ESP32) → ViewSonic projector + Vizio soundbar
- **Roku** via official ECP (fully local)

---

## Quick Start

```bash
cd smart-home-lcars
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp config.yaml.example config.yaml
# Edit config.yaml with your device details

uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Open: http://localhost:8080

---

## Device Setup

### Kasa Smart Plugs
No extra setup needed. Click **Discover** in the UI and it will find all Kasa devices on your LAN via broadcast. If discovery misses a device, add it by IP in `config.yaml` under `kasa.devices`.

### AiDot Bulbs (Tuya local)

AiDot bulbs use the Tuya protocol locally. You need three things per bulb: **device ID**, **local IP**, and **local key**.

**Step 1 — Find device IDs and IPs:**
```bash
python3 -m tinytuya scan
```
This scans your network and prints a table. Note the `Device ID` and `IP` for each bulb.

**Step 2 — Get the local key:**
1. Create a free account at https://iot.tuya.com
2. Create a project → Cloud → Development → Link Devices
3. Use the Tuya Smart or Smart Life app, add your AiDot bulbs there (they pair the same way)
4. In the Tuya IoT portal, go to your project → Devices → find your bulb → click the device → copy the **Local Key**

Alternatively, run the tinytuya wizard which guides you through this:
```bash
python3 -m tinytuya wizard
```

**Step 3 — Add to config.yaml:**
```yaml
tuya:
  devices:
    - id: "abc123abc123abc1"
      ip: "192.168.1.60"
      key: "abcdef1234567890"
      version: "3.3"
      name: "Bedroom Bulb"
```

### EcoFlow Wave 2 (local MQTT)

The Wave 2 normally talks to EcoFlow's cloud MQTT server. To control it locally, you redirect it to your own MQTT broker.

**Step 1 — Install Mosquitto:**
```bash
sudo apt install mosquitto mosquitto-clients
```

**Step 2 — Configure Mosquitto for local connections:**
Edit `/etc/mosquitto/mosquitto.conf`:
```
listener 1883
allow_anonymous true
```
```bash
sudo systemctl restart mosquitto
```

**Step 3 — Redirect the Wave 2 to your broker:**

Option A — Router DNS override (recommended):
- In your router's DNS settings, add: `mqtt.ecoflow.com` → `<your-server-IP>`
- The Wave 2 will connect to your Mosquitto instead of EcoFlow's cloud

Option B — If your router supports it, create a static DHCP entry for the Wave 2 and use firewall rules to redirect port 8883 → 1883 on your server.

**Step 4 — Set your serial number in config.yaml:**
The SN is printed on the sticker on the bottom of your Wave 2 (format: EFDELTA...).
```yaml
ecoflow:
  mode: "mqtt_local"
  serial_number: "EFDELTA12345"
  mqtt_host: "127.0.0.1"
  mqtt_port: 1883
```

**Step 5 — Restart the app.** The EcoFlow section will show "MQTT Connected" when the device reconnects.

> **Note:** While the device is redirected to your local broker, the EcoFlow mobile app will stop working (it can't reach the cloud either). You can restore normal operation by removing the DNS override.

### Arduino IR Blaster (ESP32)

**Hardware:**
- Any ESP32 board (e.g., ESP32 DevKit, Wemos D1 Mini32)
- IR LED (TSAL6100 or similar) + 100Ω resistor between LED+ and GPIO 4
- IR receiver module (TSOP38238) connected to GPIO 14

**Arduino Libraries** (install in Arduino IDE → Library Manager):
- `IRremoteESP8266` by crankyoldgit
- `ESPAsyncWebServer` by lacamera/ESP32
- `AsyncTCP` (ESP32) or `ESPAsyncTCP` (ESP8266)
- `ArduinoJson` by Benoit Blanchon

**Flash the sketch:**
1. Open `arduino/ir_blaster.ino` in Arduino IDE
2. Set your WiFi SSID and password at the top of the file
3. Select your board: ESP32 Dev Module
4. Flash

**Set the IP in config.yaml:**
After flashing, open Serial Monitor at 115200 baud to see the assigned IP, then:
```yaml
arduino_ir:
  host: "192.168.1.70"
```

**Learn new IR codes:**
In the UI, go to **Display** → scroll to "IR Code Learner". Enter a device and command name, click **Capture IR**, point your remote at the Arduino, and press the button. Copy the captured hex code into `config.yaml` under the appropriate device.

The IR codes in `config.yaml.example` are common ViewSonic/Vizio codes — your specific model may use different codes. Always learn yours.

### Roku

No setup needed — Roku is fully local via the official ECP protocol. Click **Discover** in the Roku section and it will find your Roku via SSDP. Or set the IP directly in `config.yaml`:
```yaml
roku:
  host: "192.168.1.80"
```

---

## Running as a Service

```bash
# Create a systemd service
sudo tee /etc/systemd/system/lcars.service <<EOF
[Unit]
Description=LCARS Home Control
After=network.target

[Service]
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now lcars
```

Access at: `http://<your-server-ip>:8080`
