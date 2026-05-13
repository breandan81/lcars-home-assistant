ARDUINO_CLI = $(HOME)/.local/bin/arduino-cli
FQBN        = arduino:avr:uno
ESP_FQBN    = esp8266:esp8266:nodemcuv2
PORT        = /dev/ttyUSB0
ESP_PORT    = /dev/ttyUSB1
SKETCH      ?= ir_blaster_uno
ESP_SKETCH  ?= esp_rf_replay

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
	$(ARDUINO_CLI) monitor --port $(PORT) --config baudrate=9600

esp-monitor:
	$(ARDUINO_CLI) monitor --port $(ESP_PORT) --config baudrate=115200

.PHONY: all compile upload flash esp-compile esp-upload esp-flash monitor esp-monitor
