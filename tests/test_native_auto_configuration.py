import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from desktop import processes
from desktop.generation_review import progress
from test_native_home import engine, fixture
import video_templates as templates
from generation_options import normalize_options


def test_requested_env_keys_are_allowlisted_and_explicit_env_precedes_saved_primary(tmp_path,monkeypatch):
    (tmp_path/'.env').write_text('GEMINI_API_KEY_1=local-first\nGEMINI_API_KEY_2=local-second\nSTRIPE_SECRET_KEY=never-copy\nPYTHONPATH=never-copy\nGEMINI_MODEL=test-model\n')
    monkeypatch.setattr(processes,'resources',lambda:tmp_path)
    store=SimpleNamespace(local=tmp_path,work=tmp_path/'temp',cache=tmp_path/'cache')
    env=processes.environment(store,dict(encoder='auto',preset='balanced'),'protected-primary')
    assert env['GEMINI_API_KEY']=='local-first'
    assert env['GEMINI_KEY_SOURCE']=='env'
    assert env['GEMINI_API_KEY_1']=='local-first' and env['GEMINI_API_KEY_2']=='local-second'
    assert env['GEMINI_MODEL']=='test-model'
    assert 'STRIPE_SECRET_KEY' not in env and 'PYTHONPATH' not in env
    assert env['PYTHON_DOTENV_DISABLED']=='1'
    assert processes.environment(store,dict(encoder='auto',preset='balanced'),'')['GEMINI_API_KEY']=='local-first'


@pytest.mark.parametrize('mode,expected',[('challenge','challenge'),('podcast','podcast'),('educational','story-focus'),('comedy','creator-energy'),('general','minimal-studio')])
def test_automatic_template_uses_existing_story_but_manual_selection_wins(mode,expected):
    assert templates.selected('auto',{'story':{'mode':mode}})['id']==expected
    assert templates.selected('creator-energy',{'story':{'mode':mode}})['id']=='creator-energy'
    assert normalize_options(video_template='auto')['VIDEO_TEMPLATE']=='auto'


@pytest.mark.parametrize('framing',['auto','balanced','subject','editorial'])
def test_manual_framing_is_not_overridden_by_template(framing,monkeypatch):
    monkeypatch.setenv('VIDEO_TEMPLATE','podcast');monkeypatch.setenv('FRAMING_PRESET',framing)
    assert templates.framing_preference()==framing


def test_completed_steps_survive_long_logs_and_chapter_progress_is_measured(tmp_path):
    e=engine(tmp_path);fixture(e)
    e.jobs['job-one'].update(status='processing',logs=['Job started by worker.','Transcribing video...','Transcribing… 100% (40s)']+['Observed transcript segment']*1000+['Video analysis: chapter 3/5 (354–534s)'])
    folder=Path(e.OUTPUT_DIR)/'job-one';(folder/'story_analysis.json').write_text(json.dumps({'chapters':[{},{}]}))
    result=progress(e,'job-one');stages={s['id']:s for s in result['stages']}
    assert stages['prepare']['state']=='completed' and stages['transcribe']['state']=='completed'
    assert stages['analyze']['percent']==40 and result['analysis_chapter']=={'current':3,'total':5,'completed':2}
    e.jobs['job-one']['logs'].append('Analyzing with Gemini (2-pass: score → detail)...')
    result=progress(e,'job-one');stages={s['id']:s for s in result['stages']}
    assert stages['analyze']['state']=='completed' and stages['select']['state']=='active'


def test_provider_has_one_sdk_attempt_and_a_bounded_timeout():
    from gemini_worker import http_options
    options=http_options();assert options.retry_options.attempts==1 and options.timeout==120000
