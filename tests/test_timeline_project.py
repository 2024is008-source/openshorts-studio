import copy
import json
import threading

import pytest

import timeline_project as p
import timeline_render as render


@pytest.fixture
def edits():
    return p.initial({},[{'start':0,'end':2}],None)['edits']


@pytest.mark.parametrize('value',[True,float('nan'),float('inf'),-1,'0'])
def test_reject_invalid_coordinates_and_times(edits,value):
    edits['crop']['x']=value
    with pytest.raises(ValueError):p.normalize(edits,10,[])
    edits['crop']['x']=.5;edits['segments'][0]['start']=value
    with pytest.raises(ValueError):p.normalize(edits,10,[])


def test_trim_split_reorder_remove_preserve_decisions(edits):
    edits['segments']=[{'start':5,'end':6},{'start':1,'end':2}]
    assert p.normalize(edits,10,[])['segments']==edits['segments']
    edits['segments']=[]
    with pytest.raises(ValueError):p.normalize(edits,10,[])


def test_native_appearance_and_aligned_word_edits_survive_mapping(edits):
    rows=p.captions({'segments':[{'start':0,'end':2,'words':[
        {'word':' Hello','start':.1,'end':.5},{'word':' world','start':.6,'end':1}]}]})
    edits['style']['appearance']=dict(font_name='Arial',font_size=64,font_color='#ffffff',
        highlight_color='#00FF88',border_color='#000000',border_width=3,shadow=2,effect='pop')
    edits['caption_overrides']={'0':dict(start=.1,end=1,text='Hello world',words=[
        dict(word='Hello',start=.15,end=.55,emphasis=True),dict(word='world',start=.6,end=1,emphasis=False)])}
    checked=p.normalize(edits,2,rows)
    assert p.normalize(checked,2,rows)==checked
    words=p.transcript(rows,checked)['segments'][0]['words']
    assert words[0]['aligned'] and words[0]['emphasis'] and words[0]['start']==.15
    assert checked['style']['appearance']==edits['style']['appearance']
    edits['caption_overrides']['0']['text']='Rewritten text'
    with pytest.raises(ValueError):p.normalize(edits,2,rows)


@pytest.mark.parametrize('appearance',[
    {'font_size':float('nan')},{'font_size':1000},{'font_name':'file=secret'},
    {'font_color':'white;movie=.env'},{'effect':'command'},{'shadow':True},{'unknown':1},
])
def test_native_appearance_rejects_unsafe_fields(edits,appearance):
    edits['style']['appearance']=appearance
    with pytest.raises(ValueError):p.normalize(edits,2,[])


def test_native_words_do_not_invent_alignment_or_accept_overlaps(edits):
    rows=p.captions({'segments':[dict(start=0,end=1,text='Hello world')]})
    edits['caption_overrides']={'0':dict(start=0,end=1,text='Hello world',words=[
        dict(word='Hello world',start=0,end=1,emphasis=True)])}
    with pytest.raises(ValueError):p.normalize(edits,2,rows)
    rows=p.captions({'segments':[{'start':0,'end':1,'words':[
        dict(word=' Hello',start=0,end=.5),dict(word=' world',start=.5,end=1)]}]})
    edits['caption_overrides']['0']['words']=[dict(word='Hello',start=0,end=.6,emphasis=False),dict(word='world',start=.5,end=1,emphasis=False)]
    with pytest.raises(ValueError):p.normalize(edits,2,rows)


def test_desktop_advanced_caption_layout_round_trip_and_cache(edits):
    appearance=dict(bg_color='#122334',bg_opacity=.4,max_lines=3,max_words=7,
                    sync_offset=.12,min_phrase_duration=.5,line_spacing=1.4,base_opacity=.6,uppercase=True)
    edits['style']['appearance']=appearance
    checked=p.normalize(edits,2,[])
    assert p.normalize(checked,2,[])==checked
    import caption_renderer
    config=caption_renderer.options(checked['style']['preset'],**appearance)
    assert config['max_lines']==3 and config['sync_offset']==.12 and config['uppercase'] is True
    key=p.caption_key('clean',{},checked['style'])
    changed=copy.deepcopy(checked['style']);changed['appearance']['sync_offset']=.2
    assert key!=p.caption_key('clean',{},changed)


