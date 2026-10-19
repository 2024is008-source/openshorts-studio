"""Windows lock compatibility primitive; independent of the retired browser shell."""
import os

class InstanceLock:
    def __init__(self, path):
        self.file = open(path, 'a+b')
        if os.fstat(self.file.fileno()).st_size == 0:
            self.file.write(b'1')
            self.file.flush()
        self.file.seek(0)

    def acquire(self):
        import msvcrt
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def close(self):
        self.file.close()
