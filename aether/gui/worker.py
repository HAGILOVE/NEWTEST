"""
Run an analysis in its own, low-priority process.

Why a process and not a thread
------------------------------
A FEM solve keeps every core busy for minutes. Inside the GUI process it
competes with the HTTP server, the poller that feeds the progress panel and
-- on the same machine -- the browser that draws the 3-D view, so the whole
workspace stalls and the PC becomes sluggish. A separate process fixes that
in three ways:

* it runs at *below-normal* priority and with a limited number of BLAS /
  PARDISO threads, so the desktop (and the browser) always get CPU;
* the GUI process only waits on a queue, so it never competes for the GIL;
* it can be *killed*. A direct factorisation cannot be interrupted from
  Python, so a cooperative flag alone leaves the user waiting; "Abort"
  terminates the process and the memory comes back immediately.

The child is a plain ``python -c`` subprocess (not ``multiprocessing``), so it
never re-imports the program that started the GUI -- a user script without an
``if __name__ == "__main__"`` guard cannot start the application twice. It
talks to its parent over a loopback socket guarded by a random token.
Results (partial snapshots and the final solution) are pickled to files in a
private temp directory and only the *path* travels over the socket, so a
large field set can never fill a pipe and deadlock the pair. When the socket
closes -- the GUI died -- the child exits by itself.
"""
from __future__ import annotations

import logging
import os
import pickle
import queue
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Optional

#: environment override: "process" (default) or "thread"
MODE_ENV = "AETHER_SOLVER_MODE"
#: environment override for the number of solver threads
THREADS_ENV = "AETHER_SOLVER_THREADS"

#: minimum seconds between two partial snapshots sent to the GUI
PARTIAL_INTERVAL = 1.5


