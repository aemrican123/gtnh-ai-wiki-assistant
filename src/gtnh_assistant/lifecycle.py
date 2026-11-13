"""Shut the app down once nobody is using it, so closing the app window really closes the app.

The browser sends a beacon to ``/api/closing`` when the window closes (or reloads). If no other request
arrives within ``close_grace`` seconds, the app is idle. As a fallback, ``idle_timeout`` seconds without
any request also counts (an open window polls the status every few seconds, and browsers throttle hidden
windows to about one timer per minute). Nothing shuts down while a collection/index job or an answer runs.
"""

import threading
import time


class Lifecycle:
    def __init__(
        self, on_idle, busy=lambda: False, close_grace=15.0, idle_timeout=300.0, interval=2.0, clock=None
    ):
        self.on_idle = on_idle
        self.busy = busy
        self.close_grace = close_grace
        self.idle_timeout = idle_timeout
        self.interval = interval
        self.clock = clock or time.monotonic
        self.last_seen = self.clock()
        self.closing_at = None
        self.streams = 0
        self.fired = False
        self.mutex = threading.Lock()
        self.thread = None

    def seen(self):
        with self.mutex:
            self.last_seen = self.clock()

    def closing(self):
        with self.mutex:
            self.closing_at = self.clock()

    def stream_started(self):
        with self.mutex:
            self.streams += 1

    def stream_finished(self):
        with self.mutex:
            self.streams = max(0, self.streams - 1)

    def idle(self):
        """True when the app should shut down now."""
        with self.mutex:
            if self.fired or self.streams:
                return False
            now = self.clock()
            closed = (
                self.closing_at is not None
                and self.last_seen <= self.closing_at
                and now - self.closing_at >= self.close_grace
            )
            silent = now - self.last_seen >= self.idle_timeout
        return (closed or silent) and not self.busy()

    def check(self):
        if self.idle():
            self.fired = True
            self.on_idle()
            return True
        return False

    def start(self):
        def watch():
            while not self.fired:
                time.sleep(self.interval)
                self.check()

        self.thread = threading.Thread(target=watch, name="gtnh-idle-watch", daemon=True)
        self.thread.start()
        return self
