from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from filelock import FileLock, Timeout

from .scrape import crawl


def writer_busy(directory):
    lock = FileLock(str(directory / "writer.lock"), timeout=0)
    try:
        with lock:
            return False
    except Timeout:
        return True


class Jobs:
    """One local writer, durable crawl checkpoints, no UI calls from workers."""

    def __init__(self, store, settings, index_factory):
        self.store, self.settings = store, settings
        self.index_factory = index_factory
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gtnh-ingest")
        self.stop = Event()
        self.future = None
        self.mutex = Lock()
        self.message = "Idle"
        self.result = None
        self.error = None

    def progress(self, message):
        self.message = message

    @property
    def running(self):
        return self.future is not None and not self.future.done()

    def start(self, kind, limit=None):
        with self.mutex:
            if self.running:
                return False
            self.stop.clear()
            self.result, self.error = None, None
            self.message = "Starting"
            self.future = self.executor.submit(self._run, kind, limit)
            return True

    def _run(self, kind, limit):
        try:
            with FileLock(str(self.settings.data_dir / "writer.lock"), timeout=0):
                if kind in {"scrape", "update"}:
                    self.result = crawl(
                        self.store,
                        self.settings,
                        limit=limit,
                        update=kind == "update",
                        stop=self.stop,
                        progress=self.progress,
                    )
                if not self.stop.is_set():
                    self.result = (self.result or {}) | self.index_factory().sync(
                        stop=self.stop, progress=self.progress, rebuild=kind == "rebuild"
                    )
                self.message = "Cancelled; checkpoints saved" if self.stop.is_set() else "Finished"
        except InterruptedError:
            self.message = "Cancelled; checkpoints saved"
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.message = "Stopped with an error; checkpoints saved"