# ----------------------------------------------------------------------
def default_threads(cpus: Optional[int] = None, override: int = 0) -> int:
    """
    How many threads the solver may use.

    All but one or two cores: PARDISO/MKL spin-wait on every core they own,
    so leaving none free is what makes the rest of the machine crawl.
    """
    if override and int(override) > 0:
        return min(int(override), 256)
    env = os.environ.get(THREADS_ENV, "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    n = cpus or os.cpu_count() or 2
    free = 2 if n >= 8 else 1
    return max(1, min(n - free, 16))


def solver_mode() -> str:
    m = os.environ.get(MODE_ENV, "process").strip().lower()
    return "thread" if m == "thread" else "process"


def thread_env(threads: int) -> dict:
    """Environment that keeps native libraries from over-subscribing."""
    t = str(int(threads))
    return {
        "OMP_NUM_THREADS": t, "MKL_NUM_THREADS": t,
        "OPENBLAS_NUM_THREADS": t, "NUMEXPR_NUM_THREADS": t,
        "VECLIB_MAXIMUM_THREADS": t, "BLIS_NUM_THREADS": t,
        # do not busy-wait at barriers: idle workers sleep instead of
        # burning the cores the desktop needs
        "KMP_BLOCKTIME": "0", "OMP_WAIT_POLICY": "PASSIVE",
        "MKL_DYNAMIC": "TRUE",
    }


def limit_native_threads(threads: int) -> None:
    """Best effort: cap MKL/PARDISO/BLAS in the *running* interpreter (the
    environment variables only work for a library not yet loaded)."""
    try:
        from threadpoolctl import threadpool_limits
        threadpool_limits(limits=int(threads))
    except Exception:
        pass
    try:
        import ctypes
        import pypardiso
        lib = pypardiso.ps.libmkl           # the MKL runtime PARDISO runs in
        lib.MKL_Set_Num_Threads(ctypes.c_int(int(threads)))
    except Exception:
        pass


def lower_priority() -> str:
    """Put the *current* process at below-normal priority. Returns a note."""
    try:
        if os.name == "nt":
            import ctypes
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            h = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.kernel32.SetPriorityClass(
                h, BELOW_NORMAL_PRIORITY_CLASS)
            return "below-normal priority" if ok else "priority unchanged"
        os.nice(8)
        return "nice +8"
    except Exception as exc:                   # pragma: no cover - best effort
        return f"priority unchanged ({exc})"


# ----------------------------------------------------------------------
# wire format: 4-byte big-endian length + pickled tuple
# ----------------------------------------------------------------------
def _send(sock, lock, obj) -> None:
    data = pickle.dumps(obj, protocol=4)
    with lock:
        sock.sendall(struct.pack(">I", len(data)) + data)


def _recv_exact(sock, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return bytes(buf)


def _recv(sock):
    (n,) = struct.unpack(">I", _recv_exact(sock, 4))
    return pickle.loads(_recv_exact(sock, n))


# ----------------------------------------------------------------------
# child side
# ----------------------------------------------------------------------
class _SocketLogHandler(logging.Handler):
    """Ship the solver's log records to the GUI process."""

    def __init__(self, send):
        super().__init__(logging.INFO)
        self.send = send

    def emit(self, record):
        try:
            self.send(("log", record.levelno, record.name, record.getMessage()))
        except Exception:
            pass


def _dump(obj, tmpdir: str, tag: str, seq: int) -> str:
    path = os.path.join(tmpdir, f"{tag}{seq}.pkl")
    with open(path + ".tmp", "wb") as fh:
        pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(path + ".tmp", path)           # the parent never sees half a file
    return path


def child_main() -> None:
    """Entry point of the solver process: ``sys.argv[1:] = port token tmp n``."""
    port, token, tmpdir, threads = (int(sys.argv[1]), sys.argv[2],
                                    sys.argv[3], int(sys.argv[4]))
    sock = socket.create_connection(("127.0.0.1", port), timeout=30)
    sock.settimeout(None)
    sock.sendall(token.encode("ascii"))
    lock = threading.Lock()

    def send(obj):
        _send(sock, lock, obj)

    cancel = threading.Event()
    jobs: "queue.Queue" = queue.Queue()

    def listen():                              # parent -> child commands
        try:
            while True:
                msg = _recv(sock)
                if msg and msg[0] == "stop":
                    cancel.set()
                else:
                    jobs.put(msg)
        except Exception:
            os._exit(3)                        # the GUI is gone: do not linger
    threading.Thread(target=listen, daemon=True).start()

    try:
        note = lower_priority()
        from ..core import logging as alog
        alog.configure(logging.INFO)
        root = logging.getLogger("aether")
        for h in list(root.handlers):         # the GUI prints the lines
            root.removeHandler(h)
        root.addHandler(_SocketLogHandler(send))
        root.propagate = False
        root.setLevel(logging.INFO)
        root.info("solver process %d started (%s, %d thread%s)",
                  os.getpid(), note, threads, "" if threads == 1 else "s")
        limit_native_threads(threads)          # honour the limit in loaded libs

        send(("ready",))
        job = jobs.get()                       # ("job", blob, setup, kw)
        design = pickle.loads(job[1])
        state = {"seq": 0, "last": 0.0, "pending": None}

        def flush():
            part = state["pending"]
            if part is None:
                return
            state["pending"] = None
            state["seq"] += 1
            state["last"] = time.time()
            send(("partial", _dump(part, tmpdir, "part", state["seq"])))

        def on_partial(part):
            state["pending"] = part
            if time.time() - state["last"] >= PARTIAL_INTERVAL:
                flush()

        from ..fem.control import SolveCancelled
        try:
            sol = design.solve(setup=job[2] or None, cancel=cancel,
                               on_partial=on_partial, **job[3])
        except SolveCancelled as exc:
            flush()                            # keep what was computed
            send(("cancelled", str(exc)))
            return
        except BaseException as exc:
            flush()
            import traceback
            send(("error", f"{type(exc).__name__}: {exc}",
                  traceback.format_exc()))
            return
        state["pending"] = None
        send(("done", _dump(sol, tmpdir, "final", 0)))
    except BaseException as exc:               # pragma: no cover - last resort
        try:
            send(("error", f"solver process failed: {exc}", ""))
        except Exception:
            pass
    finally:
        try:
            sock.shutdown(socket.SHUT_WR)
        except Exception:
            pass


# ----------------------------------------------------------------------
# parent side
# ----------------------------------------------------------------------
_BOOT = ("import sys; sys.path.insert(0, {root!r}); "
         "from aether.gui.worker import child_main; child_main()")


class SolverProcess:
    """
    Supervises one solver subprocess.

    ``stop()``   asks the solver to finish the current step and return what it
                 has (cooperative);
    ``abort()``  terminates the process at once.

    Callbacks run on the supervising thread:
    ``on_log(level, name, message)``, ``on_partial(solution)``.
    """

    def __init__(self, design, setup_name: str, kw: dict,
                 on_log: Callable, on_partial: Callable,
                 threads: Optional[int] = None):
        self.design = design
        self.setup_name = setup_name
        self.kw = dict(kw)
        self.on_log = on_log
        self.on_partial = on_partial
        self.threads = threads or default_threads()
        self.pid = 0
        self._proc = None
        self._sock = None
        self._lock = threading.Lock()
        self._inbox: "queue.Queue" = queue.Queue()
        self._tmp = ""
        self._stop = False
        self._aborted = False

    # -- control ---------------------------------------------------------
    def stop(self) -> None:
        self._stop = True
        if self._sock is not None:
            try:
                _send(self._sock, self._lock, ("stop",))
            except OSError:
                pass

    def abort(self) -> None:
        self._aborted = True
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.kill()           # TerminateProcess on Windows, SIGKILL elsewhere
            except OSError:
                pass

    @property
    def aborted(self) -> bool:
        return self._aborted

    # -- run ---------------------------------------------------------------
    def run(self):
        """
        Block until the solver ends.

        Returns ``(status, solution, message)`` with status one of
        ``"done"``, ``"cancelled"``, ``"aborted"``, ``"error"``; *solution*
        is the final one, or the last partial snapshot, or ``None``.
        """
        blob = pickle.dumps(self.design, protocol=pickle.HIGHEST_PROTOCOL)
        self._tmp = tempfile.mkdtemp(prefix="aether-solve-")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        srv.settimeout(0.25)
        token = secrets.token_hex(16)
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        env = dict(os.environ)
        env.update(thread_env(self.threads))
        env["PYTHONIOENCODING"] = "utf-8"
        flags = 0
        if os.name == "nt":
            flags = 0x00004000 | 0x08000000     # below-normal, no console window
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-c", _BOOT.format(root=root),
                 str(srv.getsockname()[1]), token, self._tmp, str(self.threads)],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags)
        except Exception:
            srv.close()
            shutil.rmtree(self._tmp, ignore_errors=True)
            raise
        self.pid = self._proc.pid
        try:
            self._sock = self._accept(srv, token)
            if self._sock is None:
                return self._ended([], None)
            threading.Thread(target=self._reader, daemon=True).start()
            if self._stop:
                self.stop()
            self._send_job(blob)
            return self._supervise()
        finally:
            try:
                srv.close()
            except OSError:
                pass
            self._cleanup()

    def _accept(self, srv, token):
        deadline = time.time() + 60.0
        while time.time() < deadline:
            if self._aborted or self._proc.poll() is not None:
                return None
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            conn.settimeout(5.0)
            try:
                got = _recv_exact(conn, len(token))
            except (OSError, EOFError):
                conn.close()
                continue
            if secrets.compare_digest(got, token.encode("ascii")):
                conn.settimeout(None)
                return conn
            conn.close()                       # someone else on loopback
        return None

    def _send_job(self, blob: bytes) -> None:
        _send(self._sock, self._lock, ("job", blob, self.setup_name, self.kw))

    def _reader(self) -> None:
        try:
            while True:
                self._inbox.put(_recv(self._sock))
        except Exception:
            self._inbox.put(("eof",))

    def _load(self, path: str):
        with open(path, "rb") as fh:
            obj = pickle.load(fh)
        try:
            os.remove(path)
        except OSError:
            pass
        return obj

    def _ended(self, logs, last):
        if self._aborted:
            return "aborted", last, "aborted by the user"
        code = self._proc.poll() if self._proc else None
        return ("error", last,
                "the solver process ended unexpectedly"
                + (f" (exit code {code})" if code is not None else "")
                + "; it may have run out of memory")

    def _supervise(self):
        last = None            # most recent partial solution
        while True:
            try:
                msg = self._inbox.get(timeout=0.25)
            except queue.Empty:
                if self._proc.poll() is not None and self._inbox.empty():
                    time.sleep(0.3)            # let the reader deliver the tail
                    if self._inbox.empty():
                        return self._ended([], last)
                continue
            kind = msg[0]
            if kind == "log":
                self.on_log(msg[1], msg[2], msg[3])
            elif kind == "partial":
                try:
                    last = self._load(msg[1])
                    self.on_partial(last)
                except Exception as exc:
                    self.on_log(logging.WARNING, "aether.gui",
                                f"could not read a partial result: {exc}")
            elif kind == "done":
                try:
                    return "done", self._load(msg[1]), ""
                except Exception as exc:
                    return "error", last, f"could not read the result: {exc}"
            elif kind == "cancelled":
                return "cancelled", last, msg[1]
            elif kind == "error":
                return "error", last, msg[1]
            elif kind == "eof":
                time.sleep(0.2)
                if self._inbox.empty():
                    return self._ended([], last)

    def _cleanup(self) -> None:
        p = self._proc
        if p is not None:
            try:
                if p.poll() is None:
                    try:
                        p.wait(1.5)            # it exits by itself after a result
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait(3.0)
            except Exception:
                pass
        try:
            if self._sock is not None:
                self._sock.close()
        except OSError:
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)


def can_spawn() -> bool:
    """True when the isolated solver process may be used."""
    return solver_mode() == "process" and bool(sys.executable)
