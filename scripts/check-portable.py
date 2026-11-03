"""Exercise the actual portable ZIP after moving it to another location."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

archive = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="portable-check-", dir=archive.parent.parent / "build") as temp:
    root = Path(temp)
    program = root / "first"
    program.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(program)
    assert (program / "portable.txt").is_file()
    profile = root / "profile"
    env = dict(os.environ, APPDATA=str(profile / "roaming"), LOCALAPPDATA=str(profile / "local"),
               QT_QPA_PLATFORM="offscreen", PATH=str(Path(os.environ["SystemRoot"]) / "System32"))
    def smoke(folder):
        result = subprocess.run([str(folder / "WinWhisperPlus.exe"), "--smoke-test"], cwd=root, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        report = folder / "data" / "bundle-smoke.txt"
        assert result.returncode == 0, f"Portable smoke failed: {result.stderr[-4000:]}"
        assert report.read_text(encoding="utf-8") == "OK"
        assert not (profile / "roaming" / "WinWhisperPlus").exists()
        assert not (profile / "local" / "WinWhisperPlus").exists()
    smoke(program)
    moved = root / "moved"
    shutil.move(str(program), str(moved))
    smoke(moved)
    print("Portable ZIP: model and data paths, profile isolation and relocation: OK")
