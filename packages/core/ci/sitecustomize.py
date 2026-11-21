"""Netz-Sperre fuer Testlaeufe (wird nur mit ``EAM_NET_GUARD=1`` aktiv).

Python laedt ``sitecustomize`` beim Start, wenn es im ``sys.path`` liegt. Der
Testlauf setzt ``PYTHONPATH`` auf ``ci/`` (siehe ``ci/run_tests.py``), damit
diese Sperre greift -- auch in Unterprozessen, die Tests selbst starten.

Gesperrt werden ausgehende Verbindungen zu nicht-lokalen Zielen. Loopback
bleibt erlaubt, weil Tests lokale Attrappen (HTTP-Stub) nutzen duerfen.
``bind``/``listen`` werden nicht angefasst: Server im Test sind kein Netz.

Die Meldung nennt Ziel und Zweck. Ein Test, der ins Netz will, wird damit
sichtbar rot statt still gruen.
"""

from __future__ import annotations

import os
import socket

ACTIVE = os.environ.get("EAM_NET_GUARD") == "1"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "::", ""}


def _is_local(address: object) -> bool:
    if isinstance(address, (str, bytes)):
        return True  # AF_UNIX-Pfad
    if isinstance(address, tuple) and address:
        return str(address[0]) in LOCAL_HOSTS
    return True


def _deny(target: object) -> None:
    raise RuntimeError(
        "Netzwerkzugriff im Testlauf gesperrt (EAM_NET_GUARD=1): "
        f"Ziel {target!r}. Tests muessen offline laufen; Attrappen statt Netz."
    )


if ACTIVE:
    _original_connect = socket.socket.connect
    _original_connect_ex = socket.socket.connect_ex
    _original_create_connection = socket.create_connection
    _original_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, address: object) -> None:  # type: ignore[override]
        if not _is_local(address):
            _deny(address)
        return _original_connect(self, address)  # type: ignore[arg-type]

    def connect_ex(self: socket.socket, address: object) -> int:  # type: ignore[override]
        if not _is_local(address):
            _deny(address)
        return _original_connect_ex(self, address)  # type: ignore[arg-type]

    def create_connection(address: object, *args: object, **kwargs: object) -> socket.socket:
        if not _is_local(address):
            _deny(address)
        return _original_create_connection(address, *args, **kwargs)  # type: ignore[arg-type]

    def getaddrinfo(host: object, *args: object, **kwargs: object):
        if not _is_local(host):
            _deny(host)
        return _original_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    socket.socket.connect = connect  # type: ignore[assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[assignment]
    socket.create_connection = create_connection  # type: ignore[assignment]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