@pytest.mark.parametrize('appearance',[{'max_lines':2.1},{'uppercase':'yes'},{'sync_offset':float('inf')},
    {'bg_opacity':-1},{'max_words':13},{'line_spacing':2},{'base_opacity':0},{'min_phrase_duration':.01}])
def test_desktop_advanced_caption_rejects_invalid_values(edits,appearance):
    edits['style']['appearance']=appearance
    with pytest.raises(ValueError):p.normalize(edits,2,[])


@pytest.mark.parametrize('change',[
    {'path':'../../.env'},{'style':{'enabled':True,'preset':'drawtext=file=.env','position':'bottom'}},
    {'crop':{'mode':'crop','x':.5,'y':2}}, {'caption_overrides':{'unknown':{'start':0,'end':1,'text':'x'}}},
])
def test_reject_unsafe_or_unknown_edits(edits,change):
    with pytest.raises(ValueError):p.normalize({**edits,**change},10,[])


def test_caption_override_timing_maps_without_false_word_alignment(edits):
    rows=p.captions({'segments':[{'start':0,'end':5,'words':[
        {'word':' Original','start':1,'end':1.5},{'word':' words.','start':1.6,'end':2}]}]})
    edits['segments']=[{'start':1,'end':3},{'start':0,'end':2}]
    edits['caption_overrides']={'0':{'text':'Corrected phrase','start':1.2,'end':1.8}}
    normalized=p.normalize(edits,5,rows)
    transcript=p.transcript(rows,normalized)
    assert transcript['segments'][0]['words'][0]==dict(word=' Corrected phrase',start=.2,end=.8,aligned=False)
    assert transcript['segments'][1]['words'][0]['start']==3.2
    assert p.local_markers(edits['segments'],[1.5])==[.5,3.5]


def test_cache_dependencies_invalidate_only_affected_stages(tmp_path,edits):
    path=tmp_path/'source.mp4';path.write_bytes(b'source')
    key=p.segment_key(path,edits['segments'][0],edits['crop'],(1080,1920),30,True)
    changed=copy.deepcopy(edits);changed['style']['preset']='podcast';changed['caption_overrides']={'0':{'text':'new'}}
    assert p.segment_key(path,changed['segments'][0],changed['crop'],(1080,1920),30,True)==key
    changed['crop']['x']=.9
    assert p.segment_key(path,changed['segments'][0],changed['crop'],(1080,1920),30,True)!=key
    assert p.assembly_key(['a','b'])!=p.assembly_key(['b','a'])
    assert p.caption_key('clean',{},edits['style'])!=p.caption_key('clean',{},changed['style'])
    path.write_bytes(b'replacement')
    assert p.segment_key(path,edits['segments'][0],edits['crop'],(1080,1920),30,True)!=key


def test_mapping_current_clean_video_supports_reordered_source_segments():
    original=[dict(start=10,end=20),dict(start=40,end=50)]
    assert p.mapped_bounds(dict(start=42,end=45),original)==dict(start=12,end=15)
    assert p.mapped_bounds(dict(start=18,end=42),original) is None


def test_caption_restyling_preserves_saved_corrections_for_long_sources():
    source=dict(language='en',segments=[dict(start=1,end=2,text='Original.'),dict(start=590,end=600,text='The ending.')])
    clip=dict(end=2,editor_caption_source_digest=p.digest(source),
              editor_caption_overrides={'0':dict(start=1,end=2,text='Corrected.')})
    patched=p.caption_source(clip,source)
    assert patched['language']=='en' and patched['segments'][0]['text']=='Corrected.'
    assert source['segments'][0]['text']=='Original.'
    clip['editor_caption_source_digest']='stale'
    assert p.caption_source(clip,source) is source


def test_cancellation_terminates_process_and_timeout_is_bounded():
    import sys
    cancel=threading.Event();timer=threading.Timer(.3,cancel.set);timer.start()
    with pytest.raises(render.Cancelled):render.run([sys.executable,'-c','import time; time.sleep(60)'],cancel)
    timer.join()
    with pytest.raises(TimeoutError):render.run([sys.executable,'-c','import time; time.sleep(60)'],threading.Event(),.1)


