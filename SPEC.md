# BHTP/1 — HTTP, in binary

Binary framing for HTTP-style GET/HEAD over one TCP connection. MUST / SHOULD /
MAY as in RFC 2119. All integers are unsigned big-endian.

## 1. Connection

The client opens **one** TCP connection and sends every request on it; the
server answers in order and **keeps the connection open**, after errors too.
No handshake: the first bytes on the wire are a frame. Either side may send
GOAWAY (§3) and close.

## 2. The frame — 8-byte header, then payload

```
+-----------------------------------------------+---------------+
|                 Length (24)                   |   Type (8)    |
+---------------+-------------------------------+---------------+
|   Flags (8)   |                 Stream ID (24)                |
+---------------+-----------------------------------------------+
|                   Payload (Length bytes) ...                  |
```

- **Length** — payload bytes, header not counted.
- **Type** — §3.
- **Flags** — 0x01 = END_STREAM (last frame of this message). Other bits: send 0, ignore.
- **Stream ID** — the request this frame belongs to; 0 = the connection.
  Clients number requests 1, 2, 3, …; responses reuse the request's ID.

**Why 24/8/8/24.** HTTP/2 uses 24/8/8/31 + 1 reserved bit = 9 bytes. We keep
its first three fields and cut the stream ID to 24 bits, so the header is
exactly **8 bytes — one 64-bit word, one `recv(8)`**. *Length 24:* 16 bits
would cap frames at 64 KiB forever, 32 bits wastes a byte that is always 0.
*Type 8 / Flags 8:* we use 3 types and 1 flag; the rest is room to grow.
*Stream 24:* HTTP/2 needs 31 bits because browsers hold a connection for days
and never reuse IDs; 16.7 million requests per session is plenty for us. We
keep a stream ID at all so each response names its request, connection-level
errors have stream 0, and v2 can interleave responses with the same header.

**Size limit.** A v1 sender MUST NOT send a payload over **16 384 bytes**
(bodies are split across DATA frames). A receiver that gets a bigger one reads
and discards exactly Length bytes — staying in sync — and treats it as malformed.

## 3. Frame types

| Type | Name | Stream | Payload |
|---|---|---|---|
| 0x01 | HEADERS | ≠ 0 | Header block (§4); opens a request or response |
| 0x02 | DATA | ≠ 0 | Body bytes |
| 0x03 | GOAWAY | 0 | Optional UTF-8 reason; sender then closes |

### 3.1 Unknown frame types — MUST skip

**A receiver that meets a frame type it does not know MUST read Length bytes,
discard them, and carry on as if the frame never came** — no reply, no error,
no close. This is what lets a version 2 add frames a v1 peer survives.

## 4. Header block

A HEADERS payload is fields back to back until Length runs out:

```
static name:   | index 1..10 | value len (16) | value |
literal name:  | 0x00 | name len (8) | name | value len (16) | value |
```

The ten names we actually send cost one byte (HPACK's static table); any other
name is length-prefixed (HPACK's string literal).

| # | Name | # | Name | # | Name | # | Name | # | Name |
|---|---|---|---|---|---|---|---|---|---|
| 1 | method | 3 | status | 5 | user-agent | 7 | content-type | 9 | server |
| 2 | path | 4 | host | 6 | accept | 8 | content-length | 10 | date |

Names: lowercase `a-z 0-9 - _ .`, 1–255 bytes. Values: UTF-8, 0–65 535 bytes.
Numbers are ASCII decimal (`"200"`). Indexes 11–255 are reserved → malformed in v1.

## 5. Request and response

**Request:** one HEADERS frame with END_STREAM, exactly one `method` (`GET` or
`HEAD`) and one `path` starting with `/`; SHOULD add `host`, `user-agent`,
`accept`. No body in v1.

**Response:** one HEADERS frame with `status` (MUST) and `content-type`,
`content-length`, `server`, `date` (SHOULD), then DATA frames; the last frame
has END_STREAM. No body (HEAD, empty file) → END_STREAM on the HEADERS frame.

The server maps `path` to a file under its root; a directory serves its
`index.html`; anything resolving outside the root MUST NOT be served.

| Status | When |
|---|---|
| 200 | Found — body is the file |
| 400 | Malformed: bad or reserved header encoding, missing/duplicate `method` or `path`, `path` without leading `/`, request without END_STREAM, HEADERS on stream 0, DATA from a client, payload over 16 384 |
| 404 | Not found, or outside the root |
| 405 | Method other than GET/HEAD |

Errors carry a short `text/plain` body. **A 400 goes on the stream the bad
frame named (0 if it named 0) and the connection stays open** — Length always
says where the next frame starts. Only a close mid-frame is unrecoverable.

## 6. Room for version 2

Unknown types are skipped (§3.1), unknown flag bits ignored (§2), the static
table can grow into 11–255, and the 16 KiB limit can rise without changing
the header. Every byte of a real exchange: [HEXDUMP.md](HEXDUMP.md).
