---
name: winwhisperplus-release
description: Rebuild, sign, and verify WinWhisperPlus Windows release packages when a setup or release EXE is requested. Use for this repository's release workflow, not for ordinary source changes.
---

# WinWhisperPlus release

Create a release package from `C:\Users\matth\source\repos\WinWhisperPlus` using `scripts\build-release.ps1`.

## Before building

- When the user asks to build or rebuild a signed setup, first remind them: **Bitte stelle das orgAnice-Code-Signing-Zertifikat mit zugreifbarem privatem Schlüssel im Benutzerzertifikatsspeicher bereit.** Do not begin a signed build until it is available, unless the user explicitly requests an unsigned package.
- Inspect `VERSION`, the requested version, recent commits, and `git status --short`. Preserve unrelated untracked files.
- Confirm required tools are available: a supported 64-bit Python, CMake with the Visual Studio C++ toolchain, `VULKAN_SDK` with `glslc.exe`, and Inno Setup (`ISCC.exe`).
- For a rebuild that must retain its version, always pass it explicitly, for example `-AppVersion 1.2.0`; omitting it increments the patch version.

## Build and recovery

- Run the complete release script, not an ad-hoc PyInstaller or Inno Setup sequence:

  ```powershell
  .\scripts\build-release.ps1 -AppVersion <version>
  ```

- The script rebuilds whisper.cpp with Vulkan, packages the app, signs the application, creates the ZIP and installer, and signs the setup.
- If pytest fails because repository test/cache directories are locked, rerun with a newly created, isolated pytest base directory outside the repository. Remove only that directory after the run; never delete the user's `.tmp` or other pre-existing files.
- If a DLL in `build\whispercpp-runtime` is locked, identify the exact process first. End only an orphaned `whisper-server.exe` from that build runtime when necessary for the requested build; otherwise ask the user to close the process.
- If signing reports a missing provider, storage object, or private key although the certificate is visible, rerun the build in the regular user context. Do not silently produce an unsigned release unless the user explicitly approves it.

## Required verification

After a successful build, verify the actual generated outputs rather than relying on the script exit status:

- `dist\WinWhisperPlus-Setup-<version>.exe` exists and has a fresh timestamp.
- `dist\WinWhisperPlus\_internal\VERSION` matches the requested version.
- `dist\WinWhisperPlus\WinWhisperPlus.exe` has a valid Authenticode signature.
- `dist\WinWhisperPlus-Setup-<version>.exe` has a valid Authenticode signature.
- `whisper-cli.exe` and `whisper-server.exe` exist under `dist\WinWhisperPlus\_internal\whispercpp`.
- Report the setup path, validation results, and SHA-256 hash. Mention separately if the upstream whisper helper executables are intentionally unsigned.

Do not commit generated artifacts or unrelated working-tree changes unless the user explicitly asks.
