"""BHTP/1 -- framing and header codec shared by bserve and bcurl.

Everything on the wire is described in SPEC.md. This module is the only
place that knows the byte layout; the server and client just call it.
"""

import collections

# ---------------------------------------------------------------- framing

FRAME_HEADER_LEN = 8          # length:24 | type:8 | flags:8 | stream:24
MAX_FRAME = 16384             # largest payload a v1 peer must accept

HEADERS = 0x01
DATA = 0x02
GOAWAY = 0x03
TYPE_NAMES = {HEADERS: "HEADERS", DATA: "DATA", GOAWAY: "GOAWAY"}

END_STREAM = 0x01

MAX_STREAM = 0xFFFFFF

Frame = collections.namedtuple("Frame", "type flags stream payload raw oversized")


class ProtocolError(Exception):
    """The frame boundaries are intact but the contents are malformed."""


def pack_frame(ftype, flags, stream, payload=b""):
    if len(payload) > 0xFFFFFF:
        raise ValueError("payload too large for a 24-bit length")
    if not 0 <= stream <= MAX_STREAM:
        raise ValueError("stream id out of range")
    return (len(payload).to_bytes(3, "big") + bytes([ftype, flags])
            + stream.to_bytes(3, "big") + payload)


def parse_frame_header(b):
    return (int.from_bytes(b[0:3], "big"), b[3], b[4], int.from_bytes(b[5:8], "big"))


def recv_exact(sock, n):
    """Read exactly n bytes. None on a clean EOF before any byte, EOFError mid-read."""
    chunks, got = [], 0
    while got < n:
        chunk = sock.recv(n - got)
        if not chunk:
            if got == 0:
                return None
            raise EOFError("connection closed in the middle of a frame")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def _discard(sock, n):
    while n > 0:
        chunk = sock.recv(min(n, 65536))
        if not chunk:
            raise EOFError("connection closed in the middle of a frame")
        n -= len(chunk)


def read_frame(sock, max_payload=MAX_FRAME):
    """Read one frame. Returns None on clean EOF.

    A payload longer than max_payload is read and thrown away (the length
    field still tells us where the next frame starts), and the frame comes
    back with oversized=True and payload=None.
    """
    hdr = recv_exact(sock, FRAME_HEADER_LEN)
    if hdr is None:
        return None
    length, ftype, flags, stream = parse_frame_header(hdr)
    if length > max_payload:
        _discard(sock, length)
        return Frame(ftype, flags, stream, None, hdr, True)
    payload = recv_exact(sock, length) if length else b""
    if payload is None:
        raise EOFError("connection closed in the middle of a frame")
    return Frame(ftype, flags, stream, payload, hdr + payload, False)


# ---------------------------------------------------------- header block

# The ten names we actually send. Index 0 means "literal name follows";
# 11..255 are reserved and a v1 receiver treats them as malformed.
STATIC = [
    "method",          # 1
    "path",            # 2
    "status",          # 3
    "host",            # 4
    "user-agent",      # 5
    "accept",          # 6
    "content-type",    # 7
    "content-length",  # 8
    "server",          # 9
    "date",            # 10
]
STATIC_INDEX = {name: i + 1 for i, name in enumerate(STATIC)}
LITERAL = 0x00

_TOKEN = set(b"abcdefghijklmnopqrstuvwxyz0123456789-_.")


def encode_headers(fields):
    out = bytearray()
    for name, value in fields:
        name = name.lower()
        if isinstance(value, str):
            value = value.encode("utf-8")
        if len(value) > 0xFFFF:
            raise ValueError("header value longer than 65535 bytes")
        idx = STATIC_INDEX.get(name)
        if idx is not None:
            out.append(idx)
        else:
            raw = name.encode("ascii")
            if not 1 <= len(raw) <= 255:
                raise ValueError("literal header name must be 1..255 bytes")
            out.append(LITERAL)
            out.append(len(raw))
            out += raw
        out += len(value).to_bytes(2, "big")
        out += value
    return bytes(out)


def decode_headers(payload):
    """Return a list of (name, value) pairs or raise ProtocolError."""
    fields, i, n = [], 0, len(payload)
    while i < n:
        idx = payload[i]
        i += 1
        if idx == LITERAL:
            if i >= n:
                raise ProtocolError("truncated literal name length")
            nlen = payload[i]
            i += 1
            raw = payload[i:i + nlen]
            if nlen == 0 or len(raw) != nlen:
                raise ProtocolError("bad literal name")
            if not set(raw) <= _TOKEN:
                raise ProtocolError("literal name has illegal characters")
            name = raw.decode("ascii")
            i += nlen
        elif idx <= len(STATIC):
            name = STATIC[idx - 1]
        else:
            raise ProtocolError("unknown static index %d" % idx)
        if i + 2 > n:
            raise ProtocolError("truncated value length for %s" % name)
        vlen = int.from_bytes(payload[i:i + 2], "big")
        i += 2
        if i + vlen > n:
            raise ProtocolError("value for %s runs past end of frame" % name)
        try:
            value = payload[i:i + vlen].decode("utf-8")
        except UnicodeDecodeError:
            raise ProtocolError("value for %s is not UTF-8" % name)
        i += vlen
        fields.append((name, value))
    return fields


# --------------------------------------------------------------- display

def hexdump(data, indent=""):
    lines = []
    for off in range(0, len(data), 16):
        row = data[off:off + 16]
        hexpart = " ".join("%02x" % b for b in row)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append("%s%04x  %-47s  |%s|" % (indent, off, hexpart, text))
    return "\n".join(lines)


def describe(frame):
    name = TYPE_NAMES.get(frame.type, "UNKNOWN(0x%02x)" % frame.type)
    flags = "END_STREAM" if frame.flags & END_STREAM else "-"
    length = parse_frame_header(frame.raw)[0]
    line = "%s len=%d flags=%s stream=%d" % (name, length, flags, frame.stream)
    if frame.oversized:
        return line + " (oversized, payload discarded)"
    if frame.type == HEADERS:
        try:
            for k, v in decode_headers(frame.payload):
                line += "\n    %s: %s" % (k, v)
        except ProtocolError as e:
            line += "\n    (malformed: %s)" % e
    return line


def dump(stream, direction, frame):
    """Print a frame for -v: one summary line, then every byte of it."""
    stream.write("%s %s\n" % (direction, describe(frame)))
    # cap the visible bytes of big DATA frames so a 1 MB file stays readable
    raw = frame.raw if len(frame.raw) <= 8 + 256 else frame.raw[:8 + 256]
    stream.write(hexdump(raw, "  ") + "\n")
    if raw is not frame.raw:
        stream.write("  ... %d more bytes\n" % (len(frame.raw) - len(raw)))
    stream.flush()


def as_frame(raw):
    """Wrap bytes we are about to send so dump()/describe() can show them."""
    length, ftype, flags, stream = parse_frame_header(raw)
    return Frame(ftype, flags, stream, raw[8:], raw, False)
