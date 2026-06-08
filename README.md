# E.M.I.L.Y.

**E**fficient **M**achine **I**ntelligence for **L**ocal **Y**ield

A cross-platform, voice-first desktop AI assistant for **Windows**, **macOS**, and **Linux**. Talk to Emily to browse the web, control your computer, read your screen, manage files, run code, schedule reminders, and more — all through a single conversational interface with a live PyQt6 HUD.

---

## Table of Contents

- [What is Emily?](#what-is-emily)
- [Key Features](#key-features)
- [Voice Pipelines](#voice-pipelines)
- [LLM Providers](#llm-providers)
- [What Emily Can Do](#what-emily-can-do)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Windows](#windows)
  - [Linux](#linux)
  - [macOS](#macos)
- [Running Emily](#running-emily)
- [First-Time Setup Wizard](#first-time-setup-wizard)
- [Configuration](#configuration)
- [GPU Acceleration (Local TTS)](#gpu-acceleration-local-tts)
- [Cross-Platform Notes](#cross-platform-notes)
- [Security](#security)
- [Architecture](#architecture)

---

## What is Emily?

Emily is a local desktop AI co-pilot designed to **hear**, **speak**, **remember**, and **act** on your computer. Instead of switching between apps, terminals, and browsers, you talk (or type) to Emily and she uses a large set of agent tools to get things done.

The UI is a F.R.I.D.A.Y./JARVIS-style control panel: a floating orb, live system metrics, camera feed with optional face detection, conversation log, thinking stream, file drop zone, and text command input.

Emily supports multiple LLM backends (cloud and local) and three voice pipelines, so you can optimize for privacy, latency, or quality depending on your setup.

<img width="1038" height="717" alt="emily-comms-on" src="https://github.com/user-attachments/assets/fed43388-5502-4a7f-b8c9-17c1861ea4c1" />
<img width="1034" height="715" alt="emily-comms-off" src="https://github.com/user-attachments/assets/c043e5b3-e356-4741-b3c6-6288181c3a51" />
<img width="131" height="110" alt="image" src="https://github.com/user-attachments/assets/2578676f-c864-4d70-8982-8cca59a472a2" />


---

## Key Features

- **Voice-first interaction** — speak naturally; Emily listens, thinks, and responds aloud
- **Flexible AI backends** — Gemini, OpenAI, Anthropic, Ollama, or LM Studio
- **Three voice modes** — fully local STT/TTS, cloud Deepgram voice, or native realtime (Gemini Live / OpenAI Realtime)
- **20+ built-in tools** — browser automation, screen/camera vision, file management, OS control, coding agents, and more
- **Long-term memory** — remembers facts you ask her to save across sessions
- **Scheduled reminders** — one-off or recurring tasks with spoken briefings (news, weather, custom LLM prompts)
- **Multi-step agent** — plans and executes complex goals that require several tools
- **MCP integration** — extend capabilities via Model Context Protocol servers (e.g. Massive, Firecrawl)
- **Sleep mode** — optional face-detection mute when you step away from the camera
- **Cross-platform** — Windows, macOS, and Linux with OS-aware schedulers, paths, and hotkeys

---

## Voice Pipelines

| Mode | STT | TTS | Best for |
|------|-----|-----|----------|
| **local** | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | [Supertonic 3](https://github.com/supertonic-ai/supertonic) | Privacy, offline-capable voice, local LLMs |
| **deepgram** | Deepgram Nova | Deepgram Aura | High-quality cloud voice with any LLM provider |
| **native** | Gemini Live / OpenAI Realtime | same (provider handles audio) | Lowest latency with Gemini or OpenAI |

> **Note:** Native realtime voice requires **Gemini** or **OpenAI** as the LLM provider.

---

## LLM Providers

| Provider | Type | API key needed |
|----------|------|----------------|
| Gemini | Cloud | Yes — [Google AI Studio](https://aistudio.google.com/) |
| OpenAI | Cloud | Yes — [OpenAI Platform](https://platform.openai.com/) |
| Anthropic | Cloud | Yes — [Anthropic Console](https://console.anthropic.com/) |
| Ollama | Local | Base URL only (default `http://localhost:11434`) |
| LM Studio | Local | Base URL only (default `http://localhost:1234`) |

---

## What Emily Can Do

Emily exposes tools the LLM can call during conversation. Core capabilities include:

| Category | Tools |
|----------|-------|
| **Apps & OS** | Open apps, volume/brightness, window management, keyboard shortcuts, screenshots, shutdown/restart |
| **Browser** | Headless web automation (search, click, fill forms, scrape) via Playwright |
| **Files** | List, create, move, copy, delete, search, read, write, organize desktop |
| **Vision** | Screen capture and webcam analysis; local camera object/face detection in the UI |
| **Communication** | Send WhatsApp/Telegram messages, web search, weather, flight search |
| **Media** | YouTube play/summarize/trending |
| **Code** | Write, edit, explain, run, and build code; multi-file project agent |
| **Games** | Steam/Epic install, update, schedule downloads |
| **Scheduling** | Reminders with toast alerts or spoken news/weather/custom LLM briefings |
| **Memory** | Save and recall personal facts across sessions |
| **Agents** | Multi-step `agent_task` for goals that need several tools in sequence |
| **MCP** | Massive financial data, Firecrawl web scraping (when configured in `config/mcp.json`) |

---

## Requirements

- **Python 3.10+**
- A **microphone** (required for voice interaction)
- A **webcam** (optional — used for camera feed, vision tools, and sleep mode)
- **Internet** (required for cloud LLMs, Deepgram voice, web search, and most tools; local-only setups can use Ollama/LM Studio + local voice with limited offline capability)
- **Disk space** — voice models (Whisper, Supertonic) download on first use; Playwright browsers download on first setup (~300 MB+)

### Platform-specific notes

| Platform | Additional notes |
|----------|-----------------|
| **Windows** | Python from [python.org](https://www.python.org/) or Microsoft Store; `Setup.bat` handles everything |
| **Linux** | `portaudio` dev headers for microphone support (`sudo apt install portaudio19-dev` on Debian/Ubuntu) |
| **macOS** | Xcode Command Line Tools; grant microphone and camera permissions when prompted |

---

## Installation

### Windows

Windows installation is a single step:

1. **Clone or download** this repository
2. **Double-click `Setup.bat`**

`Setup.bat` automatically:

- Creates a `.venv` virtual environment (if missing)
- Upgrades `pip` and installs all dependencies from `requirements.txt`
- Configures the correct ONNX Runtime package for GPU-accelerated Supertonic TTS
- Installs Playwright browsers on first run
- Launches the **first-time setup wizard** (`python main.py --setup`)

After setup completes, use **`start.bat`** for normal daily launches (installs any dependency updates, then runs Emily without re-running the wizard).

---

### Linux

#### 1. Clone the repository

```bash
git clone https://github.com/sanobartech/EMILY-voice-first-ai-agent.git
cd Emily
```

#### 2. Create and activate a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### 3. Install system dependencies (Debian/Ubuntu example)

```bash
sudo apt update
sudo apt install -y python3-dev portaudio19-dev
```

#### 4. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 5. Configure ONNX Runtime for local TTS (recommended if using local voice)

```bash
python scripts/ensure_onnxruntime.py
```

This auto-detects your GPU and installs the appropriate ONNX Runtime wheel (`onnxruntime`, `onnxruntime-gpu`, or `onnxruntime-webgpu`).

#### 6. Install Playwright browsers (required for browser automation)

```bash
python -m playwright install
```

#### 7. Run the first-time setup wizard

```bash
python main.py --setup
```

The terminal wizard will walk you through LLM provider, voice pipeline, API keys, microphone, and camera selection.

---

### macOS

#### 1. Clone the repository

```bash
git clone https://github.com/sanobartech/EMILY-voice-first-ai-agent.git
cd Emily
```

#### 2. Create and activate a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### 3. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Configure ONNX Runtime for local TTS (recommended if using local voice)

```bash
python scripts/ensure_onnxruntime.py
```

> On macOS, ONNX Runtime uses the CPU package. GPU acceleration for Supertonic is not available on Apple Silicon in this release.

#### 5. Install Playwright browsers

```bash
python -m playwright install
```

#### 6. Run the first-time setup wizard

```bash
python main.py --setup
```

Grant **Microphone** and **Camera** access when macOS prompts you.

---

## Running Emily

| Platform | First-time setup | Normal launch |
|----------|-----------------|---------------|
| **Windows** | `Setup.bat` | `start.bat` |
| **Linux / macOS** | `python main.py --setup` | `python main.py` |

### Re-run setup

To change LLM provider, voice mode, API keys, or devices at any time:

```bash
python main.py --setup
```

On Windows you can also run:

```bat
.venv\Scripts\python.exe main.py --setup
```

---

## First-Time Setup Wizard

The setup wizard runs in the terminal before the UI opens. You will configure:

1. **Operating system** — Windows, macOS, or Linux (auto-detected)
2. **LLM provider** — Gemini, OpenAI, Anthropic, Ollama, or LM Studio
3. **API key / base URL** — stored in `config/api_keys.json`
4. **Voice pipeline** — local, Deepgram, or native realtime
5. **Model and voice** — chat model, STT model, TTS voice (depends on pipeline)
6. **Microphone and camera** — device indices from detected hardware

Preferences are saved to `config/config.json`. Secrets are saved to `config/api_keys.json`.

> Voice models (Whisper, Supertonic) may download automatically on first use. This can take a few minutes depending on your connection.

---

## Configuration

### `config/config.json` — user preferences

| Key | Description | Example |
|-----|-------------|---------|
| `llm_provider` | AI backend | `"gemini"`, `"openai"`, `"anthropic"`, `"ollama"`, `"lmstudio"` |
| `llm_model` | Chat model name | `"gemini-2.5-flash"` |
| `voice_mode` | Voice pipeline | `"local"`, `"deepgram"`, `"native"` |
| `stt_model` | Whisper or Deepgram STT model | `"base"`, `"nova-3"` |
| `tts_voice` | Supertonic or Deepgram voice | `"F2"`, `"aura-2-asteria-en"` |
| `live_model` | Realtime model (native mode) | `"gemini-3.1-flash-live-preview"` |
| `live_voice` | Realtime voice (native mode) | `"Aoede"` |
| `mic_device_index` | Microphone device index | `1` |
| `camera_index` | Webcam device index | `0` |
| `os_system` | Target OS for tool behavior | `"windows"`, `"mac"`, `"linux"` |
| `sleep_mode_enabled` | Mute mic when no face detected | `true` |
| `sleep_face_timeout_sec` | Seconds before sleep mode activates | `10` |
| `supertonic_accel` | GPU acceleration for local TTS | `"auto"`, `"cpu"`, `"cuda"`, `"webgpu"`, `"directml"` |

### `config/api_keys.json` — secrets (do not commit)

Stores API keys and local server URLs. Example fields: `gemini_api_key`, `openai_api_key`, `anthropic_api_key`, `deepgram_api_key`, `ollama_base_url`, `lmstudio_base_url`.

### `config/mcp.json` — MCP server extensions

Configure optional MCP servers (e.g. Massive financial data, Firecrawl) under `mcpServers`.

### `core/prompt.txt` — personality and behavior

Edit this file to customize Emily's system prompt, tone, and tool-use rules.

---

## GPU Acceleration (Local TTS)

When using **local voice mode**, Emily uses Supertonic 3 for text-to-speech with ONNX Runtime. The correct GPU package is selected automatically:

| GPU | ONNX package | Execution provider |
|-----|-------------|-------------------|
| No dedicated GPU | `onnxruntime` | CPU |
| NVIDIA discrete | `onnxruntime-gpu` | CUDA |
| AMD / Intel Arc / other discrete | `onnxruntime-webgpu` | WebGPU (Vulkan-backed) |
| WebGPU unavailable (Windows) | `onnxruntime-directml` | DirectML |

On Windows, `Setup.bat` and `start.bat` run `scripts/ensure_onnxruntime.py` automatically. On Linux/macOS, run it manually after `pip install` (see installation steps above).

Override detection by setting `"supertonic_accel"` in `config/config.json`.

---

## Cross-Platform Notes

Emily adapts tool behavior based on `os_system` in your config:

| Feature | Windows | macOS | Linux |
|---------|---------|-------|-------|
| App launch | `start`, registry | `open` | `xdg-open` |
| Reminders | Task Scheduler | `launchd` | `systemd` / `cron` |
| Volume control | PyAutoGUI / pycaw | `osascript` | `pactl` |
| Steam games | Registry + `steam.exe` | `.app` paths | `~/.steam` |

Some Windows-only packages (`pycaw`, `pywinauto`, `win10toast`) are listed in `requirements.txt` for cross-platform pip compatibility; they are only used on Windows.

---

## Security

- **API keys** are stored in plaintext `config/api_keys.json` — add this file to `.gitignore` and never commit it
- **File controller** refuses paths outside your home directory roots
- **Browser automation** can attach to real browser profiles — powerful but sensitive
- **Agent code execution** runs generated Python in a sandboxed temp file with a timeout
- **No authentication layer** — Emily is a single-user local assistant; do not expose it to untrusted networks

---

## Architecture

For a deep dive into modules, threading, tool flow, and extension points, see **[Architecture.md](Architecture.md)**.

---

## Project Structure

```
Emily/
├── main.py              # Entry point
├── Setup.bat            # Windows first-time installer + setup wizard
├── start.bat            # Windows daily launcher
├── setup.py             # pip + Playwright install helper
├── requirements.txt     # Python dependencies
├── config/              # User config, API keys, MCP servers
├── core/                # Engine, voice, LLM, onboarding, config
├── actions/             # Tool implementations (browser, files, vision, etc.)
├── agent/               # Multi-step task planner and executor
├── memory/              # Long-term memory persistence
├── vision/              # Local camera detection (OpenCV)
├── ui/                  # PyQt6 interface
└── scripts/             # Utility scripts (ONNX Runtime installer)
```

---

## License

See repository license file for terms. Third-party models and services (Gemini, OpenAI, Deepgram, etc.) are subject to their own terms of use.
