"""PyInstaller entry and source launcher. Worker modes never import Qt."""
import multiprocessing
import os
import sys


if __name__ == '__main__':
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] in ('--backend', '--worker', '--native-backend'):
        if os.environ.get('OPENSHORTS_DESKTOP') != '1':
            raise SystemExit('Desktop worker requires a managed launch')
        # A noconsole executable still needs valid streams for print-heavy engines.
        for name in ('stdout', 'stderr'):
            if getattr(sys, name) is None:
                setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
        if sys.argv[1] == '--native-backend':
            from desktop.native_api import main
            main()
        elif sys.argv[1] == '--backend':
            from desktop.backend import serve
            serve()
        else:
            from desktop.backend import worker
            worker(sys.argv[2], sys.argv[3:])
    else:
        raise SystemExit('Start the native Windows application using start_wpf.vbs or OpenShorts Latest.lnk.')
