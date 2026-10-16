"""A system-wide hotkey, via Win32 rather than Qt.

Qt has no global shortcut -- QShortcut only fires when the app holds focus, which is exactly
backwards here: the whole point is to snip whatever else is in front. So this goes to
RegisterHotKey directly through ctypes.

No third-party dependency, and deliberately not one of the `keyboard` / `pynput` packages: those
install a low-level keyboard hook that sees every keystroke on the machine, which is both far more
privilege than reading one chord needs and the kind of thing anti-cheat and antivirus take an
interest in. RegisterHotKey asks the OS to tell us about one specific combination and nothing else.

Passing a null window handle posts WM_HOTKEY to the *thread's* message queue. Qt's Windows event
dispatcher pumps that queue and hands unclaimed messages to native event filters, so a
QAbstractNativeEventFilter is all it takes to catch it.
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

_user32 = ctypes.windll.user32

WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
# Without this, holding the chord down repeats at the keyboard's auto-repeat rate and fires a
# storm of snips.
MOD_NOREPEAT = 0x4000

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
}

# Virtual-key codes for the keys worth binding. Letters and digits are their ASCII values.
_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "insert": 0x2D,
    "delete": 0x2E,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
}


class HotkeyError(RuntimeError):
    """The chord could not be registered -- almost always because something else owns it."""


def parse(spec: str) -> tuple[int, int]:
    """"ctrl+shift+space" -> (modifier mask, virtual-key code)."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise HotkeyError(f"empty hotkey: {spec!r}")

    *names, key = parts
    modifiers = 0
    for name in names:
        if name not in _MODIFIERS:
            raise HotkeyError(f"unknown modifier {name!r} in {spec!r}")
        modifiers |= _MODIFIERS[name]

    if key in _KEYS:
        code = _KEYS[key]
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        code = ord(key.upper())
    else:
        raise HotkeyError(f"unknown key {key!r} in {spec!r}")

    if not modifiers:
        # A bare key would be captured globally, so typing it anywhere would start a snip.
        raise HotkeyError(f"{spec!r} needs at least one modifier")

    return modifiers | MOD_NOREPEAT, code


class GlobalHotkey(QObject, QAbstractNativeEventFilter):
    """Fires `pressed` whenever the chord is struck, whatever has focus.

    Install on the QApplication and keep a reference -- Qt does not own native event filters, and
    a garbage-collected one takes the hotkey with it.
    """

    pressed = Signal()

    _next_id = 1

    def __init__(self, spec: str = "ctrl+shift+space", parent: QObject | None = None):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self.spec = spec
        self._id = GlobalHotkey._next_id
        GlobalHotkey._next_id += 1
        self._registered = False

    def register(self) -> None:
        modifiers, key = parse(self.spec)
        if not _user32.RegisterHotKey(None, self._id, modifiers, key):
            raise HotkeyError(
                f"{self.spec!r} is already taken by another application; choose a different one"
            )
        self._registered = True

    def unregister(self) -> None:
        if self._registered:
            _user32.UnregisterHotKey(None, self._id)
            self._registered = False

    def nativeEventFilter(self, event_type, message):  # noqa: N802  (Qt naming)
        if event_type != b"windows_generic_MSG":
            return False, 0
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.wParam == self._id:
            self.pressed.emit()
            # Still returns False. Claiming the message stops Qt's own processing of the queue,
            # and nothing else wants a WM_HOTKEY addressed to us anyway.
        return False, 0
