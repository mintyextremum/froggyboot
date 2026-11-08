"""Small helpers: Wake-on-LAN, Windows image editions, WinPE install reports."""
from __future__ import annotations

import logging
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .config import MAC_RE

log = logging.getLogger("froggyboot")


# ---------------------------------------------------------------- Wake-on-LAN
def wake(macs: list[str], broadcast: str, port: int = 9) -> int:
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for mac in macs:
            raw = bytes.fromhex(mac.replace("-", ""))
            packet = b"\xff" * 6 + raw * 16
            for _ in range(3):  # UDP may drop one
                s.sendto(packet, (broadcast, port))
            sent += 1
    return sent


# ---------------------------------------------------------------- Windows images
_editions_cache: dict[tuple[str, float], list[dict]] = {}


def list_images(images_dir: Path) -> list[dict]:
    """install.wim / *.esd files with their editions (needs wimtools for editions)."""
    out = []
    if not images_dir.is_dir():
        return out
    for f in sorted(images_dir.iterdir()):
        if f.suffix.lower() not in (".wim", ".esd") or not f.is_file():
            continue
        out.append({"file": f.name, "size": f.stat().st_size, "editions": editions(f)})
    return out


def editions(path: Path) -> list[dict]:
    key = (str(path), path.stat().st_mtime)
    if key in _editions_cache:
        return _editions_cache[key]
    exe = shutil.which("wimlib-imagex") or shutil.which("wiminfo")
    result: list[dict] = []
    if exe:
        cmd = [exe, "info", str(path)] if exe.endswith("imagex") else [exe, str(path)]
        try:
            text = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
            idx = None
            for line in text.splitlines():
                m = re.match(r"^Index:\s+(\d+)", line)
                if m:
                    idx = int(m.group(1))
                m = re.match(r"^Name:\s+(.+)$", line)
                if m and idx is not None:
                    result.append({"index": idx, "name": m.group(1).strip()})
                    idx = None
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("wiminfo %s: %s", path, e)
    _editions_cache[key] = result
    return result


# ---------------------------------------------------------------- WinPE reports
class ReportWatcher:
    """Follows <incoming>/reports/<mac>.log files written by install.cmd over SMB.

    Each line is "STEP|detail"; on_step(mac, step, detail) is called for new lines.
    """

    def __init__(self, reports_dir: Path, on_step: Callable[[str, str, str], None], interval: float = 3):
        self.dir, self.on_step, self.interval = reports_dir, on_step, interval
        self.offsets: dict[str, int] = {}
        self._stop = threading.Event()
        # Lines already present at startup are history, not news.
        for f in self._files():
            self.offsets[f.name] = f.stat().st_size

    def _files(self) -> list[Path]:
        return [f for f in self.dir.glob("*.log") if MAC_RE.match(f.stem)] if self.dir.is_dir() else []

    def scan(self) -> None:
        for f in self._files():
            size = f.stat().st_size
            off = self.offsets.get(f.name, 0)
            if size < off:  # file was recreated
                off = 0
            if size == off:
                continue
            with f.open("rb") as fh:
                fh.seek(off)
                chunk = fh.read(size - off)
            # Only consume complete lines.
            end = chunk.rfind(b"\n")
            if end < 0:
                continue
            self.offsets[f.name] = off + end + 1
            for raw in chunk[: end + 1].decode("ascii", "replace").splitlines():
                step, _, detail = raw.strip().partition("|")
                if re.fullmatch(r"[a-z][a-z0-9-]{0,20}", step):
                    self.on_step(f.stem, step, detail.strip())

    def start(self) -> None:
        def loop():
            while not self._stop.wait(self.interval):
                try:
                    self.scan()
                except OSError as e:
                    log.warning("report scan: %s", e)
        threading.Thread(target=loop, daemon=True, name="reports").start()

    def stop(self) -> None:
        self._stop.set()
