# Future Tasks

## Voice Control

Local wake-word voice assistant, server-side (mic attached to server PC in same room as projector).

### Hardware needed
- USB mic (cardioid, pointed toward seating area away from speakers)
- USB speaker or 3.5mm aux speaker for TTS responses
  (do NOT route through Vizio soundbar — creates dependency on it being on/right input)

### Stack
- **Wake word**: openWakeWord (free, custom word trainable)
- **STT**: faster-whisper, `small` model (244 MB), fast on CPU
- **LLM**: KoboldCPP local API (`/v1/chat/completions`, OpenAI-compatible)
- **TTS**: Piper TTS + voice model (~50-150 MB)
- **Audio I/O**: sounddevice + numpy (no ffmpeg needed)

### New dependencies
```
faster-whisper
piper-tts
sounddevice
numpy
openWakeWord
```

### Design decisions already made
- Server-side mic (not browser) — server is in same room as projector
- Toggle button in LCARS UI header — WebSocket-controlled, latching, green/dim
- Auto-mute when projector is known on (IR state heuristic)
- Confirmation beep after wake word triggers
- Tune wake word to something 2-3 syllables with uncommon phonemes — avoid "computer"
- KoboldCPP grammar-constrained JSON output for reliable intent parsing

### Flow
```
wake word detected
  → play confirmation beep
  → sounddevice records until silence
  → faster-whisper transcribes → text
  → KoboldCPP: text + system prompt → {"action": "...", "reply": "..."}
  → backend calls its own API (existing LCARS endpoints)
  → Piper speaks reply → USB/aux speakers
```

### Rough scope
~300 lines: voice.py backend module, new WebSocket endpoint in main.py,
voice panel / toggle button in LCARS UI.

---

## Other ideas noted during build
- Roku: add search/keyboard input endpoint
- EcoFlow: revisit local API if EcoFlow publishes one for Wave 2
- Ceiling fan direction indicator (currently no state feedback from RF)
