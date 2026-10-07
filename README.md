# BHTP/1 — HTTP, in binary

A binary framing of HTTP GET over one TCP connection: a server (`bserve`),
a client (`bcurl`), and the spec that is the only thing they share.

| File | What |
|---|---|
| [SPEC.md](SPEC.md) | **The spec** — two pages, enough for a stranger to implement either side |
| [HEXDUMP.md](HEXDUMP.md) | **Annotated hexdump** of one complete request and response, byte by byte |
| [bserve](bserve) | Track 1 — the server |
| [bcurl](bcurl) | Track 2 — the client |
| [bhtp.py](bhtp.py) | Framing + header codec shared by both |
| [tests/](tests/test_bhtp.py) | End-to-end tests over real sockets (22 tests) |
| [www/](www) | Sample site to serve |

Needs only Python 3.8+ (standard library, no installs).

## Run it

```bash
./bserve ./www 9000                 # terminal 1
./bcurl -v localhost:9000/index.html   # terminal 2
```

On Windows use `python bserve ./www 9000` and `python bcurl ...`.

### bserve

```
./bserve ROOT PORT [-v]
```
Accepts TCP connections (one thread each), reads binary request frames, maps
the path to a file under ROOT (directories → `index.html`, `../` escapes →
404), replies with status, headers and the bytes. 404 if missing, 400 if the
frame is malformed, and **keeps the connection open** after every response —
including after errors. Unknown frame types are skipped. `-v` hexdumps every frame.

### bcurl

```
./bcurl [-v] [-I] [--probe] host:port/path [/more /paths ...]
```
Builds the binary request frame, writes the response body to stdout, `-v`
hexdumps every frame (sent `>` and received `<`) to stderr. Several paths
are fetched **over the same single connection**; a URL on a different
host:port is refused rather than opening a second one. `-I` sends HEAD,
`--probe` first sends an unknown frame type to check the server skips it.

Exit status: `0` ok · `4` a 4xx · `5` a 5xx · `1` connection/protocol error · `2` usage.

```bash
./bcurl localhost:9000/index.html /docs/notes.txt /missing; echo $?   # -> 4
```

## Tests

```bash
python -m unittest discover tests
```

The tests start a real `bserve` and talk to it with **hand-packed bytes
written straight from SPEC.md** (not through `bhtp.py`), so they check the
spec, not just that our client agrees with our server: 200/404/400/405,
traversal, stream 0, oversized frames, unknown frame types, five requests on
one connection, a 51 KB file split across DATA frames, bcurl's exit codes, and bcurl against a hand-written fake server (unknown frame, literal header, split body, two requests on one socket).

## Design in one paragraph

8-byte frame header: **Length 24 · Type 8 · Flags 8 · Stream 24** — HTTP/2's
layout with the stream ID cut from 31 to 24 bits so the header is one 64-bit
word. Headers: the ten names we actually send are one byte each (static
table, indexes 1–10), anything else is a length-prefixed literal (`0x00`,
len, name). Values are 16-bit length-prefixed. And the rule that leaves room
for version 2: **a receiver that meets a frame type it does not know MUST
skip it cleanly.** Full reasoning in [SPEC.md](SPEC.md).
