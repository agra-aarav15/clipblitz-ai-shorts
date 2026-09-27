"""Hardware capability probe - honest, measured numbers, stdlib only.

The server can run anywhere: a PC, a laptop, or an Android phone via Termux. Video
rendering needs real CPU and RAM, so we measure the host once and say plainly what
we found. On a device that cannot render, job creation is refused up front with a
clear message ("use your laptop or PC") instead of letting ffmpeg grind the device
into a halt or crash halfway through a job. Nothing here is simulated: every number
comes from the running machine, and the thresholds are plain configuration.
"""

import os
import time

# Thresholds are configuration, not magic: a weak host is refused, a strong one is
# allowed, and tests can lower or raise the bar through the environment.
MIN_CORES = int(os.environ.get("CB_MIN_RENDER_CORES", "2") or 2)
MIN_RAM_GB = float(os.environ.get("CB_MIN_RENDER_RAM", "2.5") or 2.5)

_CACHE = {"ts": 0.0, "value": None}
_CACHE_TTL = 30.0          # seconds; health polls often, the machine does not change


def _ram_gb():
    """Total physical RAM in GiB: GlobalMemoryStatusEx on Windows, /proc/meminfo on
    Linux/Termux. 0.0 means "could not measure" (and then RAM is not counted against)."""
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _MemStatus()
        st.dwLength = ctypes.sizeof(_MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullTotalPhys / (1024 ** 3)
    except Exception:
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 ** 2)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def _ffmpeg_ok():
    try:
        from .config import ffmpeg_available
        return bool(ffmpeg_available())
    except Exception:
        return False


def _probe():
    cores = os.cpu_count() or 1
    ram = round(_ram_gb(), 1)
    ffmpeg_ok = _ffmpeg_ok()
    problems = []
    if cores < MIN_CORES:
        problems.append(f"only {cores} CPU core" + ("" if cores == 1 else "s"))
    if ram and ram < MIN_RAM_GB:
        problems.append(f"only {ram} GB of memory")
    if not ffmpeg_ok:
        problems.append("the ffmpeg engine is missing")
    if problems:
        reason = ("This device can't render clips (" + ", ".join(problems) + "). "
                  "Use your laptop or PC to render them.")
    else:
        reason = "ready"
    return {"cores": cores, "ram_gb": ram, "ffmpeg": ffmpeg_ok,
            "render_capable": not problems, "reason": reason}


def profile(refresh=False):
    """The host's measured capability. Cached briefly so the UI can poll it freely."""
    now = time.time()
    if refresh or not _CACHE["value"] or now - _CACHE["ts"] > _CACHE_TTL:
        _CACHE["value"] = _probe()
        _CACHE["ts"] = now
    return _CACHE["value"]


def render_capable():
    return bool(profile().get("render_capable"))
