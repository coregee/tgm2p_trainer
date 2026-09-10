"""Editable sliders in displayed units; gravity uses a piecewise physical scale."""

from fractions import Fraction

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

ONE_G = 65536


def gravity_text(raw):
    whole, remainder = divmod(raw, ONE_G)
    if whole and remainder:
        return f"{whole} + {remainder / 256:g}/256 G"
    return f"{whole} G" if whole else f"{raw / 256:g}/256 G"


class GravitySlider(QSlider):
    gravityChanged = Signal(int)
    # 19 slider positions per 1/256G below 1G, one per 1/256G above it.
    # Both linear segments therefore occupy exactly 4,864 positions.
    MIDPOINT = 19 * 256

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setRange(0, 2 * self.MIDPOINT)
        # Track clicks must advance far enough to cross a quarter-G snap point.
        self.setPageStep(256)
        self.setTickInterval(self.MIDPOINT)
        self.setTickPosition(QSlider.TicksBelow)
        self._raw = 0
        self.valueChanged.connect(self._moved)

    @staticmethod
    def normalize(raw):
        raw = max(0, min(20 * ONE_G, raw))
        step = 256 if raw <= ONE_G else 1024 if raw <= 5 * ONE_G else ONE_G // 4
        return int((raw + step // 2) // step) * step

    @classmethod
    def gravity_for_pos(cls, pos):
        raw = (
            pos * ONE_G / cls.MIDPOINT
            if pos <= cls.MIDPOINT
            else ONE_G + (pos - cls.MIDPOINT) * 256
        )
        return cls.normalize(raw)

    @classmethod
    def pos_for_gravity(cls, raw):
        raw = cls.normalize(raw)
        return (
            round(raw * cls.MIDPOINT / ONE_G)
            if raw <= ONE_G
            else cls.MIDPOINT + (raw - ONE_G) // 256
        )

    def gravity(self):
        return self._raw

    def setGravity(self, raw):
        raw = self.normalize(raw)
        changed = raw != self._raw
        self._raw = raw
        with QSignalBlocker(self):
            self.setValue(self.pos_for_gravity(raw))
        if changed:
            self.gravityChanged.emit(raw)

    def _moved(self, pos):
        self.setGravity(self.gravity_for_pos(pos))

    def step(self, count):
        raw = self._raw
        for _ in range(abs(count)):
            boundary = raw if count > 0 else raw - 1
            step = (
                256
                if boundary < ONE_G
                else 1024
                if boundary < 5 * ONE_G
                else ONE_G // 4
            )
            raw += step * (1 if count > 0 else -1)
        self.setGravity(raw)

    def keyPressEvent(self, event):
        keys = {
            Qt.Key_Left: -1,
            Qt.Key_Down: -1,
            Qt.Key_Right: 1,
            Qt.Key_Up: 1,
            Qt.Key_PageDown: -10,
            Qt.Key_PageUp: 10,
        }
        if event.key() in keys:
            self.step(keys[event.key()])
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        self.step(round(event.angleDelta().y() / 120))
        event.accept()


class GravityControl(QWidget):
    valueChanged = Signal(int)

    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.editor = QLineEdit()
        self.editor.setFixedWidth(130)
        self.editor.setAccessibleName("Gravity value")
        self.editor.setToolTip(
            "Enter G, a fraction (128/256), or a mixed fraction (1 + 4/256). Steps: 1/256G to 1G; 4/256G to 5G; 0.25G above 5G."
        )
        row.addWidget(self.editor)
        scale = QVBoxLayout()
        scale.setSpacing(0)
        self.slider = GravitySlider()
        self.slider.setAccessibleName("Gravity: midpoint is 1G")
        scale.addWidget(self.slider)
        labels = QHBoxLayout()
        for i, text in enumerate(("0G", "1G", "20G")):
            if i:
                labels.addStretch()
            labels.addWidget(QLabel(text))
        scale.addLayout(labels)
        row.addLayout(scale, 1)
        self.slider.gravityChanged.connect(self._changed)
        self.editor.editingFinished.connect(self._entered)
        self.set_raw(ONE_G)

    def _changed(self, raw):
        self.editor.setText(gravity_text(raw))
        self.valueChanged.emit(raw)

    def _entered(self):
        text = (
            self.editor.text()
            .strip()
            .removesuffix("G")
            .removesuffix("g")
            .replace(" ", "")
        )
        try:
            raw = round(sum(Fraction(part) for part in text.split("+")) * ONE_G)
        except (ValueError, ZeroDivisionError):
            raw = self.raw()
        self.set_raw(raw)

    def raw(self):
        return self.slider.gravity()

    def set_raw(self, raw):
        self.slider.setGravity(raw)
        self.editor.setText(gravity_text(self.raw()))


class NumericControl(QWidget):
    valueChanged = Signal(int)

    def __init__(self, spec, suffix=""):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        offset = spec.get("display_offset", 0)
        low, high = spec["min"] + offset, spec["max"] + offset
        self.editor = QSpinBox()
        self.editor.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.editor.setKeyboardTracking(False)
        self.editor.setRange(low, high)
        self.editor.setSuffix(suffix)
        self.editor.setFixedWidth(110)
        self.editor.setAccessibleName(spec["label"] + " value")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(low, high)
        self.slider.setAccessibleName(spec["label"])
        self.slider.setToolTip(f"{low}–{high}{suffix}")
        row.addWidget(self.editor)
        row.addWidget(self.slider, 1)
        self.slider.valueChanged.connect(self.editor.setValue)
        self.editor.valueChanged.connect(self._changed)
        self.setValue(spec["default"] + offset)

    def _changed(self, value):
        with QSignalBlocker(self.slider):
            self.slider.setValue(value)
        self.valueChanged.emit(value)

    def value(self):
        return self.editor.value()

    def setValue(self, value):
        self.editor.setValue(value)
        self.slider.setValue(self.editor.value())
