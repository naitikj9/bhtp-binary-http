# Annotated hexdump — one complete request and response

Captured with:

```
./bserve ./www 9000
./bcurl -v localhost:9000/index.html
```

`>` = client → server, `<` = server → client. Every byte below is from the
real capture; every byte is accounted for. Field layout is in [SPEC.md](SPEC.md).

---

## Frame 1 `>` HEADERS — the request (8 + 55 = 63 bytes)

```
0000  00 00 37 01 01 00 00 01 01 00 03 47 45 54 02 00  |..7........GET..|
0010  0b 2f 69 6e 64 65 78 2e 68 74 6d 6c 04 00 0e 6c  |./index.html...l|
0020  6f 63 61 6c 68 6f 73 74 3a 39 30 30 30 05 00 09  |ocalhost:9000...|
0030  62 63 75 72 6c 2f 31 2e 30 06 00 03 2a 2f 2a     |bcurl/1.0...*/*|
```

| Offset | Bytes | Meaning |
|---|---|---|
| 00–02 | `00 00 37` | **Length** = 0x37 = 55 bytes of payload |
| 03 | `01` | **Type** = HEADERS |
| 04 | `01` | **Flags** = END_STREAM (a GET has no body; request complete) |
| 05–07 | `00 00 01` | **Stream ID** = 1 (first request on this connection) |
| 08 | `01` | static index 1 = `method` |
| 09–0a | `00 03` | value length = 3 |
| 0b–0d | `47 45 54` | `GET` |
| 0e | `02` | static index 2 = `path` |
| 0f–10 | `00 0b` | value length = 11 |
| 11–1b | `2f 69 … 6c` | `/index.html` |
| 1c | `04` | static index 4 = `host` |
| 1d–1e | `00 0e` | value length = 14 |
| 1f–2c | `6c 6f … 30` | `localhost:9000` |
| 2d | `05` | static index 5 = `user-agent` |
| 2e–2f | `00 09` | value length = 9 |
| 30–38 | `62 63 … 30` | `bcurl/1.0` |
| 39 | `06` | static index 6 = `accept` |
| 3a–3b | `00 03` | value length = 3 |
| 3c–3e | `2a 2f 2a` | `*/*` |

Payload check: 6 + 14 + 17 + 12 + 6 = **55** = Length. ✓
Same request as HTTP/1.1 text is ~86 bytes; here every header *name* costs one byte.

---

## Frame 2 `<` HEADERS — the response head (8 + 129 = 137 bytes)

```
0000  00 00 81 01 00 00 00 01 03 00 03 32 30 30 09 00  |...........200..|
0010  0a 62 73 65 72 76 65 2f 31 2e 30 0a 00 1d 57 65  |.bserve/1.0...We|
0020  64 2c 20 30 37 20 4f 63 74 20 32 30 32 36 20 30  |d, 07 Oct 2026 0|
0030  38 3a 33 33 3a 30 35 20 47 4d 54 07 00 18 74 65  |8:33:05 GMT...te|
0040  78 74 2f 68 74 6d 6c 3b 20 63 68 61 72 73 65 74  |xt/html; charset|
0050  3d 75 74 66 2d 38 08 00 02 36 33 00 0d 6c 61 73  |=utf-8...63..las|
0060  74 2d 6d 6f 64 69 66 69 65 64 00 1d 57 65 64 2c  |t-modified..Wed,|
0070  20 30 37 20 4f 63 74 20 32 30 32 36 20 30 38 3a  | 07 Oct 2026 08:|
0080  33 33 3a 30 32 20 47 4d 54                       |33:02 GMT|
```

