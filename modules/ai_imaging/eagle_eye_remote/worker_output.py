"""Bounded private model output; never let a full disk block a child's pipe."""
from pathlib import Path
import threading

from .admission import CompletionUncertain


class WorkerOutput:
    def __init__(self, path, *, max_bytes=1024 * 1024):
        if type(max_bytes) is not int or not 1024 <= max_bytes <= 16 * 1024 * 1024:
            raise ValueError('Worker log budget must be between 1 KiB and 16 MiB.')
        self.path, self.max_bytes = Path(path), max_bytes
        self.failed = threading.Event()
        self.thread = None

    def start(self, stream):
        if self.thread is not None:
            raise RuntimeError('Worker output already has an owner.')
        self.thread = threading.Thread(target=self._drain, args=(stream,),
                                       name='EagleEyeWorkerOutput', daemon=True)
        self.thread.start()

    def _drain(self, stream):
        sink = None
        try:
            try:
                sink = self.path.open('wb')
            except OSError:
                self.failed.set()
            while block := stream.read(min(65536, self.max_bytes)):
                if sink is not None:
                    try:
                        if sink.tell() + len(block) > self.max_bytes:
                            sink.seek(0)
                            sink.truncate()
                        sink.write(block)
                        sink.flush()
                    except OSError:
                        self.failed.set()
                        sink.close()
                        sink = None
        except (OSError, ValueError):
            self.failed.set()
        finally:
            if sink is not None:
                try:
                    sink.close()
                except OSError:
                    self.failed.set()

    def finish(self):
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise CompletionUncertain('Owned worker output cleanup did not complete.')
        if self.failed.is_set():
            raise OSError('Worker output could not be retained safely.')
