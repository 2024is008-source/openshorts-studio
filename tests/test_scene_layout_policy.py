import editing_director as director
import split_layout


def context(*moments):
    return {'segments':[{'start':807.52,'end':833.29}], 'analysis':{'moments':list(moments)}}


def moment(intent='two_speaker_split', start=807.52, end=833.29, **kwargs):
    return dict(start=start,end=end,layout_intent=intent,
                layout_evidence='Two separate stationary talking-head views.',**kwargs)


def test_split_requires_retained_semantic_evidence_not_faces_or_genre():
    assert director.scene_layout_policy(context(),0,250,10)[0]=='uncertain'
    assert director.scene_layout_policy(context({'start':807.52,'end':833.29,
        'editing_kind':'podcast','visual_evidence':'Two people.'}),0,250,10)[0]=='uncertain'
    assert director.scene_layout_policy(context(moment()),0,250,10)[0]=='two_speaker_split'


def test_shared_action_and_objects_override_split_even_with_conflicting_evidence():
    for intent in ('preserve_scene','demonstration','single_subject'):
        assert director.scene_layout_policy(context(moment(),moment(intent)),0,250,10)[0]!='two_speaker_split'
    shared=moment('preserve_scene')
    assert director.context_shots(context(shared),[(0,250,'TRACK')],10)=={0}


def test_duplicate_or_nonoverlapping_evidence_cannot_authorize_split():
    short=moment(end=812.52)
    assert director.scene_layout_policy(context(short,short,short,short),0,250,10)[0]=='uncertain'
    assert director.scene_layout_policy(context(moment(start=0,end=20)),0,250,10)[0]=='uncertain'


def test_word_boundary_expansion_does_not_expand_visual_evidence():
    row=moment(layout_source_start=810.,layout_source_end=815.)
    assert director.scene_layout_policy(context(row),0,250,10)[0]=='uncertain'
    assert director.scene_layout_policy(context(moment(start=float('nan'))),0,250,10)[0]=='uncertain'


def test_independent_views_cannot_duplicate_the_same_source_region():
    assert split_layout.independent_split(1920,1080,1080,1920,
        ((350,350,150,150),(1570,350,150,150)))
    assert not split_layout.independent_split(1920,1080,1080,1920,
        ((600,350,150,150),(1150,350,150,150)))
    assert not split_layout.independent_split(1920,1080,1080,1920,
        ((600,350,150,150),(600,350,150,150)))


def test_shot_observations_override_a_broad_story_layout_without_boundary_bleed():
    data=context(moment('preserve_scene'))
    data['analysis']['scene_observations']=[moment('single_subject',start=807.52,end=817.52),
        moment('preserve_scene',start=817.52,end=833.29)]
    assert director.scene_layout_policy(data,0,100,10)[0]=='uncertain'
    assert director.context_shots(data,[(0,100,'TRACK'),(100,250,'TRACK')],10)=={100}
    # A tiny intersection with the neighboring contextual shot does not flatten this shot.
    assert director.context_shots(data,[(0,101,'TRACK')],10)==set()
