"""Desired-state bridge: full snapshots, revision acknowledgements, bounded framing."""

from __future__ import annotations

import copy
import json
import socket
import threading
import time

from PySide6.QtCore import QObject, Signal

PROTOCOL = 3
MAX_LINE = 65536


def split_lines(buffer: bytes):
    messages = []
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        if len(line) > MAX_LINE:
            raise ValueError("Bridge message exceeds 64 KiB")
        try:
            message = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if isinstance(message, dict):
            messages.append(message)
    if len(buffer) > MAX_LINE:
        raise ValueError("Bridge message exceeds 64 KiB")
    return buffer, messages


class Bridge(QObject):
    connectionChanged = Signal(bool)
    readyChanged = Signal(bool)
    stateReceived = Signal(dict)
    statusReceived = Signal(dict)
    acknowledged = Signal(int)
    hotkeyEvent = Signal(str, str)
    notice = Signal(str)

    def __init__(self, host="127.0.0.1", port=50575, patch_id=None):
        super().__init__()
        self.host, self.port, self.patch_id = host, port, patch_id
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._socket = None
        self._compatible = False
        self._settings = {"players": [{}, {}], "global": {}}
        self._revision = 0
        self._bindings = []

    @property
    def settings(self):
        with self._lock:
            return copy.deepcopy(self._settings)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="trainer-bridge"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._disconnect()
        if self._thread:
            self._thread.join(timeout=2)

    def _disconnect(self):
        with self._lock:
            sock, self._socket = self._socket, None
            self._compatible = False
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _send(self, message):
        with self._lock:
            if self._socket is None:
                return False
            try:
                self._socket.sendall(
                    (json.dumps(message, separators=(",", ":")) + "\n").encode()
                )
                return True
            except OSError:
                return False

    def replace_settings(self, settings):
        with self._lock:
            self._settings = copy.deepcopy(settings)
            self._revision += 1
            if self._compatible:
                self._sync()
            return self._revision

    def _sync(self):
        # Called under the same lock as local edits; a reconnect cannot publish
        # an older snapshot after a newer UI edit.
        self._send({"t": "sync", "id": self._revision, "settings": self._settings})

    def action(self, action, player=0, value=None):
        with self._lock:
            if not self._compatible:
                # Practice clicks are transient: silently drop them offline,
                # and let the plugin check the live game state when connected.
                if action not in ("level", "section", "grade", "restart"):
                    self.notice.emit("Connect to a ready game before using an action.")
                return
            self._send(
                {"t": "action", "action": action, "player": player, "value": value}
            )

    def set_hotkeys(self, bindings):
        with self._lock:
            self._bindings = copy.deepcopy(bindings)
            if self._compatible:
                self._send({"t": "bindings", "bindings": self._bindings})

    def reset_machine(self):
        self._send({"t": "reset_machine"})

    def _run(self):
        backoff = 0.25
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=1)
                sock.settimeout(0.25)
            except OSError:
                self._stop.wait(backoff)
                backoff = min(2, backoff * 2)
                continue
            with self._lock:
                self._socket = sock
            self._send({"t": "hello"})
            last_received = time.monotonic()
            last_ping = 0
            buffer = b""
            try:
                while not self._stop.is_set():
                    try:
                        data = sock.recv(16384)
                        if not data:
                            break
                        buffer, messages = split_lines(buffer + data)
                        for message in messages:
                            kind = message.get("t")
                            if kind == "hello":
                                compatible = (
                                    message.get("protocol") == PROTOCOL
                                    and message.get("rom") == "tgm2p"
                                    and message.get("compatible") is True
                                    and (
                                        self.patch_id is None
                                        or message.get("patch_id") == self.patch_id
                                    )
                                )
                                if not compatible:
                                    self.notice.emit(
                                        "Plugin mismatch. Launch MAME from this trainer to use its matching plugin."
                                    )
                                    raise ValueError("Incompatible bridge")
                                with self._lock:
                                    self._compatible = True
                                    self._sync()
                                    self._send(
                                        {"t": "bindings", "bindings": self._bindings}
                                    )
                                self.connectionChanged.emit(True)
                                backoff = 0.25
                            if not self._compatible:
                                continue
                            last_received = time.monotonic()
                            if (
                                kind in ("heartbeat", "state", "status", "ack")
                                and "ready" in message
                            ):
                                self.readyChanged.emit(message["ready"] is True)
                            if kind == "state":
                                self.stateReceived.emit(message)
                            elif kind == "status":
                                self.statusReceived.emit(message)
                                if message.get("error"):
                                    self.notice.emit(message["error"])
                            elif kind == "ack" and "settings" in message:
                                self.acknowledged.emit(message["id"])
                            elif kind == "hotkey":
                                self.hotkeyEvent.emit(
                                    message["action"], message["event"]
                                )
                            elif kind == "error":
                                self.notice.emit(
                                    message.get("msg", "Bridge rejected a command")
                                )
                    except TimeoutError:
                        pass
                    now = time.monotonic()
                    if now - last_ping >= 1:
                        if not self._send({"t": "ping"}):
                            break
                        last_ping = now
                    if now - last_received > 4:
                        break
            except (OSError, ValueError) as exc:
                if not self._stop.is_set():
                    self.notice.emit(str(exc))
            finally:
                self._disconnect()
                self.connectionChanged.emit(False)
                self.readyChanged.emit(False)
            self._stop.wait(0.25)
