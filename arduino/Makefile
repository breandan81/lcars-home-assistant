ARDUINO_CLI = /tmp/arduino-cli
FQBN        = arduino:avr:uno
ESP_FQBN    = esp8266:esp8266:nodemcuv2
PORT        = /dev/ttyUSB0

all: compile

compile:
	$(ARDUINO_CLI) compile --fqbn $(FQBN) $(SKETCH)

upload:
	$(ARDUINO_CLI) upload --fqbn $(FQBN) --port $(PORT) $(SKETCH)

flash: compile upload

esp-compile:
	$(ARDUINO_CLI) compile --fqbn $(ESP_FQBN) $(SKETCH)

esp-upload:
	$(ARDUINO_CLI) upload --fqbn $(ESP_FQBN) --port $(PORT) $(SKETCH)

esp-flash: esp-compile esp-upload

monitor:
	$(ARDUINO_CLI) monitor --port $(PORT) --config baudrate=9600

esp-monitor:
	$(ARDUINO_CLI) monitor --port $(PORT) --config baudrate=115200

.PHONY: all compile upload flash esp-compile esp-upload esp-flash monitor esp-monitor
