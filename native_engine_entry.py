"""Frozen WPF engine: no GUI/browser imports; shares existing worker dispatch."""
import multiprocessing
import os
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if os.environ.get('OPENSHORTS_DESKTOP') != '1':
        raise SystemExit('A managed desktop launch is required')
    for name in ('stdout','stderr'):
        if getattr(sys,name) is None:
            setattr(sys,name,open(os.devnull,'w',encoding='utf-8'))
    if sys.argv[1:] == ['--native-backend']:
        from desktop.native_api import main
        main()
    elif len(sys.argv)>2 and sys.argv[1]=='--worker':
        from desktop.backend import worker
        worker(sys.argv[2],sys.argv[3:])
    else:
        raise SystemExit('Unsupported engine command')
