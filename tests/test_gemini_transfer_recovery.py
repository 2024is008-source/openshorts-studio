"""No-credit tests that exercise the actual failing media-transfer boundary."""
import httpx
import pytest
import story_director as sd
from test_gemini_chapter_compatibility import provider  # noqa: F401


def test_inline_write_timeout_switches_transport_instead_of_resending_bytes(provider,tmp_path):
    proxy=tmp_path/'short.mp4';proxy.write_bytes(b'local media')
    provider.answers[:]=[httpx.WriteTimeout(''),dict(chapter_summary='Observed.',moments=[])]
    value,_=sd._inspect(proxy,'Observe.','fixture-model')
    assert value['chapter_summary']=='Observed.'
    assert len(provider.calls)==2 and len(provider.uploaded)==len(provider.deleted)==1
    assert provider.calls[0]['contents'][0].inline_data.data==b'local media'
    assert getattr(provider.calls[1]['contents'][0],'name',None)=='files/local-fixture'


def test_chapter_sized_proxy_uses_uploaded_reference_from_first_attempt(provider,tmp_path):
    proxy=tmp_path/'chapter.mp4'
    # Exercise the uploaded-reference path above the current bounded inline size.
    with proxy.open('wb') as file:file.truncate(6*1024*1024)
    provider.answers[:]=[dict(chapter_summary='Observed.',moments=[])]
    sd._inspect(proxy,'Observe.','fixture-model')
    assert len(provider.uploaded)==1
    assert getattr(provider.calls[0]['contents'][0],'name',None)=='files/local-fixture'


def test_reference_generation_retry_reuses_one_upload(provider,tmp_path,monkeypatch):
    proxy=tmp_path/'chapter.mp4'
    with proxy.open('wb') as file:file.truncate(6*1024*1024)
    monkeypatch.setattr(sd.time,'sleep',lambda n:None)
    provider.answers[:]=[httpx.ReadTimeout(''),dict(chapter_summary='Observed.',moments=[])]
    sd._inspect(proxy,'Observe.','fixture-model')
    assert len(provider.uploaded)==1 and len(provider.calls)==2
    assert provider.calls[0]['contents'][0] is provider.calls[1]['contents'][0]


def test_proxy_reader_caps_sdk_chunks_and_preserves_exact_bytes(tmp_path):
    import io
    value=bytes(range(256))*40000
    proxy=tmp_path/'proxy.mp4';proxy.write_bytes(value)
    parts=[]
    with sd._ProxyReader(io.FileIO(proxy,'r')) as stream:
        assert stream.seekable()
        while part:=stream.read(8*1024*1024):
            assert len(part)<=8*1024*1024
            parts.append(part)
        assert stream.tell()==len(value)
    assert b''.join(parts)==value and len(parts)>1


def test_long_read_timeout_requests_section_recovery_without_three_whole_retries(provider):
    provider.answers[:]=[httpx.ReadTimeout('')]
    previous=getattr(sd._chapter_context,'media_duration',None)
    sd._chapter_context.media_duration=180
    try:
        with pytest.raises(sd.AnalysisMediaTimeout):sd._inspect('chapter.mp4','Observe.','fixture-model')
    finally:sd._chapter_context.media_duration=previous
    assert len(provider.calls)==1 and len(provider.uploaded)==len(provider.deleted)==1


def test_read_timeout_recovery_preserves_all_section_timestamps(tmp_path,monkeypatch):
    from test_chapter_section_recovery import result
    calls=[]
    monkeypatch.setattr(sd.subprocess,'run',lambda *a,**k:None)
    def inspect(*args):
        calls.append(sd._chapter_context.media_duration)
        if len(calls)==1:raise sd.AnalysisMediaTimeout('Long generation timeout')
        return sd._schema().model_validate(result()).model_dump(),None
    monkeypatch.setattr(sd,'_inspect',inspect)
    merged,_=sd._inspect_chapter(tmp_path/'chapter.mp4','Observe.','model',144,tmp_path/'sections.json','source')
    assert calls==[144,60.,60.,24.]
    assert [m['start'] for m in merged['moments']]==[2,62,122]
