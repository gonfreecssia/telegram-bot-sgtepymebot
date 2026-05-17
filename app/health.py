"""Health check HTTP server para aiohttp (usado por Portainer/external monitors)."""
import asyncio
import logging
from typing import Optional

from aiohttp import web

from app.portainer_client import get_client, cb as circuit_breaker

log = logging.getLogger(__name__)

_health_app: Optional[web.Application] = None
_health_runner: Optional[web.AppRunner] = None
_health_site: Optional[web.TCPSite] = None


async def health_handler(request: web.Request) -> web.Response:
    """GET /health — retorna estado del bot y sus dependencias."""
    client = get_client()
    
    # Verificar circuit breaker
    cb_state = circuit_breaker.state
    
    # Verificar Portainer si el circuit breaker no está abierto
    portainer_ok = False
    if cb_state != "open":
        try:
            await client.get_containers()
            portainer_ok = True
        except Exception:
            pass
    
    status = "healthy" if portainer_ok else "degraded"
    http_status = 200 if portainer_ok else 503
    
    containers_count = 0
    try:
        containers_count = len(await client.get_containers())
    except Exception:
        pass
    
    return web.json_response(
        {
            "status": status,
            "bot": "operational",
            "portainer": "connected" if portainer_ok else "unavailable",
            "circuit_breaker": cb_state,
            "containers_count": containers_count,
        },
        status=http_status,
    )


async def ready_handler(request: web.Request) -> web.Response:
    """GET /ready — readiness probe simple (solo si el bot está corriendo)."""
    return web.json_response({"ready": True})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/ready", ready_handler)
    return app


async def start_health_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Iniciar servidor HTTP de health check en segundo plano."""
    global _health_app, _health_runner, _health_site
    
    app = create_app()
    _health_runner = web.AppRunner(app)
    await _health_runner.setup()
    _health_site = web.TCPSite(_health_runner, host, port)
    await _health_site.start()
    log.info(f"Health server started on {host}:{port}")


async def stop_health_server() -> None:
    """Detener el servidor HTTP de health check."""
    global _health_runner, _health_site
    if _health_site:
        await _health_site.stop()
        _health_site = None
    if _health_runner:
        await _health_runner.cleanup()
        _health_runner = None
    log.info("Health server stopped")
