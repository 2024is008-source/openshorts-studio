"""Explicit, restartable model preparation owned by the desktop process tree."""
import os
from pathlib import Path


def download():
    from desktop.model_provisioning import Provisioner
    from desktop.storage import Storage
    output=os.environ.get('OUTPUT_DIR')
    storage = Storage(local=Path(output).resolve().parent if output else None)
    status = storage.work / 'model-download-status'
    service=Provisioner(storage)
    try:
        # This compatibility worker is launched only by an explicit model action.
        service.start(acknowledged=True)
        if service.thread:service.thread.join()
        if not service.status()['available']:raise RuntimeError('Model preparation did not complete')
        status.write_text('complete', 'ascii')
    except Exception as error:
        status.write_text('failed:' + type(error).__name__, 'ascii')
        raise SystemExit(1)
    finally:service.close()


if __name__ == '__main__':
    download()
