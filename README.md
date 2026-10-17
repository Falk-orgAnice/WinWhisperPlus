# WinWhisperPlus

Ein Windows-Tool zur lokalen Spracherkennung auf Basis von whisper.cpp.
A Windows speech-recognition tool powered by OpenAI Whisper running entirely locally.

## Features

Whisper inference is provided by a bundled `whisper.cpp` runtime using Vulkan.
The same release supports AMD, NVIDIA, and Intel GPUs, plus CPU-only inference.

- ðŸŽ¤ **Speech-to-Text** â€“ Converts microphone input to text using OpenAI Whisper (local, no cloud).
- ðŸŒ **Language support** â€“ German (Deutsch), Polish (Polski), English, French (FranÃ§ais), Dutch (Nederlands).
- ðŸ—‚ï¸ **Localized interface** â€“ UI available in German, Polish, and English independently from dictation language.
- âŒ¨ï¸ **System-wide hotkeys** â€“ Configurable hotkeys to start/stop recording and cycle languages.
- ðŸ“‹ **Auto-insert** â€“ Transcribed text is automatically pasted into the currently active input field.
- âš¡ **Live mode** â€“ Optional near real-time transcription inserts stable partial text while you are still speaking.
- âœ¨ **Local text optimization** â€“ Optionally structures final dictation locally with Qwen3: paragraphs, punctuation, lists, and configurable conservative cleanup.
- ðŸ“Š **Usage statistics** â€“ Tracks successful sessions and shows count/total/average recording duration per day, week, and month.
- ðŸŽ›ï¸ **Microphone selection** â€“ Choose from all connected input devices.
- ðŸ”” **System tray** â€“ Runs silently in the background with a tray icon and context menu.
- âš™ï¸ **Settings GUI** â€“ Configure hotkeys, language, microphone and Whisper model size.

## Default Hotkeys

| Action                     | Default shortcut    |
|----------------------------|---------------------|
| Start / stop recording     | `Ctrl + Alt + H`    |
| Cycle language             | `Alt + Shift + S`   |

Both hotkeys are fully configurable in the settings dialog.

## Requirements

- Windows 10 64-bit or newer
- Tested with Python 3.14.6 for source usage and release builds
- A current graphics driver with Vulkan support for GPU acceleration
- A physical microphone selected in Windows and in WinWhisperPlus; avoid inactive virtual streaming inputs

CPU-only transcription is supported when no Vulkan GPU is available. PyTorch,
ROCm, CUDA, and the Python package `openai-whisper` are not required.

## Installation

For development or direct source usage:

```bash
pip install -r requirements.txt
```

> FÃ¼r die GPU-Beschleunigung im Release baut das Build-Skript whisper.cpp mit
> Vulkan. Dazu werden Visual Studio C++ Build Tools, CMake und das Vulkan SDK benÃ¶tigt.

For a full installer build, Inno Setup 6 or 7 is also required. End users do
not need Python, the Vulkan SDK, or any other build tools.

## Windows Release Package

### Build in Visual Studio 2026 (x64)

Open `WinWhisperPlus.sln`, select **Debug | x64** or **Release | x64**, then
choose **Build Solution** (`Ctrl+Shift+B`). These are the only configurations.
The solution uses a Makefile project to invoke the Python/PyInstaller build;
install the **Desktop development with C++** workload (MSVC v145 and CMake),
Python 3.10â€“3.14 **64-bit** with the `py` launcher, and the Vulkan SDK.
No Python project workload, signing certificate, or Inno Setup is required.
This follows Microsoft's [Makefile project integration](https://learn.microsoft.com/en-us/cpp/build/reference/creating-a-makefile-project?view=msvc-180).

The ready-to-run application and all its dependencies are written to:

```text
Bin\Debug\WinWhisperPlus.exe
Bin\Debug\_internal\...
Bin\Release\WinWhisperPlus.exe
Bin\Release\_internal\...
```

Debug includes a console and PyInstaller bootloader diagnostics; Release is a
windowed application without a console. Both contain the complete local runtimes,
FFmpeg and bundled Qwen model. Keep each entire configuration directory together.
The Visual Studio run command launches the selected executable; Python source
debugging still requires a Python debugger rather than the native EXE debugger.

The first build installs dependencies, builds missing x64 runtimes and downloads
the bundled text model (several GB). Later builds reuse these caches. Build and
Rebuild keep `VERSION` unchanged and create no installer or signed release.
Clean/Rebuild affect only the selected configuration; the other configuration,
`.venv-build`, and shared runtime/model caches remain intact.

From a Visual Studio Developer PowerShell, the equivalent commands are:

