"""Launch the frozen executable with isolated data and bounded lifetime."""
from pathlib import Path
import os
import subprocess
import argparse

root = Path(__file__).resolve().parents[1]
profile = root / "build/bundle-smoke-profile"
environment = dict(os.environ, APPDATA=str(profile), LOCALAPPDATA=str(profile), QT_QPA_PLATFORM="offscreen")
parser = argparse.ArgumentParser()
parser.add_argument("--package", default="build/feature-package")
args = parser.parse_args()
package = root / args.package
executable = package / "WinWhisperPlus.exe"
if not executable.is_file():
    executable = package / "WinWhisperPlus/WinWhisperPlus.exe"
report = profile / "WinWhisperPlus/bundle-smoke.txt"
report.unlink(missing_ok=True)
completed = subprocess.run([str(executable), "--smoke-test"], env=environment, timeout=30,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
assert completed.returncode == 0, f"Bundle failed: {completed.returncode}\n{completed.stderr[-4000:]}"
assert report.read_text(encoding="utf-8") == "OK", report.read_text(encoding="utf-8")
sessions = profile / "WinWhisperPlus/sessions"
assert not list(sessions.glob("*/owner.json")), "Session not cleaned on graceful exit"
print("Frozen GUI, model catalogue, FFmpeg, both runtimes and session cleanup: OK")
