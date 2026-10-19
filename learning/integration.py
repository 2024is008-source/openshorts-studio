"""Fail-open bridge: optional ranking can only remove/reorder safe AI candidates."""
from learning.database import Store
from learning import service,features
from learning.models import rank


def apply(plan,settings):
    try:
        store=Store();store.purge()
        service.observe(plan,settings,store)
        if not store.preferences()['inference']:return settings
        import auto_edit
        # Existing validator decides eligibility first, and remains authoritative
        # after ranking. Manual effects never become ML-controlled candidates.
        safe={e['id']:e for e in auto_edit.active(settings) if e['origin']=='ai'}
        candidates=[];groups=[]
        scenes={s['id']:s for s in settings['scenes']}
        spacing={s['id']:previous for s,_,previous in features.scene_contexts(settings)}
        for effect in safe.values():
            scene=scenes[effect['source_scene']]
            for candidate in (effect,{'type':'none'}):
                value=features.extract(scene,candidate,((plan.get('evidence') or {}).get('category_selection') or {}).get('primary_category',plan.get('kind')),spacing[scene['id']])
                candidates.append(dict(features=value))
            groups.append(effect['id'])
        scores=rank(store,candidates) if candidates else None
        if scores is None:return settings
        retained={identity for i,identity in enumerate(groups) if scores[2*i]>scores[2*i+1]}
        result=__import__('copy').deepcopy(settings)
        result['effects']=[e for e in settings['effects'] if e['origin']=='manual' or e['id'] in retained]
        return auto_edit.normalize(result,plan['duration'])
    except Exception:
        # Database, disk and model errors must never break generation/export.
        return settings
