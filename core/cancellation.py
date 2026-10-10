"""Interrupt local inference processes even while a HTTP call is blocked."""
from contextlib import contextmanager
import threading


@contextmanager
def interrupt_on_cancel(cancel, stop):
    done = threading.Event()

    def watch():
        while not done.wait(0.05):
            if cancel.is_set():
                stop()
                return

    thread = None
    if cancel is not None:
        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
    try:
        yield
    finally:
        done.set()
        if thread:
            thread.join(timeout=2)
