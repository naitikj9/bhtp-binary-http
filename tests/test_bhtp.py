"""End-to-end tests: start a real bserve, talk to it over real sockets.

Run with:  python -m unittest discover tests
"""

import os
import socket
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WWW = os.path.join(ROOT, "www")
sys.path.insert(0, ROOT)
import bhtp  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def raw_frame(ftype, flags, stream, payload):
    """Hand-packed frame that does NOT use bhtp.py -- straight from SPEC.md."""
    return (len(payload).to_bytes(3, "big") + bytes([ftype, flags])
            + stream.to_bytes(3, "big") + payload)


def raw_get(path, stream=1):
    # method=GET (index 1), path (index 2), straight from the static table
    p = path.encode()
    block = b"\x01\x00\x03GET" + b"\x02" + len(p).to_bytes(2, "big") + p
    return raw_frame(0x01, 0x01, stream, block)


class BhtpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "bserve"), WWW, str(cls.port)],
            stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port)).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait()

    def connect(self):
        s = socket.create_connection(("127.0.0.1", self.port))
        s.settimeout(5)
        self.addCleanup(s.close)
        return s

    def read_response(self, sock):
        """Collect one response -> (stream, headers dict, body)."""
        headers, body = None, b""
        while True:
            f = bhtp.read_frame(sock)
            self.assertIsNotNone(f, "server closed the connection")
            if f.type == bhtp.HEADERS:
                headers = dict(bhtp.decode_headers(f.payload))
            elif f.type == bhtp.DATA:
                body += f.payload
            if f.flags & bhtp.END_STREAM:
                return f.stream, headers, body

    def bcurl(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "bcurl")] + list(args),
            capture_output=True, timeout=10)

    # ------------------------------------------------------------- codec

    def test_header_roundtrip(self):
        fields = [("method", "GET"), ("path", "/x"), ("x-custom", "hello"),
                  ("date", "Wed, 07 Oct 2026 00:00:00 GMT")]
        self.assertEqual(bhtp.decode_headers(bhtp.encode_headers(fields)), fields)

    def test_static_name_is_one_byte(self):
        self.assertEqual(bhtp.encode_headers([("method", "GET")]), b"\x01\x00\x03GET")

    def test_literal_name(self):
        self.assertEqual(bhtp.encode_headers([("etag", "1")]),
                         b"\x00\x04etag\x00\x011")

    def test_reserved_index_is_malformed(self):
        with self.assertRaises(bhtp.ProtocolError):
            bhtp.decode_headers(b"\x0b\x00\x00")

    def test_truncated_value_is_malformed(self):
        with self.assertRaises(bhtp.ProtocolError):
            bhtp.decode_headers(b"\x01\x00\x09GET")

    # ------------------------------------------------------------ server

    def test_get_200(self):
        s = self.connect()
        s.sendall(raw_get("/index.html"))
        stream, h, body = self.read_response(s)
        self.assertEqual((stream, h["status"]), (1, "200"))
        with open(os.path.join(WWW, "index.html"), "rb") as f:
            self.assertEqual(body, f.read())
        self.assertEqual(int(h["content-length"]), len(body))

    def test_directory_serves_index(self):
        s = self.connect()
        s.sendall(raw_get("/"))
        self.assertEqual(self.read_response(s)[1]["status"], "200")

    def test_404(self):
        s = self.connect()
        s.sendall(raw_get("/missing.html"))
        self.assertEqual(self.read_response(s)[1]["status"], "404")

    def test_traversal_is_404(self):
        s = self.connect()
        s.sendall(raw_get("/../bhtp.py"))
        self.assertEqual(self.read_response(s)[1]["status"], "404")

    def test_malformed_header_block_400_and_connection_survives(self):
        s = self.connect()
        s.sendall(raw_frame(0x01, 0x01, 1, b"\xff\xff\xff"))
        self.assertEqual(self.read_response(s)[1]["status"], "400")
        s.sendall(raw_get("/index.html", stream=2))
        stream, h, _ = self.read_response(s)
        self.assertEqual((stream, h["status"]), (2, "200"))

    def test_missing_path_400(self):
        s = self.connect()
        s.sendall(raw_frame(0x01, 0x01, 1, b"\x01\x00\x03GET"))
        self.assertEqual(self.read_response(s)[1]["status"], "400")

    def test_stream_zero_400(self):
        s = self.connect()
        s.sendall(raw_get("/index.html", stream=0))
        stream, h, _ = self.read_response(s)
        self.assertEqual((stream, h["status"]), (0, "400"))

    def test_oversized_frame_400_and_skipped(self):
        s = self.connect()
        s.sendall(raw_frame(0x01, 0x01, 1, b"\x00" * (bhtp.MAX_FRAME + 1)))
        self.assertEqual(self.read_response(s)[1]["status"], "400")
        s.sendall(raw_get("/index.html", stream=3))
        self.assertEqual(self.read_response(s)[1]["status"], "200")

    def test_unknown_frame_type_is_skipped(self):
        s = self.connect()
        s.sendall(raw_frame(0x42, 0xff, 7, b"future stuff the server cannot know")
                  + raw_get("/index.html"))
        stream, h, _ = self.read_response(s)
        self.assertEqual((stream, h["status"]), (1, "200"))

    def test_many_requests_one_connection(self):
        s = self.connect()
        for i in range(1, 6):
            s.sendall(raw_get("/docs/notes.txt", stream=i))
            stream, h, body = self.read_response(s)
            self.assertEqual((stream, h["status"]), (i, "200"))

    def test_large_file_split_into_frames(self):
        s = self.connect()
        s.sendall(raw_get("/big.bin"))
        frames = []
        while True:
            f = bhtp.read_frame(s)
            frames.append(f)
            if f.flags & bhtp.END_STREAM:
                break
        data = [f for f in frames if f.type == bhtp.DATA]
        self.assertGreater(len(data), 1)
        self.assertTrue(all(len(f.payload) <= bhtp.MAX_FRAME for f in data))
        with open(os.path.join(WWW, "big.bin"), "rb") as fh:
            self.assertEqual(b"".join(f.payload for f in data), fh.read())

    # ------------------------------------------------------------ client

    def test_bcurl_body_to_stdout(self):
        r = self.bcurl("localhost:%d/index.html" % self.port)
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(WWW, "index.html"), "rb") as f:
            self.assertEqual(r.stdout, f.read())

    def test_bcurl_exit_nonzero_on_404(self):
        r = self.bcurl("localhost:%d/nope" % self.port)
        self.assertEqual(r.returncode, 4)

    def test_bcurl_verbose_hexdumps(self):
        r = self.bcurl("-v", "localhost:%d/index.html" % self.port)
        self.assertIn(b"> HEADERS", r.stderr)
        self.assertIn(b"< DATA", r.stderr)
        self.assertIn(b"0000  00 00", r.stderr)

    def test_bcurl_refuses_second_connection(self):
        r = self.bcurl("localhost:%d/index.html" % self.port, "otherhost:1/x")
        self.assertEqual(r.returncode, 2)

    def test_bcurl_probe_unknown_frame(self):
        r = self.bcurl("--probe", "localhost:%d/index.html" % self.port)
        self.assertEqual(r.returncode, 0)

    def test_bcurl_against_hand_written_server(self):
        """bcurl must follow the spec, not just bserve. A fake server built
        from raw bytes sends an unknown frame, a literal header and a body
        split over two DATA frames, then answers a second request with 404."""
        ls = socket.socket()
        ls.bind(("127.0.0.1", 0))
        ls.listen(1)
        self.addCleanup(ls.close)
        port = ls.getsockname()[1]
        p = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "bcurl"), "localhost:%d/a" % port, "/b"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        c, _ = ls.accept()
        c.settimeout(5)

        def recv_n(n):
            buf = b""
            while len(buf) < n:
                chunk = c.recv(n - len(buf))
                if not chunk:
                    raise EOFError
                buf += chunk
            return buf

        def read_raw():
            hdr = recv_n(8)
            return hdr, recv_n(int.from_bytes(hdr[0:3], "big"))

        hdr, payload = read_raw()                       # request 1
        self.assertEqual(hdr[3:], b"\x01\x01\x00\x00\x01")
        self.assertIn(b"\x02\x00\x02/a", payload)       # path = /a
        c.sendall(raw_frame(0x55, 0, 0, b"v2 stuff")    # unknown type: skip
                  + raw_frame(0x01, 0, 1, b"\x03\x00\x03200"
                              + b"\x00\x06x-test\x00\x01y")
                  + raw_frame(0x02, 0, 1, b"hel")
                  + raw_frame(0x02, 0x01, 1, b"lo"))

        hdr, payload = read_raw()                       # request 2, same socket
        self.assertEqual(hdr[3:], b"\x01\x01\x00\x00\x02")
        self.assertIn(b"\x02\x00\x02/b", payload)
        c.sendall(raw_frame(0x01, 0x01, 2, b"\x03\x00\x03404"))

        out, err = p.communicate(timeout=5)
        c.close()
        self.assertEqual(out, b"hello")
        self.assertEqual(p.returncode, 4)


if __name__ == "__main__":
    unittest.main()
