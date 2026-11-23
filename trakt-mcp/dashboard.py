"""Administrator dashboard on an unpublished port, restricted to HA Supervisor ingress."""
import ipaddress
import json
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from errors import TraktError

INGRESS_PEER = ipaddress.ip_address('172.30.32.2')
WEB = Path(__file__).with_name('web')
HEADERS = {
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'SAMEORIGIN',
    'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "base-uri 'none'; object-src 'none'; frame-ancestors 'self'; form-action 'none'",
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}


class IngressOnly:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            try:
                peer = ipaddress.ip_address(scope['client'][0])
                peer = getattr(peer, 'ipv4_mapped', None) or peer
            except (KeyError, ValueError, TypeError, IndexError):
                peer = None
            if peer != INGRESS_PEER:
                await JSONResponse({'error': 'Home Assistant ingress required'}, status_code=403,
                                   headers=HEADERS)(scope, receive, send)
                return
            async def secured_send(message):
                if message['type'] == 'http.response.start':
                    message['headers'] = list(message.get('headers', [])) + [
                        (k.lower().encode(), v.encode()) for k, v in HEADERS.items()]
                await send(message)
            await self.app(scope, receive, secured_send)
            return
        await self.app(scope, receive, send)


def create_dashboard(statistics, writes=None):
    async def index(request):
        return FileResponse(WEB / 'index.html', media_type='text/html')

    async def stylesheet(request):
        return FileResponse(WEB / 'status.css', media_type='text/css')

    async def script(request):
        return FileResponse(WEB / 'status.js', media_type='application/javascript')

    async def stats(request):
        try:
            return JSONResponse(await statistics())
        except Exception:
            return JSONResponse({'error': 'Statistics temporarily unavailable. Try refreshing.'}, status_code=503)

    async def review(request):
        if writes is None or request.headers.get('content-type') != 'application/json':
            return JSONResponse({'error': 'Invalid approval request.'}, status_code=400)
        try:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 1024:
                    return JSONResponse({'error': 'Approval request too large.'}, status_code=413)
                body.extend(chunk)
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError()
            operation_id = data.get('operation_id')
            if not isinstance(operation_id, str) or len(operation_id) > 32:
                raise ValueError()
            decision = data.get('decision')
            if decision == 'stage_undo':
                return JSONResponse(writes.stage_undo(operation_id))
            proof = data.get('approval')
            if (decision not in ('approve', 'decline') or not isinstance(proof, str)
                    or len(proof) > 64 or not proof.isascii()):
                raise ValueError()
            return JSONResponse(await writes.approve(operation_id, proof, decision))
        except (ValueError, TraktError):
            return JSONResponse({'error': 'Approval rejected. Refresh the dashboard.'}, status_code=409)

    return IngressOnly(Starlette(routes=[Route('/', index), Route('/assets/status.css', stylesheet),
                                        Route('/assets/status.js', script), Route('/api/stats', stats), Route('/api/review', review, methods=['POST'])]))