def test_cached_receipt_rejects_interrupted_or_changed_files(tmp_path):
    path=tmp_path/'artifact.mp4';path.write_bytes(b'valid')
    assert not render.cached(path)
    render.receipt(path);assert render.cached(path)
    path.write_bytes(b'broken bytes');assert not render.cached(path)
    path.write_bytes(b'');render.receipt(path);assert not render.cached(path)


def test_real_render_reuses_segments_for_captions_and_only_changes_trimmed_part(tmp_path,real_clip,edits):
    source=real_clip('editor-source')
    edits['segments']=[{'start':0,'end':1},{'start':1,'end':2}]
    edits['style']['enabled']=False
    kwargs=dict(rows=[],source=str(source),canonical=str(source),canonical_range={'start':0,'end':2},
        size=(108,192),fps=24,audio=True,directory=tmp_path,cancel=threading.Event(),progress=lambda *a:None)
    first,stats=render.render(edits=edits,**kwargs)
    assert stats['segment_hits']==0
    second,stats2=render.render(edits=edits,**kwargs)
    assert first==second and stats2['segment_hits']==2
    edits['style']['enabled']=True
    edits['style']['preset']='cinematic'
    _,stats3=render.render(edits=edits,**kwargs)
    assert stats3['segment_hits']==2
    edits['segments'][0]['start']=.5
    last,stats4=render.render(edits=edits,**kwargs)
    assert stats4['segment_hits']==1
    import export_quality as q
    assert q.streams(q.probe(last))[0]['width']==108
    assert not list(tmp_path.glob('temp_editor_*'))


def test_preview_and_full_hd_crop_and_caption_rules_match(tmp_path,real_clip,edits):
    import export_quality as q
    import subprocess
    source=real_clip('split-color',audio=None,
        video='color=c=red:s=128x72:r=24:d=2,drawbox=x=64:y=0:w=64:h=72:color=blue:t=fill')
    edits['crop']=dict(mode='crop',x=0,y=.5)
    rows=p.captions({'segments':[dict(start=.4,end=1.4,text='A retained source caption.')]})
    pixels=[]
    for size in [(108,192),(1080,1920)]:
        path,_=render.render(edits=edits,rows=rows,source=str(source),canonical=None,
            canonical_range={'start':0,'end':2},size=size,fps=24,audio=False,
            directory=tmp_path,cancel=threading.Event(),progress=lambda *a:None)
        expected=q.expectations(q.probe(source),duration=2,size=size)
        assert q.enforce(path,'consistency',expected)['accepted']
        frame=subprocess.run(['ffmpeg','-v','error','-ss','0.1','-threads','1','-i',path,'-frames:v','1',
            '-filter_threads','1','-vf','scale=2:2','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],capture_output=True,check=True,timeout=10).stdout
        pixels.append(frame)
    assert all(abs(a-b)<12 for a,b in zip(*pixels))
    assert pixels[0][0]>200 and pixels[0][2]<50


def test_cancelled_render_cleans_owned_temporaries_and_keeps_valid_parts(tmp_path,real_clip,edits):
    source=real_clip('cancel-source');cancel=threading.Event()
    edits['segments']=[dict(start=0,end=1),dict(start=1,end=2)]
    kwargs=dict(edits=edits,rows=[],source=str(source),canonical=str(source),canonical_range=dict(start=0,end=2),
        size=(64,36),fps=24,audio=True,directory=tmp_path,cancel=cancel)
    # Frame-clock progress can now cancel before a part completes. This case
    # deliberately cancels after the first completed part to verify cache reuse.
    with pytest.raises(render.Cancelled):render.render(**kwargs,progress=lambda value,label:cancel.set() if label=='Rendering changed video segments' else None)
    assert not list(tmp_path.glob('temp_editor_*'))
    assert len(list(tmp_path.glob('editor_part_*.mp4')))==1
    cancel.clear()
    _,stats=render.render(**kwargs,progress=lambda *a:None)
    assert stats['segment_hits']==1


from test_export_quality import real_clip  # noqa: F401
