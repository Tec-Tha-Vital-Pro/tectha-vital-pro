"""Background loop that runs all automations every N seconds."""
import sys
import threading
import traceback

from app import audit, automations, util

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()


def tick() -> dict | None:
    """Run one pass. Errors are printed and written to the audit log, never swallowed silently."""
    try:
        return automations.run_all(util.now())
    except Exception as e:  # noqa: BLE001 - loop must survive and report
        traceback.print_exc(file=sys.stderr)
        audit.log("automation", "automation_error", "scheduler", None, f"{type(e).__name__}: {e}")
        return None


def _loop(interval: int) -> None:
    while not _stop.is_set():
        tick()
        _stop.wait(interval)


def start(interval_seconds: int) -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, args=(interval_seconds,), name="tectha-scheduler", daemon=True)
        _thread.start()


def stop() -> None:
    global _thread
    with _lock:
        _stop.set()
        if _thread is not None:
            _thread.join(timeout=5)
        _thread = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