| Offset | Bytes | Meaning |
|---|---|---|
| 00–02 | `00 00 81` | **Length** = 0x81 = 129 |
| 03 | `01` | **Type** = HEADERS |
| 04 | `00` | **Flags** = none — a body follows, so *not* END_STREAM |
| 05–07 | `00 00 01` | **Stream ID** = 1 — answers request 1 |
| 08 | `03` | static 3 = `status` |
| 09–0a | `00 03` | length 3 |
| 0b–0d | `32 30 30` | `200` (ASCII decimal) |
| 0e | `09` | static 9 = `server` |
| 0f–10 | `00 0a` | length 10 |
| 11–1a | `62 73 … 30` | `bserve/1.0` |
| 1b | `0a` | static 10 = `date` |
| 1c–1d | `00 1d` | length 29 |
| 1e–3a | `57 65 … 54` | `Wed, 07 Oct 2026 08:33:05 GMT` |
| 3b | `07` | static 7 = `content-type` |
| 3c–3d | `00 18` | length 24 |
| 3e–55 | `74 65 … 38` | `text/html; charset=utf-8` |
| 56 | `08` | static 8 = `content-length` |
| 57–58 | `00 02` | length 2 |
| 59–5a | `36 33` | `63` — the body will be 63 bytes |
| 5b | `00` | **literal name** follows (not in the static table) |
| 5c | `0d` | name length = 13 |
| 5d–69 | `6c 61 … 64` | `last-modified` |
| 6a–6b | `00 1d` | value length 29 |
| 6c–88 | `57 65 … 54` | `Wed, 07 Oct 2026 08:33:02 GMT` |

Payload check: 6 + 13 + 32 + 27 + 5 + 46 = **129** = Length. ✓
This one frame shows both header mechanisms: five static names (1 byte each)
and one literal (`00`, length, spelled-out name).

---

## Frame 3 `<` DATA — the body (8 + 63 = 71 bytes)

```
0000  00 00 3f 02 01 00 00 01 3c 21 64 6f 63 74 79 70  |..?.....<!doctyp|
0010  65 20 68 74 6d 6c 3e 0a 3c 74 69 74 6c 65 3e 42  |e html>.<title>B|
0020  48 54 50 3c 2f 74 69 74 6c 65 3e 0a 3c 68 31 3e  |HTP</title>.<h1>|
0030  48 65 6c 6c 6f 20 6f 76 65 72 20 42 48 54 50 2f  |Hello over BHTP/|
0040  31 3c 2f 68 31 3e 0a                             |1</h1>.|
```

| Offset | Bytes | Meaning |
|---|---|---|
| 00–02 | `00 00 3f` | **Length** = 63 — matches `content-length` |
| 03 | `02` | **Type** = DATA |
| 04 | `01` | **Flags** = END_STREAM — last frame of response 1 |
| 05–07 | `00 00 01` | **Stream ID** = 1 |
| 08–46 | `3c 21 … 0a` | the 63 bytes of `www/index.html`, verbatim → bcurl writes them to stdout |

A file larger than 16 384 bytes would arrive as several DATA frames, only the
last one carrying END_STREAM.

---

## Frame 4 `>` GOAWAY — client is finished (8 + 4 = 12 bytes)

```
0000  00 00 04 03 00 00 00 00 64 6f 6e 65              |........done|
```

| Offset | Bytes | Meaning |
|---|---|---|
| 00–02 | `00 00 04` | **Length** = 4 |
| 03 | `03` | **Type** = GOAWAY |
| 04 | `00` | **Flags** = none |
| 05–07 | `00 00 00` | **Stream ID** = 0 — about the connection, not a request |
| 08–0b | `64 6f 6e 65` | reason `done`; the client then closes the socket |

---

## Bonus: an unknown frame, skipped

`./bcurl --probe localhost:9000/` sends this before its request:

```
0000  00 00 16 7f 00 00 00 00 61 20 66 72 61 6d 65 20  |........a frame |
0010  66 72 6f 6d 20 76 65 72 73 69 6f 6e 20 32        |from version 2|
```

Type `7f` is not defined in v1. The server reads Length = 0x16 = 22 bytes,
throws them away, logs `skipped unknown frame type 0x7f (22 bytes)` and
answers the GET that follows normally — no reply, no error, no close.
