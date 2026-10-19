"""Versioned shared policies, not category-specific event detectors."""
import auto_edit

VERSION=1
CATEGORIES={'challenge':['auto','competition','survival','experiment','general'], 'podcast':['auto','motivation','education','comedy'],
    'sports_highlights':['auto','cricket','football'], 'movie_scene_trailer':[],
    'comedy':[], 'default_clipping':[]}
ALIASES={'general':'default_clipping','educational':'podcast','emotional':'default_clipping'}


def category(value):
    try:
        from category_intelligence import resolve
        primary,_=resolve(value)
        value='default_clipping' if primary=='general' else primary
    except (ValueError,TypeError):pass
    value=ALIASES.get(value,value)
    return value if value in CATEGORIES else 'default_clipping'


def policy(value,subtype='auto'):
    value=category(value)
    if subtype!='auto' and subtype not in CATEGORIES[value]:raise ValueError('Unknown category subtype')
    return dict(version=VERSION,category=value,subtype=subtype,foundation_only=True,
        reserved=value in ('movie_scene_trailer','comedy','default_clipping'),
        allowed_effects=sorted(auto_edit.SUPPORTED),suppressed_effects=sorted(auto_edit.UNSUPPORTED|auto_edit.DELEGATED),
        captions={'preference':'existing_project'},pacing={'preference':'existing_director'},
        evidence_requirements=['retained_source','valid_timestamps','renderer_support','safe_geometry'],
        framing_limits={'preserve_protected_regions':True,'max_zoom':1.18},ranking_weights={'evidence':1.,'safety':1.},
        renderer_capability_check=True)
