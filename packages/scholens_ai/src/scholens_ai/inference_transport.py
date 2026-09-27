"""Standard-library framing and one absolute deadline for private socket calls."""

import socket
import struct
import time

FRAME_HEADER = struct.Struct("!I")
MAX_FRAME_BYTES = 256 * 1024


class EmbeddingUnavailable(RuntimeError):
    """A stable degradation signal containing no query or document content."""


def frame(data: bytes) -> bytes:
    if not 0 < len(data) <= MAX_FRAME_BYTES:
        raise ValueError("Inference frame exceeds its byte bound")
    return FRAME_HEADER.pack(len(data)) + data


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise EmbeddingUnavailable("inference_deadline")
    return value


def _read(connection: socket.socket, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        connection.settimeout(remaining(deadline))
        received = connection.recv(size - len(data))
        if not received:
            raise EmbeddingUnavailable("inference_connection_closed")
        data.extend(received)
    return bytes(data)


def exchange(path: str, request: bytes, deadline: float) -> bytes:
    data = frame(request)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(remaining(deadline))
            connection.connect(path)
            connection.settimeout(remaining(deadline))
            connection.sendall(data)
            size = FRAME_HEADER.unpack(_read(connection, FRAME_HEADER.size, deadline))[
                0
            ]
            if not 0 < size <= MAX_FRAME_BYTES:
                raise EmbeddingUnavailable("inference_response_bound")
            return _read(connection, size, deadline)
    except OSError as exc:
        raise EmbeddingUnavailable("inference_unavailable") from exc
