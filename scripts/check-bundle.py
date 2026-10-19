"""Launch the frozen executable with isolated data and bounded lifetime."""
from pathlib import Path
import os
import subprocess
import argparse
import tempfile
from runtime_bundle import audit_package

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--package", default="build/feature-package")
parser.add_argument("--check-downloads", action="store_true", help="Also verify real HTTPS downloads and redirects (requires Internet)")
args = parser.parse_args()
package = root / args.package
executable = package / "WinWhisperPlus.exe"
if not executable.is_file():
    executable = package / "WinWhisperPlus/WinWhisperPlus.exe"
package = executable.parent.resolve()
audit_package(package)
def snapshot():
    return {str(path.relative_to(package)): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in package.rglob("*") if path.is_file()}
before = snapshot()
(root / "build").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="bundle-smoke-", dir=root / "build") as directory:
    profile = Path(directory)
    environment = dict(os.environ, APPDATA=str(profile / "roaming"), LOCALAPPDATA=str(profile / "local"),
                       QT_QPA_PLATFORM="offscreen", PATH=str(Path(os.environ["SystemRoot"]) / "System32"))
    report = profile / "roaming/WinWhisperPlus/bundle-smoke.txt"
    completed = subprocess.run([str(executable.resolve()), "--smoke-test"], env=environment, cwd=profile, timeout=30,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert completed.returncode == 0, f"Bundle failed: {completed.returncode}\n{completed.stderr[-4000:]}"
    assert report.read_text(encoding="utf-8") == "OK", report.read_text(encoding="utf-8")
    # Force the bundled Khronos loader to see no installed drivers, without
    # changing the system loader, graphics drivers or registry on this PC.
    report.unlink()
    no_driver_environment = dict(environment, VK_DRIVER_FILES=str(profile / "absent-vulkan-driver.json"))
    completed = subprocess.run([str(executable.resolve()), "--smoke-test", "--smoke-no-vulkan"],
                               env=no_driver_environment, cwd=profile, timeout=40,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert completed.returncode == 0, f"No-driver fallback failed: {completed.returncode}\n{completed.stderr[-4000:]}"
    assert report.read_text(encoding="utf-8") == "OK", report.read_text(encoding="utf-8")
    assert not list(profile.glob("local/WinWhisperPlus/sessions/*/owner.json")), "Session not cleaned"
    if args.check_downloads:
        report.unlink()
        completed = subprocess.run([str(executable.resolve()), "--smoke-test", "--smoke-downloads"],
                                   env=environment, cwd=profile, timeout=150,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert completed.returncode == 0, f"HTTPS download check failed: {completed.returncode}\n{completed.stderr[-4000:]}"
        assert report.read_text(encoding="utf-8") == "OK", report.read_text(encoding="utf-8")
        assert (profile / "local/WinWhisperPlus/models/ggml-silero-v6.2.0.bin.receipt.json").is_file()
        print("Frozen HTTPS: verified model download, Hugging Face/CDN redirects and GitHub catalogue TLS: OK")
    assert not list(profile.rglob("*.gguf")), "Smoke test must not download models"
    # Actually start each CPU executable, from an unrelated working directory.
    for folder, filenames in (("whispercpp-cpu", ["whisper-cli.exe", "whisper-server.exe"]),
                              ("textoptimizer-cpu", ["llama-server.exe"])):
        for filename in filenames:
            completed = subprocess.run([str(package / "_internal" / folder / filename), "--help"],
                                       env=environment, cwd=package / "_internal" / folder, timeout=30, capture_output=True)
            assert completed.returncode == 0, f"CPU runtime failed: {folder}/{filename}: {completed.stderr[-2000:]}"
assert before == snapshot(), "Application wrote into its program directory"
print("Frozen GUI, single instance, CPU processes, automatic CPU fallback without Vulkan drivers, empty user profile, no program writes, session cleanup: OK")
