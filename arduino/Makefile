ARDUINO_CLI = /tmp/arduino-cli
FQBN        = arduino:avr:uno
PORT        = /dev/ttyUSB0

all: compile

compile:
	$(ARDUINO_CLI) compile --fqbn $(FQBN) $(SKETCH)

upload:
	$(ARDUINO_CLI) upload --fqbn $(FQBN) --port $(PORT) $(SKETCH)

flash: compile upload

monitor:
	$(ARDUINO_CLI) monitor --port $(PORT) --config baudrate=9600

.PHONY: all compile upload flash monitor
