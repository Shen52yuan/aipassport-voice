# AI Passport · Voice Organizer

[简体中文](README.md) | [English](README.en.md)

> **A personalized fork of [FoloToy AI Passport](https://github.com/zhaohuaxiaoy/folo-ai-passport-voice) (MIT).**
> The underlying framework (ESP32-C3 firmware state machine, LVGL UI, BLE/USB dual-channel transport, physical-approval mechanism) is inherited from that project; this repository layers scene-aware, local-first customization on top.

**AI Passport** is a small system of an ESP32-C3 wearable voice device + a desktop companion (macOS/Windows). The problem it solves is **not "speech-to-text" but "turning fragmented speech into work-ready messages you can send directly"**:

Hold the device to talk → **local whisper.cpp** transcription (audio never leaves the machine) → **DeepSeek** polishes the speech into a coherent / structured draft based on the **work scene** you picked → auto-injected into the current input box (WeChat / docs / any caret), or pushed back to your phone.

In one sentence: take the scattered thoughts in your head and, with the least effort, turn them into something you can actually send.

```text
Hold VOL+ to talk ──► device records ──► desktop relay ──► local whisper.cpp (audio stays on-device)
                         │  over BLE / USB
                         ▼  live partials
              Device screen previews candidates
                         │
                         ▼  final → DeepSeek polishes by scene
              Coherent / structured draft ──► inject into focused input box (once) / push to phone
```

> The repository contains both the **firmware** (ESP-IDF, device side) and the **desktop companion** (`companion/`, macOS/Windows relay), which work together over two channels: BLE / USB.

## Four work scenes

After HOME → READY you can pick a scene first; each scene maps to a different DeepSeek polishing preset — the same spoken sentence yields a completely different "draft shape":

| Scene | Device label | Polishing goal (DeepSeek preset) | Typical use |
| --- | --- | --- | --- |
| **① Colleagues** | `同事` | Strip filler, fix subjects, concise work message (`work_wechat`) | Work-group / colleague messages |
| **② Boss / Client** | `领导客户` | Conclusion-first, formal written, quantifiable (`report_boss`) | Reporting up / client comms |
| **③ To AI** | `对AI` | Spoken idea → directly executable AI task instruction (`agent_prompt`) | Briefing a coding / work agent |
| **④ Voice Input** | `语音输入` | Speech → smooth written text, keep all info points (`voice_input`) | Quick notes / long dictation / writing drafts |

## Differences from upstream FoloToy AI Passport

| Dimension | Upstream FoloToy AI Passport | This fork (AI Passport Voice Organizer) |
| --- | --- | --- |
| **Positioning** | Generic voice input + AI agent control surface | Scene-aware "speech → sendable work info" organizer |
| **ASR** | Volcano Engine cloud streaming ASR (key required, audio leaves device) | **Local whisper.cpp** (zero cloud cost, audio stays on-device) |
| **Intelligence layer** | Agent thinking / execution / approval visualization | **DeepSeek polishes speech by scene** into a draft |
| **Capture** | Single hold-to-talk utterance | **1–3 segmented capture + merge**, continuous fast capture (v0.2.4) |
| **Draft shape** | Verbatim transcript | Message / report / instruction / clean text per scene |
| **Delivery** | Inject into desktop input box | Desktop injection + WeCom push-back (planned) |
| **Shared base** | Dual-channel / state machine / physical approval / LVGL | Inherited and extended |

## Architecture

| Layer | Component | Responsibility |
| --- | --- | --- |
| Device | ESP32-C3 firmware (ESP-IDF 5.5 + LVGL 9.5) | State machine, buttons/recording, scene select, UI rendering, dual-channel transport, power management |
| Desktop | companion (macOS / Windows) | Dual-channel access, local whisper.cpp ASR, DeepSeek polish layer, floating window, clipboard injection, wizard, tray |
| Local models | whisper.cpp (ASR) + DeepSeek V4-Flash (polish) | Audio → text (on-device); speech → scene-shaped draft (cloud LLM, text only, no private audio) |

Data flow: the device captures 16 kHz audio → streams 100 ms frames up over **BLE / USB** (any channel) → the desktop relay feeds them into **local whisper.cpp** for transcription → the final text goes to the **DeepSeek polish layer**, which reshapes it per the active scene preset → the draft echoes on the device screen and is injected into the current input box (or pushed to phone). Agent status, approval requests and button verdicts travel the reverse channel.

## Highlights

- **Local-first, privacy-aware**: ASR runs on local whisper.cpp by default — audio never leaves the machine, zero cloud cost; only the "polish" step calls DeepSeek's text API (it sends already-transcribed Chinese text, not raw audio).
- **Scene-aware polishing**: the same spoken sentence is reshaped into a message, a report, an AI instruction, or clean text depending on the selected scene — not a one-size-fits-all transcript.
- **Segmented capture + merge**: one idea can be recorded in up to 3 segments; each segment's final text previews instantly on the device, and once all segments are done DeepSeek de-duplicates across segments, reorders the logic and merges them into one coherent draft — OK confirms and injects.
- **Continuous fast capture (v0.2.4)**: in the "Voice Input" scene, releasing returns immediately to READY so you can record the next sentence without waiting for the previous one to finish polishing — great for a burst of ideas.
- **Dual-channel redundant transport**: one audio/event protocol runs over two physical channels — BLE (direct to Mac, GATT service `0xA2B0`) and USB-Serial-JTAG (wired debugging + full console command surface). Any channel failure converges the session back to READY and keeps approvals pending for reconnect — a broken link never bricks the device.
- **State-machine driven + snapshot rendering**: the core state machine is a pure-C reducer (`state + event → action`) with zero ESP-IDF dependencies; host tests run directly on a PC. UI rendering is driven by snapshot diffs, fully decoupling logic from hardware — testable and portable.
- **Low-resource streaming audio pipeline**: on an ESP32-C3 with only **400 KB SRAM**, audio streams up in 3200-byte/100 ms frames — static ring buffers (no dynamic allocation), source-side frame dropping (never buffers a full utterance), drop reconciliation against silent loss; long sentences never stall.
- **Physical security approval** (inherited from the upstream base): agent permission requests are not push notifications — they are an approval page on the device screen. **OK approve / UP reject** — a real physical press counts; the approval state never sleeps.
- **Two-level power management**: 20 s idle → backlight off (rendering skipped, panel frozen on the last frame); 60 s idle → panel SLPIN sleep at μA level; any key wakes instantly with zero repaint (ST7789 DRAM survives sleep).

## Features

### Device firmware

- **Push-to-talk**: hold **VOL+** in READY to record (start beep), release to send — sub-500 ms slips are dropped on the spot
- **Scene select**: after HOME → READY, move the cursor among `同事 / 领导客户 / 对AI / 语音输入` with UP/DOWN, confirm with OK; the scene label shows on the READY top bar
- **Segmented capture (scenes ①–③)**: up to 3 segments; each final previews instantly on the SEG_WAIT page (shows "segment N"); OK ends capture → MERGE_REVIEW shows the DeepSeek merged draft → OK injects / discard
- **Continuous fast capture (④ Voice Input)**: release returns immediately to READY, record the next sentence at once; drafts accumulate on the desktop in recording order
- **Back navigation**: from scene-select / segment-wait pages you can step back to the previous menu
- **True lock**: when locked, no key lights the screen or renders (power saving); only OK long-press unlocks
- **Exit transcribing**: click VOL+ in TRANSCRIBING to exit back to READY immediately; late recognition results are not shown
- **Agent workflow visualization**: THINKING / RUNNING / DONE states, task echo, offline banner — see what the AI is doing
- **Physical approval**: agent approval requests show on-device — OK approve / UP reject / DOWN view diff
- **Three-button interaction**: VOL+ hold-to-talk, VOL+ click exits transcribing, DOWN = Enter, OK long-press clears the input box (global)
- **Full state machine**: HOME → READY → LISTENING → TRANSCRIBING → SCENE_SELECT → SEG_WAIT → MERGE_REVIEW → AGENT_RUNNING → APPROVAL → DONE
- **Tones**: start / send / approval / success / reject / error
- **Dual-channel transport**: BLE / USB-Serial-JTAG (full console command surface)
- **Low-memory audio pipeline**: 3200-byte/100 ms frames, static ring buffers, source-side frame dropping, drop reconciliation
- **Two-level screen-off**: 20 s idle → backlight off; 60 s idle → panel SLPIN power-off; any key wakes; approval state stays on
- **Console commands**: `st` (heap/stack watermarks, link state, drop stats), `log [offset]`, `rst`, `time`, `bt scan/dtx`, `reboot`, `factory`

### Desktop companion (macOS + Windows)

- **Local whisper.cpp ASR** (core change): replaces the upstream Volcano cloud ASR; transcription runs on-device, **zero cloud cost, audio never leaves the machine**; interface aligns with upstream `asr_client.StreamingASR`, so relay can switch back to the cloud backend in one line
- **DeepSeek polish layer**: `refine_deepseek.py` reshapes the final transcript per the scene preset, between transcription and injection; on network/key failure it falls back to injecting the raw text — "worst case still works"
- **Candidate floating window**: partial ASR results — full accumulated text — appear live in a borderless always-on-top window anchored at the bottom center; auto-wraps and grows upward; on release the polished draft is injected once and the window disappears
- **Never steals focus**: Windows `WS_EX_NOACTIVATE` + `SWP_NOACTIVATE`, macOS hot path avoids WindowServer syncs (no beachball while talking)
- **High-frequency frame merging**: 120 ms merge window keeps only the latest frame, first frame renders immediately
- **5-step wizard**: welcome → auto-discover device (BLE → USB) → local model / polish config → system permission guide (macOS) → status page
- **System tray**: stays in the menu bar / tray after connecting — status rows, diagnostics, settings
- **Diagnostics page**: full device console command surface over USB; read-only runtime state over BLE
- **Injection**: macOS clipboard + Cmd+V (requires Accessibility permission; CJK goes through the clipboard channel); standalone Windows injector

## Controls

| Button | Context | Action |
| --- | --- | --- |
| **VOL+ hold** | READY | Start recording (PTT, start beep), release to send |
| **VOL+ click** | TRANSCRIBING | Exit the transcribing scene, back to READY (late results dropped) |
| **UP / DOWN click** | SCENE_SELECT | Move cursor among the four scenes |
| **OK click** | SCENE_SELECT | Confirm current scene, enter READY |
| **OK click** | SEG_WAIT | End segmented capture, trigger merge (→ MERGE_REVIEW) |
| **OK click** | MERGE_REVIEW | Confirm and inject the merged draft / discard (per prompt) |
| **DOWN long-press** | anywhere | Clear all text in the input box (0.5 s, confirmation beep at threshold) |
| DOWN click | HOME / READY | Press Enter in the input box (submit) |
| OK click | HOME | Enter READY (workflow ready) |
| OK long-press | anywhere | Lock / unlock screen (locked = power-saving off-screen; keys still execute but do not wake the display) |
| OK click | APPROVAL | Approve the agent request |
| UP click | APPROVAL | Reject the agent request |
| DOWN click | APPROVAL | View diff details |

> Long-press thresholds: all three keys use 500 ms — DOWN long-press clears, OK long-press locks/unlocks. VOL+ starts recording on **press** (no threshold wait); the threshold on VOL+ only decides whether a trailing single-click is reported afterwards.

## Quick start

### Desktop companion (Mac / Windows)

**System requirements**:

| Platform | OS version | Architecture | Notes |
| --- | --- | --- | --- |
| macOS | 11.0 (Big Sur) or newer | **Apple Silicon (arm64)** | No official Intel build yet (Pillow lacks a universal binary; build yourself in an x86 env) |
| Windows | 10 1803+ (21H2 recommended) / 11 | x64 | Requires bleak winrt backend; allow through the firewall on first run |

**Configure local models and the polish backend**:

ASR defaults to **local whisper.cpp** (prepare a whisper.cpp model on the machine, e.g. `large-v3-turbo`); polishing defaults to DeepSeek V4-Flash:

1. Prepare the local whisper model (see `companion/install_whisper_local.sh` and the `asr_local_whisper.py` docstring)
2. Put your DeepSeek key (`deepseek_api_key`, or export `DEEPSEEK_API_KEY`) and `refine_preset` (default `work_wechat`) into `companion/config.local.json`
3. First run writes `companion/config.local.json` (**never committed**)

> **Optional cloud backend**: the upstream Volcano cloud ASR can still be enabled by swapping `from asr_local_whisper import ...` back to `from asr_client import StreamingASR` — handy for machines without local compute.

> **Security**: the key lives only in `companion/config.local.json` (gitignored) or the wizard's local config — **never commit it**. If leaked, revoke and recreate it from the console.

**Run from source (development)**:

```bash
pip install -r companion/requirements.txt
cp companion/config.example.json companion/config.local.json   # fill in the DeepSeek key and polish preset
companion/.venv/bin/python companion/fre_app.py                 # wizard GUI (--dry-run walks the flow with a fake link)
companion/.venv/bin/python companion/relay.py                   # CLI relay (auto-scans "AI Passport" over BLE)
```

On macOS, grant **Accessibility** permission (required for clipboard + Cmd+V injection) and Bluetooth permission on first use. Windows instructions: [`companion/WINDOWS.md`](companion/WINDOWS.md).

### Firmware (ESP32-C3)

Requires ESP-IDF 5.5.x (known environment: 5.5.3):

```bash
source "$HOME/esp/esp-idf-v5.5.3/export.sh"   # or your installation path
idf.py set-target esp32c3
idf.py build
idf.py flash monitor
```

The first build pulls LVGL, `esp_lvgl_port`, `button`, `esp_codec_dev` and other dependencies via the ESP-IDF Component Manager. The console runs over USB-Serial-JTAG (GPIO18/19; the default UART0 TX on GPIO21 conflicts with this board's backlight).

## Repository layout

```text
main/                    ESP32-C3 firmware: state machine, UI, dual-channel transport, audio streaming, console commands
components/bsp/          Board drivers: display / buttons / audio / battery / shared I2C (bsp_pins.h is the single source of truth)
companion/               Desktop side: relay (local whisper ASR + DeepSeek polish + injection), floating window, wizard, tray, dual-channel transport
tests/                   Hardware-free firmware logic tests (pure C, ctest)
docs/                    Hardware development guide and acceptance docs
sdkconfig.defaults       ESP32-C3, USB console, Flash, LVGL defaults
partitions.csv           Custom partition table (factory 4 MB)
```

## How it works

1. Hold VOL+ in READY → start beep → `voice.start` → 3200-byte/100 ms audio frames stream up over BLE (GATT NOTIFY) / USB
2. The desktop relay feeds frames into **local whisper.cpp** (every result packet carries the **full accumulated text**)
3. Partial results → device screen previews live; release → `voice.end` → ASR final
4. The final text goes to the **DeepSeek polish layer**, reshaped per the active scene preset (`work_wechat` / `report_boss` / `agent_prompt` / `voice_input`)
5. Scenes ①–③: each segment previews during segmented capture; once all are done DeepSeek **merges across segments** into one coherent draft, MERGE_REVIEW OK confirms and injects; scene ④: each final is polished immediately, continuous fast capture supported
6. The draft is injected into the focused input box (clipboard + Cmd+V) → window closes; it also echoes back on the device screen

The injection target is whatever window the user is focused on — the floating window never steals focus. When the polish service is unavailable it falls back to injecting the raw text.

## Design decisions

- **Why local ASR**: privacy and cost are hard constraints — voice is highly sensitive data; local whisper.cpp keeps audio on-device with zero usage-based cost. Only the "polish" step sends already-transcribed Chinese text to DeepSeek (and polish failure falls back to raw text).
- **Why scene-aware polishing**: users don't want "what I said" but "what this should look like when sent". Colleague messages should be concise, boss updates conclusion-first, AI briefs executable, quick notes clean text — presets encode the intent so you never write the prompt by hand.
- **Why segmented capture + merge**: ideas are often fragmented, jumping and spread across multiple utterances; per-segment preview + cross-segment de-dup merge gives tighter control and a more coherent draft than one long recording.
- **Why two channels**: BLE covers Macs with Bluetooth; USB is both the debugger and the last-resort wired link — any single link can fail and the other keeps working.
- **Why a pure-C reducer state machine**: the `state + event → action` pattern keeps all transition logic **hardware-free**; host-side tests cover state transitions, protocol codec, audio framing and UI pixel math. UI renders from snapshot diffs — adding a page adds no state coupling.
- **Why a static ring-buffer audio pipeline**: the ESP32-C3 has only 400 KB SRAM — dynamic allocation plus buffering a full utterance would blow the heap. 3200-byte/100 ms frames, source-side frame dropping and drop reconciliation are what let an entry-level MCU act as an AI input device.
- **Why physical approval**: AI auto-modifying files or running commands is risky — approvals don't live in a notification banner, they live on the device screen. A real button press counts, and the approval state never sleeps.

## Development

Firmware logic tests (hardware-free, cmake + ctest):

```bash
cd tests && cmake -B build && cmake --build build && ctest --test-dir build
```

Desktop unit tests (pytest):

```bash
companion/.venv/bin/python -m pytest companion/tests/ -q -o asyncio_mode=auto
```

- State machine, protocol, audio framing and UI pixel math all have host-side test coverage; a passing build is not hardware validation
- Keep hardware logic in `components/bsp` and application logic in `main`; separate testable pure logic from ESP-IDF/LVGL
- LVGL is not thread-safe; button callbacks only dispatch lightweight events; slow operations belong in worker tasks

### On-device acceptance status

The full checklist for when hardware arrives is in [`docs/ON_DEVICE.md`](docs/ON_DEVICE.md). Current status: **Build PASS, host tests PASS, device continuous-test PASS**. Verified on real hardware: four-scene switching, 1–3 segmented capture and merge, continuous fast capture, repeated PTT sessions, no dropped keys under rapid presses, click-to-exit transcribing, dual-channel transport, sleep/wake, true lock. Still to verify: Windows focus behavior, no dropped words over ~15 s of continuous speech, USB unplug recovery, battery readings, WeCom push-back.

## Roadmap / planned

- **WeCom push-back**: push polished drafts to the phone via WeCom (avoids personal-WeChat ban risk) — desktop injection is done, phone delivery is the next step.
- **Multi-segment orchestration**: per-segment preview + confirm-then-merge for longer continuous dictation.
- **Pixel-art UI**: index-color sprites (≤128×128) for objects/characters on the 240×320 screen, low footprint (~50–200 KB Flash, near-zero RAM).

## Credits / upstream

This project is a derivative of [zhaohuaxiaoy/folo-ai-passport-voice](https://github.com/zhaohuaxiaoy/folo-ai-passport-voice) (FoloToy AI Passport, MIT): the firmware's state machine, LVGL UI, BLE/USB dual-channel transport and physical-approval mechanism are inherited from that project; this repository adds the local whisper.cpp ASR, the scene-aware DeepSeek polish layer, the four scenes and segmented / continuous capture as personalized capabilities.

## License

MIT © 2026 AI Passport, see [LICENSE](LICENSE).

Third-party components (LVGL, esp_lvgl_port, NimBLE, cJSON, whisper.cpp, OpenAI-compatible SDK, etc.) are copyright their respective authors.
