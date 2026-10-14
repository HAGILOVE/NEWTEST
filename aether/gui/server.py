"""
Local application server for Aether Desktop.

Deliberately built on nothing but the Python standard library: no Flask, no
Node, no build step. ``aether gui`` starts a threaded HTTP server bound to
loopback, opens the browser, and the workspace is live.

Security posture, since this endpoint can execute scripts against your model
exactly as HFSS's scripting console can:

* the socket binds to 127.0.0.1 only (never 0.0.0.0 unless asked explicitly),
* every API call must carry a random per-run token, which is baked into the
  page URL, so another site in your browser cannot drive it.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import secrets
import socket
import threading
import traceback
import weakref
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from ..core.logging import get_logger
from ..version import __version__
from .api import dispatch, state_json
from .state import Session

log = get_logger("gui.server")

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class _Handler(BaseHTTPRequestHandler):
    server_version = f"AetherDesktop/{__version__}"
    protocol_version = "HTTP/1.1"

    # -- plumbing ------------------------------------------------------
    def log_message(self, fmt, *args):           # silence stderr spam
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: bytes, ctype: str = "application/json",
              extra: Optional[dict] = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        try:
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The tab was closed, or the page navigated away, while the reply
            # was being written. That is the browser's business, not a fault
            # in the server, and it must not take the session down with it.
            log.debug("client went away before the reply was written")

    def _json(self, code: int, obj):
        self._send(code, json.dumps(_finite(obj)).encode("utf-8"))

    def _authorized(self, query) -> bool:
        tok = self.server.token                  # type: ignore[attr-defined]
        if not tok:
            return True
        given = (self.headers.get("X-Aether-Token")
                 or (query.get("token", [""])[0] if query else ""))
        return secrets.compare_digest(str(given), tok)

    # -- routes --------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path
        if path in ("/", "/index.html"):
            return self._serve_index()
        if path.startswith("/api/"):
            if not self._authorized(q):
                return self._json(403, {"error": "invalid token"})
            if path == "/api/state":
                return self._json(200, state_json(self.server.session))
            if path == "/api/messages":
                seq = int(q.get("since", ["0"])[0])
                s = self.server.session
                # Deliberately lock-free: this is the one request that must
                # keep answering while a long command (opening a project,
                # tessellating an assembly) holds the session lock, because it
                # is what the progress panel is reading.
                return self._json(200, {"messages": s.messages.since(seq),
                                        "seq": s.messages.seq,
                                        "job": s.job.to_json(),
                                        "task": s.progress.to_json()})
            if path == "/api/blob":
                return self._serve_blob(q.get("id", [""])[0])
            return self._json(404, {"error": "no such endpoint"})
        return self._serve_static(path)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path != "/api/rpc":
            return self._json(404, {"error": "no such endpoint"})
        if not self._authorized(q):
            return self._json(403, {"error": "invalid token"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as exc:
            return self._json(400, {"error": f"bad request: {exc}"})
        method = payload.get("method", "")
        params = payload.get("params") or {}
        s = self.server.session                  # type: ignore[attr-defined]
        try:
            result = dispatch(s, method, params)
            return self._json(200, {"ok": True, "result": result,
                                    "state": state_json(s)})
        except Exception as exc:
            s.messages.add(f"{method}: {exc}", "error", "command")
            log.debug("command %s failed:\n%s", method, traceback.format_exc())
            return self._json(200, {"ok": False, "error": str(exc),
                                    "state": state_json(s)})

    def _serve_blob(self, key: str):
        """
        One vertex array, as raw little-endian float32/int32.

        The viewport's buffers are float data; encoding them as JSON text
        roughly triples the bytes and then costs a full parse on the other
        side. They are content-addressed, so a blob is immutable and safe to
        cache in the browser for the life of the run.
        """
        from .api import BLOBS
        raw = BLOBS.get(key)
        if raw is None:
            return self._json(404, {"error": "expired buffer"})
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        try:
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            log.debug("client went away before the buffer was written")

    # -- static --------------------------------------------------------
    def _serve_index(self):
        p = os.path.join(STATIC, "index.html")
        with open(p, "rb") as fh:
            html = fh.read()
        tok = self.server.token or ""            # type: ignore[attr-defined]
        html = html.replace(b"__AETHER_TOKEN__", tok.encode())
        html = html.replace(b"__AETHER_VERSION__", __version__.encode())
        self._send(200, html, "text/html; charset=utf-8")

    def _serve_static(self, path: str):
        rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)


def _finite(o):
    """
    Make a payload strictly JSON-safe.

    Physical models legitimately contain infinities — a PEC has infinite
    conductivity — and ``Infinity`` is not valid JSON. Rather than let one such
    value abort a whole response (and with it the UI), non-finite numbers are
    sent as ``null`` and rendered as ∞ in the interface.
    """
    import math
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


class DesktopServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, session: Session, token: str):
        super().__init__(addr, _Handler)
        self.session = session
        self.token = token

    def shutdown(self):
        """
        Stop serving *and* release the port.

        ``ThreadingHTTPServer.shutdown`` only ends the serving loop; the
        listening socket stays open until the object is collected. That is why
        restarting the workspace on the same port could fail with "address
        already in use" after a clean stop.
        """
        super().shutdown()
        try:
            self.server_close()
        except Exception:                        # pragma: no cover
            pass


def _free_port(host: str, start: int = 8737) -> int:
    for p in range(start, start + 200):
        with socket.socket() as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free port in 8737-8937")


def serve(host: str = "127.0.0.1", port: int = 0, open_browser: bool = True,
          token: Optional[str] = None, project: Optional[str] = None,
          template: Optional[str] = None, block: bool = True):
    """Start the workspace; returns ``(server, url, session)``."""
    session = Session()
    if project:
        from .api import dispatch as _d
        _d(session, "project.open", {"path": project})
    elif template:
        from .api import dispatch as _d
        _d(session, "project.template", {"template": template})
    else:
        session.new_project()

    tok = token if token is not None else secrets.token_urlsafe(18)
    port = port or _free_port(host)
    # A closed tab must not be able to kill the process. Python ignores
    # SIGPIPE by default, but the CAD kernel resets signal handlers when it
    # initialises, so it is set again here -- after gmsh has had its say.
    try:
        import signal
        if hasattr(signal, "SIGPIPE"):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    except (ImportError, ValueError, OSError):               # pragma: no cover
        pass
    srv = DesktopServer((host, port), session, tok)
    # A weak reference on purpose: the server already owns the session, and a
    # strong link back would make the pair a reference cycle that keeps the
    # listening socket alive until the collector happens to run.
    session.server = weakref.proxy(srv)          # so File ▸ Exit can stop it
    url = f"http://{host}:{port}/?token={tok}" if tok else \
        f"http://{host}:{port}/"

    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log.info("Aether Desktop listening on %s", url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:                        # pragma: no cover
            pass
    if block:
        print(f"\n  Aether Desktop  v{__version__}")
        print(f"  {url}\n  (Ctrl-C to stop)\n")
        try:
            while True:
                t.join(1.0)
        except KeyboardInterrupt:
            print("shutting down")
            srv.shutdown()
    return srv, url, session


__all__ = ["serve", "DesktopServer"]
