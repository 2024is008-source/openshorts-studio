"""Outer ASGI security boundary; covers API, documentation and static media."""
import hmac
import shutil
from starlette.responses import JSONResponse


class LocalAccess:
    def __init__(self, app, token, origin, storage=None):
        if len(token) < 32:
            raise ValueError('A strong local session token is required')
        self.app, self.token, self.origin, self.storage = app, token, origin, storage
        self.host = origin.removeprefix('http://')

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get('headers', [])}
        token = headers.get(b'x-openshorts-session', b'')
        origin = headers.get(b'origin', b'').decode('latin1')
        allowed = (scope.get('client', ('',))[0] in ('127.0.0.1', '::1') and
                   headers.get(b'host', b'').decode('latin1') == self.host and
                   (not origin or origin == self.origin) and
                   hmac.compare_digest(token, self.token.encode('ascii')))
        if scope['type'] == 'websocket':
            # No desktop WebSocket protocol has been authorized yet.
            return await send({'type': 'websocket.close', 'code': 1008})
        if not allowed:
            return await JSONResponse({'detail': 'Desktop session required'}, 403)(scope, receive, send)
        if scope['method'] in ('POST', 'PUT') and self.storage:
            declared = headers.get(b'content-length', b'0')
            try:
                needed = max(2 * 1024**3, int(declared) * 2)
                if shutil.disk_usage(self.storage).free < needed:
                    return await JSONResponse({'detail': 'Insufficient working disk space'}, 507)(scope, receive, send)
            except ValueError:
                return await JSONResponse({'detail': 'Invalid content length'}, 400)(scope, receive, send)
        return await self.app(scope, receive, send)
