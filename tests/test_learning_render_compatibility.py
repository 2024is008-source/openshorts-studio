"""Keep the final measured renderer progress when a fast child exits."""
import io
import threading
import time
import render_runtime


def test_progress_reader_drains_before_final_callback(monkeypatch):
    released=threading.Event()
    class Output(io.BytesIO):
        def readline(self,*args):
            assert released.wait(2)
            return super().readline(*args)
    class Child:
        pid=123
        returncode=0
        stdout=Output(b'frame=24\nout_time_us=1000000\nprogress=end\n')
        def poll(self):released.set();return 0
        def wait(self):return 0
    monkeypatch.setattr(render_runtime.subprocess,'Popen',lambda *args,**kwargs:Child())
    monkeypatch.setattr(render_runtime,'_rss',lambda *args:None)
    rows=[]
    result=render_runtime._execute(['ffmpeg','output.mp4'],None,time.monotonic()+5,rows.append,1,1)
    assert result['returncode']==0
    assert rows[-1]['time_seconds']==1 and rows[-1]['frame']==24
    assert rows[-1]['fraction']==.99  # Completion still waits for validation.
