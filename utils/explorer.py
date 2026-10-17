"""Reveal a local file without shell interpolation or creating directories."""
from pathlib import Path
import subprocess


def reveal_file(path):
    path = Path(path)
    if path.is_file():
        arguments = ["explorer.exe", "/select,", str(path)]
    elif path.parent.is_dir():
        arguments = ["explorer.exe", str(path.parent)]
    else:
        raise FileNotFoundError(str(path.parent))
    subprocess.Popen(arguments)
