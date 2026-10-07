# BHTP/1 — HTTP, in binary

A small binary framing of HTTP-style GET requests over one TCP connection.
This document is all a stranger needs to write an interoperable client or
server. The key words MUST, MUST NOT, SHOULD and MAY mean what RFC 2119 says.
All integers are **unsigned, big-endian** (network byte order).

## 1. Connection

The client opens **one** TCP connection and sends every request on it. The
server keeps the connection open after each response and serves requests in
the order they arrive. Either side may end the connection by sending GOAWAY
(§3) and closing; closing without GOAWAY is also legal. There is no
preface or handshake: the first bytes on the wire are a frame.

## 2. The frame

Everything on the wire is a frame: a fixed 8-byte header and a payload.

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-----------------------------------------------+---------------+
|                 Length (24)                   |   Type (8)    |
+---------------+-------------------------------+---------------+
|   Flags (8)   |                 Stream ID (24)                |
+---------------+-----------------------------------------------+
|                   Payload (Length bytes) ...                  |
```

| Field | Bits | Meaning |
|---|---|---|
| Length | 24 | Payload size in bytes, not counting the 8-byte header. |
| Type | 8 | Frame type (§3). |
| Flags | 8 | Bit 0x01 = END_STREAM. Other bits MUST be sent as 0 and MUST be ignored. |
| Stream ID | 24 | Which request/response this frame belongs to. 0 = the connection itself. |

**Why these widths.** HTTP/2 uses 24/8/8/31 (plus 1 reserved bit) = 9 bytes.
We keep its first three fields and shrink the stream ID to 24 bits so the
header is exactly **8 bytes — one 64-bit word, one `recv(8)`**.
*Length 24:* 16 bits would cap a frame at 64 KiB forever; 32 bits would spend
a byte that is always zero. 24 bits gives a 16 MiB ceiling, while §2.1 keeps
the *working* limit small. *Type 8 / Flags 8:* we use 3 types and 1 flag;
the other 253 types and 7 bits are our room to grow. *Stream 24:* HTTP/2
needs 31 bits because browsers keep one connection alive for days and IDs
are never reused. Our connection carries one session; 16.7 million requests
per connection is plenty, and a client that runs out opens a new session.
Stream IDs exist at all so every response names the request it answers,
errors can be reported on stream 0, and a version 2 can interleave
responses without changing the header.

### 2.1 Size limit

A v1 sender MUST NOT send a payload longer than **16 384 bytes**. A receiver
that gets a longer one MUST NOT buffer it: it reads and discards exactly
Length bytes (the stream stays in sync) and treats the frame as malformed.

### 2.2 Stream IDs

The client numbers requests 1, 2, 3, … — non-zero and increasing. Every
response frame carries the ID of the request it answers.

## 3. Frame types

| Type | Name | Stream | Payload |
|---|---|---|---|
| 0x01 | HEADERS | ≠ 0 | A header block (§4). Starts a request or a response. |
| 0x02 | DATA | ≠ 0 | Raw body bytes. |
| 0x03 | GOAWAY | 0 | Optional UTF-8 reason. Sender closes after it. |

END_STREAM on a frame means "this is the last frame of this message".

### 3.1 Unknown frame types — MUST skip

**A receiver that meets a frame type it does not know MUST read Length
bytes of payload, discard them, and carry on as if the frame were never
sent.** It MUST NOT reply, error or close. This is the one rule that lets a
version 2 add frames (PING, PUSH, PRIORITY…) that a v1 peer survives.

## 4. Header block

A HEADERS payload is a sequence of fields, back to back, until the payload
ends. There is no count — Length already says where it stops.

```
static name:   | index (1..10) | value len (16) | value bytes |
literal name:  | 0x00 | name len (8) | name bytes | value len (16) | value bytes |
```

The ten names we actually send get one byte each (HPACK's static table).
Anything else is spelled out, length-prefixed (HPACK's string literal).

| # | Name | # | Name |
|---|---|---|---|
| 1 | method | 6 | accept |
| 2 | path | 7 | content-type |
| 3 | status | 8 | content-length |
| 4 | host | 9 | server |
| 5 | user-agent | 10 | date |

Names are lowercase ASCII (`a-z 0-9 - _ .`), 1–255 bytes. Values are UTF-8,
0–65 535 bytes. Index bytes 11–255 are reserved; in v1 they are malformed.
Numbers in values (status, content-length) are ASCII decimal: `"200"`.

## 5. Request and response

**Request** = one HEADERS frame with END_STREAM set, containing exactly one
`method` (`GET` or `HEAD`) and exactly one `path` (starts with `/`). The
client SHOULD send `host`, `user-agent`, `accept`. A v1 request has no body.

**Response** = one HEADERS frame carrying `status` (MUST), and `content-type`,
`content-length`, `server`, `date` (SHOULD), followed by zero or more DATA
frames. The last frame of the response has END_STREAM. If there is no body
(HEAD, empty file) END_STREAM is set on the HEADERS frame itself.

The server maps `path` to a file under its root. A path naming a directory
serves `index.html` inside it. A path that resolves outside the root MUST
NOT be served.

| Status | When |
|---|---|
| 200 | File found. Body = file bytes. |
| 400 | Malformed frame: bad header block, reserved index, missing/duplicate method or path, path not starting with `/`, HEADERS without END_STREAM, HEADERS on stream 0, DATA from a client, payload over 16 384 bytes. |
| 404 | No such file (or outside the root). |
| 405 | Method other than GET/HEAD. |

Error responses carry a short `text/plain` body. **A 400 is sent on the
stream the bad frame named (stream 0 if it named 0) and the connection stays
open** — the Length field always tells the server where the next frame
starts. Only a connection that closes mid-frame is unrecoverable.

## 6. Leaving room for version 2

New frame types are skipped by v1 peers (§3.1); new flag bits are ignored
(§2); the static table can grow into indexes 11–255 once both sides agree;
the 16 KiB working limit can be raised without touching the header.
A complete annotated request and response is in [HEXDUMP.md](HEXDUMP.md).
