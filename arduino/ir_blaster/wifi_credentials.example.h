// Copy this file to wifi_credentials.h and fill in your network details.
// wifi_credentials.h is gitignored.
//
// DEVICE_NAME identifies this blaster on the network. The ESP advertises
// itself as <DEVICE_NAME>.local via mDNS, so LCARS can reach it without
// caring about its DHCP-assigned IP. Use kebab-case, room-prefixed:
//   "lcars-bedroom", "lcars-office", "lcars-livingroom"
#pragma once

#define WIFI_SSID     "YOUR_SSID"
#define WIFI_PASSWORD "YOUR_PASSWORD"
#define DEVICE_NAME   "lcars-blaster"