```powershell
msbuild .\WinWhisperPlus.sln /t:Build /p:Configuration=Debug /p:Platform=x64
msbuild .\WinWhisperPlus.sln /t:Build /p:Configuration=Release /p:Platform=x64
# Or without opening Visual Studio:
.\scripts\build-solution.ps1 -Configuration Debug -Action Build
.\scripts\build-solution.ps1 -Configuration Release -Action Rebuild
.\scripts\build-solution.ps1 -Configuration Debug -Action Clean
```

### Signed distribution and installer

End users do **not** need to install Python when you distribute the PyInstaller
release package. They only need to unzip the package and start
`WinWhisperPlus.exe`.

The release also contains the optional Qwen3-4B text model (several GB) and a
local `llama.cpp` runtime. It is checked by SHA-256 before use and is contacted
only through `127.0.0.1`; recognition text is never sent to a cloud service.

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
dist\WinWhisperPlus-Setup-<version>.exe
```

Distribute `dist\WinWhisperPlus-Setup-<version>.exe` to the user, or use
`dist\WinWhisperPlus.zip` for a portable-style package. On first use, Whisper
may need internet access to download the selected model into the normal local
Whisper cache. Settings and statistics are still stored below
`%APPDATA%\WinWhisperPlus`.

## Usage

WinWhisperPlus 1.2.5 runs once per Windows user, including across Debug/Release
builds and different installation folders. A second interactive start shows
â€œWinWhisperPlus lÃ¤uft bereitsâ€ and exits before loading configuration, models,
or hotkeys. An already-running older `WinWhisperPlus.exe` is detected too.
The Windows mutex is automatically released if the process exits or crashes.
Resource-only `--smoke-test` runs are exempt because they do not start an
interactive session. The guard uses a user-specific named mutex following the
[Windows named-object lifecycle](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw).

```bash
python main.py
```

The application starts minimised to the system tray.  
Double-click the tray icon or use the hotkey to start/stop recording.

For end-user instructions with screenshots, see the German
[Benutzerhandbuch](docs/benutzerhandbuch.md).

## Configuration

Click **Einstellungenâ€¦** in the tray menu to open the settings dialog where you can:

The shown application version in this dialog is read from the bundled `VERSION`
file. Release builds and the Inno Setup package use the same version value.

- Change hotkeys by clicking the field and pressing the desired key combination.
- Select the default language (Deutsch / Polski / English / FranÃ§ais / Nederlands).
- Select the interface language (Deutsch / Polski / English).
- Choose a specific microphone from the dropdown.
- Choose automatic Vulkan processing, a detected Vulkan GPU, or CPU-only processing.
- Optionally keep active Whisper models loaded in memory for faster subsequent transcriptions.
- Select the Whisper model size (`tiny` â†’ `large`; larger = more accurate but slower).
- Enable live transcription if you want stable partial text to be inserted during an active recording.
- Enable **local text optimization** and combine its independent options: improve punctuation/paragraphs, remove clear repetitions and fillers, and cautiously redact for readability. Optionally translate the final result into German, Polish, English, French, or Dutch. The model runs only after final transcription, so live text remains responsive.

The processing choice is used for live and final transcription. When several
Vulkan GPUs are available, each one is listed separately. Keeping models loaded
reduces latency, but keeps RAM or GPU memory in use while the application runs.

### Local text optimization

Text optimization is disabled by default. When enabled, the bundled local
Qwen3-4B Q4_K_M model receives only the final recognized text and returns plain
text with paragraphs and `-` lists; HTML and Markdown formatting are rejected.
Formatting, cleanup, redaction, and translation target can be combined in the
settings. Translation is available between the five dictation languages and
does not run when the target is the current dictation language. The model must
preserve names, numbers, facts, commands, and ambiguous fragments.
Long text is split at sentence/paragraph boundaries using the actual model
tokenizer and a reserved output budget. Truncated responses are retried in smaller
sections. Failed translations are labelled explicitly; source text remains
available separately and is never inserted as a successful translation.

### Corrections, audio import and session recordings (1.2.0)

- **Settings â†’ Correction rules:** add literal whole-word/phrase replacements,
  e.g. `Organize â†’ orgAnice`. Matching ignores case; the longest match wins and
  replacements do not cascade. Empty replacements delete a matched word. Rules
  persist atomically in a separate profile-level JSON file. Protected names survive text processing.
- **Open audio file:** import WAV, MP3, M4A or FLAC through local FFmpeg. Choose a
  source language (including auto detection), speech model and optional translation.
  File imports never paste automatically or interpret spoken keyboard commands.
- **History:** recordings include audio and versioned original/result text. Play,
  export, re-recognize with another model, retry failed sections, copy or explicitly
  insert a result. Audio exists only for this session; export it before quitting.
- **Long recordings:** audio is recorded to disk, processed in <=30-second windows
  with a one-second overlap, pause-aware boundaries and Silero VAD. Successful
  sections survive retries. The final partial window is always processed.
- **Settings â†’ Models:** check the versioned catalogue, download verified models,
  and choose speech/text models independently. `large` still means `large-v3`.
  Turbo and Qwen alternatives are candidates, not automatic quality upgrades.

Models are stored under `%LOCALAPPDATA%\\WinWhisperPlus\\models`; temporary audio is
under `%LOCALAPPDATA%\\WinWhisperPlus\\sessions`. Orphaned sessions are cleaned only
when their owner process is no longer running. Exported files are untouched.

Maintainers can run `scripts/refresh-model-catalog.py` to pin upstream revisions
and checksums. Review and test candidates before publishing the generated
`dist/model-catalog.json` as a GitHub release attachment. Until that attachment is
published, update checks display an explicit notice that the online catalogue is
not yet available; the bundled catalogue works offline. Version 1.2.1 downloads
optional text models only when text processing or translation is requested, after
speech recognition, and displays download/verification progress in the status
window and history. Selecting a text model does not delay ordinary dictation.
Runtime updates ship with program releases (whisper.cpp 1.9.4 / llama.cpp v0.6.0).

### Microphone troubleshooting

If recognition returns unrelated text, first verify that the selected microphone
shows an input level in Windows. Virtual streaming microphones can be silent
even when selected as the Windows default. Bluetooth hands-free microphones may
use an 8 kHz native rate; WinWhisperPlus resamples such inputs to Whisper's
required 16 kHz automatically. Very quiet recordings are discarded to avoid
hallucinated text.

## Live Transcription

The optional live mode keeps the current push-to-talk workflow, but starts transcribing overlapping audio chunks during the recording.

- Stable partial text is inserted while the recording is still running.
- When you stop recording, the final full transcription replaces the live partial text block.
- Spoken `enter` is only executed on the final result so partial hypotheses do not trigger unwanted line breaks.
- For the best latency, `tiny` or `base` are recommended in live mode.

Settings are saved to `%APPDATA%\WinWhisperPlus\settings.json`.

Correction rules are stored separately in
`%APPDATA%\WinWhisperPlus\correction-rules.json`, shared by all installations
and Debug/Release builds for the current user. Existing embedded rules migrate
automatically; an existing rule file takes precedence. In **Settings â†’ Correction
rules**, edit the displayed path or use **â€¦** to select a file. The compact folder
button reveals it in Explorer. Relative paths resolve against the configuration
directory, never the working directory. Selecting an existing file loads its
rules; a new path copies the current rules when saving and preserves the old file.
Cancel creates no file and does not change the active path.

The file is indented UTF-8 JSON and can be edited in any text editor:

```json
{
  "schema_version": 1,
  "rules": [
    {"enabled": true, "source": "Organize", "target": "orgAnice"}
  ]
}
```

Save external edits before starting the next dictation or recognition job.
Rules are captured at recording/job start; running jobs and retries retain their
original rules. The settings dialog also offers **Reload** and detects external
edits before overwriting. Invalid files produce an explicit warning and retain
the last valid rules. With corrections enabled and no valid rules available,
new jobs are blocked until the file is repaired or corrections are disabled.
Window-position saves never overwrite the rule file. Older WinWhisperPlus
versions continue to use their embedded rules and do not share this new file.
Statistics are saved to `%APPDATA%\WinWhisperPlus\statistics.json`.

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

## Architecture

```
WinWhisperPlus/
â”œâ”€â”€ main.py                  # Entry point
â”œâ”€â”€ app.py                   # Application orchestrator
â”œâ”€â”€ config/
â”‚   â””â”€â”€ settings.py          # Settings persistence (JSON)
â”œâ”€â”€ core/
â”‚   â”œâ”€â”€ recorder.py          # Microphone capture (sounddevice)
â”‚   â”œâ”€â”€ transcriber.py       # Whisper inference wrapper
â”‚   â”œâ”€â”€ text_inserter.py     # Clipboard-based text paste
â”‚   â””â”€â”€ hotkey_manager.py    # System-wide hotkeys (keyboard lib)
â”œâ”€â”€ gui/
â”‚   â”œâ”€â”€ tray_icon.py         # System tray icon & menu (PyQt6)
â”‚   â”œâ”€â”€ status_window.py     # Floating status indicator
â”‚   â””â”€â”€ settings_window.py   # Settings dialog
â””â”€â”€ tests/
    â”œâ”€â”€ test_settings.py
    â”œâ”€â”€ test_recorder.py
    â”œâ”€â”€ test_transcriber.py
    â””â”€â”€ test_hotkey_manager.py
```
