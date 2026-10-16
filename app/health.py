"""What the process is holding on to, sampled into the log.

Written after a crash there was nothing to study: the log recorded

    Windows fatal exception: access violation
    Current thread 0x0000327c (most recent call first):
      <no Python frame>

An access violation on a thread with no Python frame is a fault inside native code -- Qt, ONNX
Runtime, or a Windows call one of them made. Python cannot catch it and faulthandler can only say
that it happened, so the question "what was the process doing beforehand" has to be answered by
what was already written to disk when it died.

Hence sampling on a timer rather than on demand. The log is line-buffered, so the last sample
before a crash is always on disk, and a crash is then preceded by a picture of the process
instead of arriving out of nowhere.

The counters were chosen for what they can each rule in or out:

  rss       plain memory growth -- an unbounded buffer, a cache with no eviction
  gdi/user  the Windows ones, and the reason this module exists at all. Every process has a hard
            default limit of 10,000 GDI objects; past it, creating a pen or a bitmap simply fails,
            and the native code that assumed it succeeded dereferences nothing. That is precisely
            an access violation with no Python frame, and it arrives "after some time" -- which is
            what was reported. A watched region paints four times a second, so if anything here
            leaks a handle per frame the limit is minutes away, not days.
  handles   kernel handles: files, events, threads. Leaks here point at something not being
            closed rather than not being painted.
  threads   Python-level thread count. Should be flat at four or so; a climb means something is
            spawning and never joining.
  gc        tracked Python objects, which is the closest cheap proxy for "are widgets piling up".

Nothing here is Qt-specific on purpose: the suspects are native, so the measurements are too.

Windows only, and non-fatal everywhere else -- sample() returns what it can and says so, rather
than making a diagnostic aid into a new way to fail.
"""

import ctypes
import gc
import sys
import threading
from dataclasses import dataclass

_WINDOWS = sys.platform == "win32"

#: GetGuiResources flags.
_GR_GDIOBJECTS = 0
_GR_USEROBJECTS = 1

#: Windows' default per-process ceiling. Not a constant anyone should tune -- it is a registry
#: setting most machines never change -- but it is the number a GDI reading has to be read
#: against, so a sample is worth flagging once it is a meaningful fraction of it.
GDI_LIMIT = 10_000
#: Say so in the log from here up, so the warning lands before the crash rather than after it.
GDI_WARN_AT = 6_000


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _win32():
    """The three DLLs, with their signatures declared.

    Declaring them is not optional here and the omission is silent: GetCurrentProcess returns a
    pseudo-handle of (HANDLE)-1, and ctypes defaults a return type to C int -- so on 64-bit the
    handle is truncated, every call that receives it fails, and the whole module reports zeros
    that look like a perfectly healthy process.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    user32.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    user32.GetGuiResources.restype = ctypes.c_uint32
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_uint32,
    ]
    return kernel32, user32, psapi


@dataclass(frozen=True)
class Sample:
    rss_mb: float = 0.0
    peak_mb: float = 0.0
    gdi: int = 0
    user: int = 0
    handles: int = 0
    threads: int = 0
    objects: int = 0
    available: bool = True

    def line(self) -> str:
        """One line, fixed order, so a log can be read as a column."""
        if not self.available:
            return f"health  threads {self.threads}  objects {self.objects}  (no win32 counters)"
        return (
            f"health  rss {self.rss_mb:.0f}MB (peak {self.peak_mb:.0f})  "
            f"gdi {self.gdi}  user {self.user}  handles {self.handles}  "
            f"threads {self.threads}  objects {self.objects}"
        )

    @property
    def gdi_alarming(self) -> bool:
        return self.available and self.gdi >= GDI_WARN_AT


def sample() -> Sample:
    """Take a reading. Never raises: a diagnostic must not become a fault of its own."""
    threads = threading.active_count()
    objects = len(gc.get_objects())

    if not _WINDOWS:
        return Sample(threads=threads, objects=objects, available=False)

    try:
        kernel32, user32, psapi = _win32()
        process = kernel32.GetCurrentProcess()

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)

        handles = ctypes.c_uint32()
        kernel32.GetProcessHandleCount(process, ctypes.byref(handles))

        return Sample(
            rss_mb=counters.WorkingSetSize / 1048576,
            peak_mb=counters.PeakWorkingSetSize / 1048576,
            gdi=user32.GetGuiResources(process, _GR_GDIOBJECTS),
            user=user32.GetGuiResources(process, _GR_USEROBJECTS),
            handles=handles.value,
            threads=threads,
            objects=objects,
        )
    except Exception:  # noqa: BLE001 - see the docstring; this is the one place it is right
        return Sample(threads=threads, objects=objects, available=False)


def growth(first: Sample, latest: Sample) -> str:
    """How far things have moved since the app started.

    A single reading says almost nothing -- 40MB and 900 GDI objects is either fine or the middle
    of a leak, and only the slope tells them apart. This is what makes one line of log useful to
    somebody reading it after the fact, without having to diff two by hand.
    """
    if not (first.available and latest.available):
        return f"since start: objects {latest.objects - first.objects:+d}"
    return (
        f"since start: rss {latest.rss_mb - first.rss_mb:+.0f}MB  "
        f"gdi {latest.gdi - first.gdi:+d}  user {latest.user - first.user:+d}  "
        f"handles {latest.handles - first.handles:+d}  "
        f"objects {latest.objects - first.objects:+d}"
    )
