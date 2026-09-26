"""OS-released exclusive ownership of a durable server job directory."""
import os


class DirectoryLease:
    def __init__(self, root):
        self.stream = (root / '.server.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(self.stream.fileno()).st_size == 0:
                    self.stream.write(b'\0')
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError('The server job directory is already owned by another service.') from None

    def close(self):
        if not self.stream.closed:
            # Closing the handle releases the lock, including after process death.
            self.stream.close()
