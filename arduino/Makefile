ARDUINO_CLI = $(HOME)/.local/bin/arduino-cli
FQBN        = arduino:avr:uno
ESP_FQBN    = esp8266:esp8266:nodemcuv2
PORT        = /dev/ttyUSB0
ESP_PORT    = /dev/ttyUSB1
SKETCH      ?= ir_blaster_uno
ESP_SKETCH  ?= esp_rf_replay
HUNTER_SKETCH ?= hunter_rx_debug
WIRE_SKETCH   ?= wire_capture
NIMROD_SKETCH ?= nimrod

all: compile

compile:
	$(ARDUINO_CLI) compile --fqbn $(FQBN) $(SKETCH)

upload:
	$(ARDUINO_CLI) upload --fqbn $(FQBN) --port $(PORT) $(SKETCH)

flash: compile upload

esp-compile:
	$(ARDUINO_CLI) compile --fqbn $(ESP_FQBN) $(ESP_SKETCH)

esp-upload:
	$(ARDUINO_CLI) upload --fqbn $(ESP_FQBN) --port $(ESP_PORT) $(ESP_SKETCH)

esp-flash: esp-compile esp-upload

monitor:
	$(ARDUINO_CLI) monitor --port $(PORT) --config baudrate=115200

esp-monitor:
	$(ARDUINO_CLI) monitor --port $(ESP_PORT) --config baudrate=115200

hunter-compile:
	$(ARDUINO_CLI) compile --fqbn $(FQBN) $(HUNTER_SKETCH)

hunter-upload:
	$(ARDUINO_CLI) upload --fqbn $(FQBN) --port $(PORT) $(HUNTER_SKETCH)

hunter-flash: hunter-compile hunter-upload

nimrod-compile:
	$(ARDUINO_CLI) compile --fqbn $(ESP_FQBN) $(NIMROD_SKETCH)

nimrod-upload:
	$(ARDUINO_CLI) upload --fqbn $(ESP_FQBN) --port $(ESP_PORT) $(NIMROD_SKETCH)

nimrod-flash: nimrod-compile nimrod-upload

wire-compile:
	$(ARDUINO_CLI) compile --fqbn $(FQBN) $(WIRE_SKETCH)

wire-upload:
	$(ARDUINO_CLI) upload --fqbn $(FQBN) --port $(PORT) $(WIRE_SKETCH)

wire-flash: wire-compile wire-upload

.PHONY: all compile upload flash esp-compile esp-upload esp-flash monitor esp-monitor \
        hunter-compile hunter-upload hunter-flash nimrod-compile nimrod-upload nimrod-flash \
        wire-compile wire-upload wire-flash
