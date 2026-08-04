# WinWhisperPlus

Ein Windows-Tool zur lokalen Spracherkennung auf Basis von whisper.cpp.
A Windows speech-recognition tool powered by OpenAI Whisper running entirely locally.

## Features

- 🎤 **Speech-to-Text** – Converts microphone input to text using OpenAI Whisper (local, no cloud).
- 🌍 **Language support** – German (Deutsch), Polish (Polski), English.
- 🗂️ **Localized interface** – UI available in German, Polish, and English independently from dictation language.
- ⌨️ **System-wide hotkeys** – Configurable hotkeys to start/stop recording and cycle languages.
- 📋 **Auto-insert** – Transcribed text is automatically pasted into the currently active input field.
- ⚡ **Live mode** – Optional near real-time transcription inserts stable partial text while you are still speaking.
- 📊 **Usage statistics** – Tracks successful sessions and shows count/total/average recording duration per day, week, and month.
- 🎛️ **Microphone selection** – Choose from all connected input devices.
- 🔔 **System tray** – Runs silently in the background with a tray icon and context menu.
- ⚙️ **Settings GUI** – Configure hotkeys, language, microphone and Whisper model size.

## Default Hotkeys

| Action                     | Default shortcut    |
|----------------------------|---------------------|
| Start / stop recording     | `Ctrl + Alt + H`    |
| Cycle language             | `Alt + Shift + S`   |

Both hotkeys are fully configurable in the settings dialog.

## Requirements

- Windows 10 64-bit or newer
- Python 3.10 to 3.14 for source usage and release builds
- Vulkan-fähige GPU empfohlen (AMD, NVIDIA oder Intel)

## Installation

For development or direct source usage:

```bash
pip install -r requirements.txt
```

> Für die GPU-Beschleunigung im Release baut das Build-Skript whisper.cpp mit
> Vulkan. Dazu werden Visual Studio C++ Build Tools, CMake und das Vulkan SDK benötigt.

## Windows Release Package

End users do **not** need to install Python when you distribute the PyInstaller
release package. They only need to unzip the package and start
`WinWhisperPlus.exe`.

Build the release package on a Windows development machine with Python 3.10 to
3.14 64-bit and Inno Setup 7 or 6 installed:

```powershell
.\scripts\build-release.ps1
```

Each build automatically increments the patch version stored in `VERSION`
unless `-AppVersion` is specified explicitly.

By default, the build script signs `WinWhisperPlus.exe` with PowerShell
Authenticode signing and the configured certificate thumbprint before creating
the ZIP package and installer.

For local unsigned test builds:

```powershell
.\scripts\build-release.ps1 -SkipSigning
```

To build only the PyInstaller folder and ZIP without an installer:

```powershell
.\scripts\build-release.ps1 -SkipInstaller
```

The script creates:

```text
dist\WinWhisperPlus\WinWhisperPlus.exe
dist\WinWhisperPlus.zip
dist\WinWhisperPlus-Setup-1.0.0.exe
```

Distribute `dist\WinWhisperPlus-Setup-1.0.0.exe` to the user, or use
`dist\WinWhisperPlus.zip` for a portable-style package. On first use, Whisper
may need internet access to download the selected model into the normal local
Whisper cache. Settings and statistics are still stored below
`%APPDATA%\WinWhisperPlus`.

## Usage

```bash
python main.py
```

The application starts minimised to the system tray.  
Double-click the tray icon or use the hotkey to start/stop recording.

For end-user instructions with screenshots, see the German
[Benutzerhandbuch](docs/benutzerhandbuch.md).

## Configuration

Click **Einstellungen…** in the tray menu to open the settings dialog where you can:

- Change hotkeys by clicking the field and pressing the desired key combination.
- Select the default language (Deutsch / Polski / English).
- Select the interface language (Deutsch / Polski / English).
- Choose a specific microphone from the dropdown.
- Choose automatic Vulkan processing, a detected Vulkan GPU, or CPU-only processing.
- Optionally keep active Whisper models loaded in memory for faster subsequent transcriptions.
- Select the Whisper model size (`tiny` → `large`; larger = more accurate but slower).
- Enable live transcription if you want stable partial text to be inserted during an active recording.

## Live Transcription

The optional live mode keeps the current push-to-talk workflow, but starts transcribing overlapping audio chunks during the recording.

- Stable partial text is inserted while the recording is still running.
- When you stop recording, the final full transcription replaces the live partial text block.
- Spoken `enter` is only executed on the final result so partial hypotheses do not trigger unwanted line breaks.
- For the best latency, `tiny` or `base` are recommended in live mode.

Settings are saved to `%APPDATA%\WinWhisperPlus\settings.json`.
Statistics are saved to `%APPDATA%\WinWhisperPlus\statistics.json`.

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

## Architecture

```
WinWhisperPlus/
├── main.py                  # Entry point
├── app.py                   # Application orchestrator
├── config/
│   └── settings.py          # Settings persistence (JSON)
├── core/
│   ├── recorder.py          # Microphone capture (sounddevice)
│   ├── transcriber.py       # Whisper inference wrapper
│   ├── text_inserter.py     # Clipboard-based text paste
│   └── hotkey_manager.py    # System-wide hotkeys (keyboard lib)
├── gui/
│   ├── tray_icon.py         # System tray icon & menu (PyQt6)
│   ├── status_window.py     # Floating status indicator
│   └── settings_window.py   # Settings dialog
└── tests/
    ├── test_settings.py
    ├── test_recorder.py
    ├── test_transcriber.py
    └── test_hotkey_manager.py
```
