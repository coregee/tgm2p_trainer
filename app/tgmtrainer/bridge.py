from __future__ import annotations

import json
import socket
import threading
import time

from PySide6.QtCore import QObject, Signal

class Bridge(QObject):
    connectionChanged = Signal(bool)
    stateReceived = Signal(dict)
    notice = Signal(str)
    hotkeyEvent = Signal(str, str)   # (action_id, "press"|"tap"|"hold")

    HEARTBEAT_TIMEOUT = 4.0
    PING_INTERVAL = 1.0
    RECONNECT_BACKOFF = (0.25, 0.5, 1.0, 2.0)

    def __init__(self, host: str = "127.0.0.1", port: int = 50575):
        super().__init__()
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = False
        self._desired: dict = {}
        self._desired_lock = threading.Lock()
        self._players: list[int] = [0]
        self._hotkeys: list = []   # last bindings sent; resent on (re)connect

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bridge", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close_sock()
        if self._thread:
            self._thread.join(timeout=2.0)

    def send(self, obj: dict) -> bool:
        sock = self._sock
        if not sock:
            return False
        try:
            line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
            with self._send_lock:
                sock.sendall(line)
            return True
        except OSError:
            return False

    def set_override(self, key: str, value=None):
        with self._desired_lock:
            self._desired[key] = value
            players = list(self._players)
        self.send({
            "t": "set_override",
            "key": key,
            "value": value,
            "players": players
        })

    def set_players(self, players: list[int]):
        """
        1P = 0, 2P = 1
        """
        players = sorted(set(players)) or [0]
        with self._desired_lock:
            self._players = players
            desired = dict(self._desired)
        self.send({"t": "set_players", "players": players})
        for key, value in desired.items():
            self.send({
                "t": "set_override",
                "key": key,
                "value": value,
                "players": players
            })

    def clear_override(self, key: str):
        with self._desired_lock:
            self._desired.pop(key, None)
        self.send({
            "t": "clear_override",
            "key": key
        })

    def write(self, key: str, value):
        self.send({
            "t": "write",
            "key": key,
            "value": value,
            "players": list(self._players)
        })

    def set_hotkeys(self, bindings: list):
        """Push the active hotkey bindings to the plugin, which polls MAME's
        host-input layer for them. Stored so they resend on reconnect."""
        with self._desired_lock:
            self._hotkeys = list(bindings)
        self.send({"t": "set_hotkeys", "bindings": bindings})

    def reload_config(self):
        self.send({"t": "reload_config"})

    def osd(self, text: str):
        self.send({
            "t": "osd",
            "text": text
        })

    def _set_connected(self, value: bool):
        if value != self._connected:
            self._connected = value
            self.connectionChanged.emit(value)

    def _close_sock(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _run(self):
        attempt = 0
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self._host, self._port), timeout=1.5)
            except OSError:
                attempt += 1
                delay = self.RECONNECT_BACKOFF[min(attempt - 1, len(self.RECONNECT_BACKOFF) - 1)]
                self._stop.wait(delay)
                continue

            attempt = 0
            sock.settimeout(0.5)
            self._sock = sock

            self.send({"t": "hello"})
            with self._desired_lock:
                desired = dict(self._desired)
                players = list(self._players)
                hotkeys = list(self._hotkeys)

            self.send({"t": "set_players", "players": players})
            for key, value in desired.items():
                self.send({"t": "set_override", "key": key, "value": value, "players": players})
            if hotkeys:
                self.send({"t": "set_hotkeys", "bindings": hotkeys})

            buffer = b""
            last_hb = time.monotonic()
            last_ping = 0.0

            try:
                while not self._stop.is_set():
                    try:
                        data = sock.recv(4096)
                        if not data:
                            break
                        buffer += data
                        buffer, msgs = _split_lines(buffer)
                        for m in msgs:
                            if m.get("t") == "heartbeat":
                                last_hb = time.monotonic()
                                self._set_connected(True)
                            self._on_message(m)
                    except socket.timeout:
                        pass
                    except OSError:
                        break

                    now = time.monotonic()
                    if now - last_ping >= self.PING_INTERVAL:
                        last_ping = now
                        if not self.send({"t": "ping"}):
                            break
                    if now - last_hb >= self.HEARTBEAT_TIMEOUT:
                        break
            finally:
                self._set_connected(False)
                self._close_sock()

        self._set_connected(False)

    def _on_message(self, m: dict):
        t = m.get("t")
        if t == "hello":
            self.notice.emit(f"Bridge v{m.get('version','?')} (rom={m.get('rom','?')})")
        elif t == "state":
            self.stateReceived.emit(m)
        elif t == "error":
            self.notice.emit(f"error: {m.get('key','')} {m.get('msg','')}".strip())
        elif t == "ack":
            key = m.get("key")
            if key:
                self.notice.emit(f"ok: {key}")
        elif t == "hotkey":
            action, event = m.get("action"), m.get("event")
            if action and event:
                self.hotkeyEvent.emit(action, event)


def _split_lines(buffer: bytes):
    msgs = []
    while True:
        nl = buffer.find(b"\n")
        if nl < 0:
            break
        line = buffer[:nl].strip()
        buffer = buffer[nl + 1:]
        if line:
            try:
                msgs.append(json.loads(line.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                pass
    return buffer, msgs
