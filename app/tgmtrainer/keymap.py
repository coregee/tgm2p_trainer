from __future__ import annotations

from PySide6.QtCore import Qt

_SPECIAL = {
    Qt.Key_Escape: "ESC",
    Qt.Key_Space: "SPACE",
    Qt.Key_Return: "ENTER",
    Qt.Key_Enter: "ENTER_PAD",
    Qt.Key_Tab: "TAB",
    Qt.Key_Backspace: "BACKSPACE",
    Qt.Key_Insert: "INSERT",
    Qt.Key_Delete: "DEL",
    Qt.Key_Home: "HOME",
    Qt.Key_End: "END",
    Qt.Key_PageUp: "PGUP",
    Qt.Key_PageDown: "PGDN",
    Qt.Key_Up: "UP",
    Qt.Key_Down: "DOWN",
    Qt.Key_Left: "LEFT",
    Qt.Key_Right: "RIGHT",
    Qt.Key_Minus: "MINUS",
    Qt.Key_Equal: "EQUALS",
    Qt.Key_BracketLeft: "OPENBRACE",
    Qt.Key_BracketRight: "CLOSEBRACE",
    Qt.Key_Semicolon: "COLON",
    Qt.Key_Apostrophe: "QUOTE",
    Qt.Key_QuoteLeft: "TILDE",
    Qt.Key_Backslash: "BACKSLASH",
    Qt.Key_Comma: "COMMA",
    Qt.Key_Period: "STOP",
    Qt.Key_Slash: "SLASH",
}


def mame_token(qt_key: int) -> str | None:
    qt_key = int(qt_key)
    if (int(Qt.Key_A) <= qt_key <= int(Qt.Key_Z)) or (int(Qt.Key_0) <= qt_key <= int(Qt.Key_9)):
        return "KEYCODE_" + chr(qt_key)
    if int(Qt.Key_F1) <= qt_key <= int(Qt.Key_F15):
        return "KEYCODE_F%d" % (qt_key - int(Qt.Key_F1) + 1)
    suffix = _SPECIAL.get(qt_key)
    return "KEYCODE_" + suffix if suffix else None

_MODS = (
    (Qt.ControlModifier, "ctrl"),
    (Qt.ShiftModifier, "shift"),
    (Qt.AltModifier, "alt"),
    (Qt.MetaModifier, "win"),
)


def mod_names(modifiers) -> list[str]:
    return [name for flag, name in _MODS if modifiers & flag]
