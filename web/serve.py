#!/usr/bin/env python3
"""Static dev server that supports HTTP range requests.

`python -m http.server` answers every request with 200 and the whole body. That
is fine for HTML, but PMTiles is *built* on range requests — without them the
browser pulls the entire archive for each tile lookup, so the map appears to
hang on a file that loads instantly in production.

GitHub Pages does serve ranges (verified: 206 Partial Content), so this only
exists to make local development behave like the deployed site.
"""

from __future__ import annotations

import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeHandler(SimpleHTTPRequestHandler):
    def send_head(self):  # noqa: C901 - mirrors the stdlib method it replaces
        header = self.headers.get("Range")
        if not header:
            return super().send_head()

        match = _RANGE.fullmatch(header.strip())
        if not match:
            return super().send_head()

        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()

        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        size = os.fstat(f.fileno()).st_size
        first, last = match.group(1), match.group(2)

        if first:
            start = int(first)
            end = int(last) if last else size - 1
        else:  # suffix form: bytes=-500
            if not last:
                f.close()
                self.send_error(400, "Invalid range")
                return None
            start = max(0, size - int(last))
            end = size - 1

        if start >= size or start > end:
            f.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        end = min(end, size - 1)
        f.seek(start)

        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return _Slice(f, end - start + 1)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _Slice:
    """File wrapper that stops after `remaining` bytes, for copyfile()."""

    def __init__(self, f, remaining: int):
        self._f = f
        self._remaining = remaining

    def read(self, n: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        if n < 0 or n > self._remaining:
            n = self._remaining
        data = self._f.read(n)
        self._remaining -= len(data)
        return data

    def close(self) -> None:
        self._f.close()


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    root = os.path.dirname(os.path.abspath(__file__))
    handler = partial(RangeHandler, directory=root)
    print(f"serving {root} at http://localhost:{port}  (range requests enabled)")
    ThreadingHTTPServer(("", port), handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
