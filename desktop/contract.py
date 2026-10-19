"""Versioned native adapter contract. No credentials or machine paths."""
PROTOCOL_VERSION = 1
FEATURES = ('project-library', 'source-media', 'templates', 'pipeline-cancel',
            'saved-timeline', 'timeline-features', 'caption-appearance', 'aligned-word-edits', 'advanced-caption-layout', 'native-editor-workspace', 'native-video-import', 'generation-drafts', 'generation-review', 'clip-duplication')


def describe(engine):
    routes = sorted({(method, route.path) for route in engine.app.routes
                     for method in getattr(route, 'methods', ()) if method not in ('HEAD', 'OPTIONS')})
    return dict(protocol_version=PROTOCOL_VERSION, editor_project_version=1,
                features=list(FEATURES), routes=[dict(method=m, path=p) for m,p in routes],
                entrypoint='native_engine_entry.py', credential_store='windows-current-user-dpapi')
