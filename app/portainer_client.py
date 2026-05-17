"""Cliente de la API de Portainer con retries y circuit breaker."""
import asyncio
import aiohttp
from typing import Optional

from app.config import cfg
from app.logger import log, request_id_var
from app.models import ContainerSummary, ContainerDetail


# ── Circuit Breaker ──────────────────────────────────────────────
class CircuitBreaker:
    """Circuit breaker simple para evitar llamadas a Portainer cuando está caído."""
    
    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure: Optional[float] = None
        self.state = "closed"  # closed | open | half-open
    
    def record_failure(self):
        self.failures += 1
        self.last_failure = asyncio.get_event_loop().time()
        if self.failures >= self.failure_threshold:
            self.state = "open"
            log.warning("Circuit breaker OPENED — too many failures")

    def record_success(self):
        if self.state == "half-open":
            self.state = "closed"
            self.failures = 0
            log.info("Circuit breaker CLOSED — recovered")

    def is_open(self) -> bool:
        if self.state == "closed":
            return False
        if self.state == "open" and self.last_failure:
            elapsed = asyncio.get_event_loop().time() - self.last_failure
            if elapsed >= self.reset_timeout:
                self.state = "half-open"
                log.info("Circuit breaker HALF-OPEN — testing...")
                return False
        return True


cb = CircuitBreaker()


# ── Retry helpers ────────────────────────────────────────────────
async def with_retry(coro, max_retries: int = None, base_delay: float = None):
    """Ejecutar coroutine con exponential backoff."""
    max_retries = max_retries or cfg.max_retries
    base_delay = base_delay or cfg.retry_base_delay
    
    for attempt in range(max_retries + 1):
        try:
            rid = request_id_var.get()
            log.debug(f"Portainer API attempt {attempt + 1}", extra={"request_id": rid})
            result = await coro
            cb.record_success()
            return result
        except aiohttp.ClientConnectorError as e:
            cb.record_failure()
            log.warning(f"Connection error (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                await asyncio.sleep(base_delay * (2 ** attempt))
        except aiohttp.ClientResponseError as e:
            cb.record_failure()
            log.warning(f"HTTP {e.status} error (attempt {attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                await asyncio.sleep(base_delay * (2 ** attempt))
            # Auth errors — no retry
            if e.status in (401, 403):
                raise Exception(f"Auth error: {e.status}")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            cb.record_failure()
            raise
    
    raise Exception(f"Max retries ({max_retries}) exceeded")


# ── Portainer Client ─────────────────────────────────────────────

class PortainerClient:
    """Cliente para la API de Portainer con sesiones reutilizadas."""

    def __init__(self, url: str = None, user: str = None, pw: str = None):
        self.url = url or cfg.portainer_url
        self.user = user or cfg.portainer_user
        self.pw = pw or cfg.portainer_pass
        self._jwt: Optional[str] = None
        self._endpoint_id: Optional[int] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict:
        if not self._jwt:
            raise Exception("Not authenticated — call auth() first")
        return {"Authorization": f"Bearer {self._jwt}"}

    async def auth(self) -> str:
        """Autenticar y guardar JWT. Requiere llamada periódica (Portainer expira tokens)."""
        url = f"{self.url}/api/auth"
        async def _do():
            session = await self._get_session()
            async with session.post(url, json={"username": self.user, "password": self.pw}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._jwt = data.get("jwt")
                    log.info("Portainer auth successful")
                    return self._jwt
                text = await resp.text()
                raise Exception(f"Auth failed: {resp.status} - {text}")
        
        self._jwt = await with_retry(_do())
        return self._jwt

    async def _ensure_auth(self):
        """Asegurar JWT válido antes de cada request."""
        if not self._jwt:
            await self.auth()

    async def get_endpoint_id(self) -> int:
        """Obtener endpoint ID (default: primer endpoint)."""
        if self._endpoint_id is not None:
            return self._endpoint_id
        
        async def _do():
            session = await self._get_session()
            url = f"{self.url}/api/endpoints"
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get endpoint: {resp.status}")
                data = await resp.json()
                if isinstance(data, list) and len(data) > 0:
                    self._endpoint_id = data[0].get("Id")
                elif isinstance(data, dict) and data.get("Id"):
                    self._endpoint_id = data["Id"]
                if not self._endpoint_id:
                    raise Exception("No endpoint ID found")
                return self._endpoint_id
        
        await self._ensure_auth()
        self._endpoint_id = await with_retry(_do())
        return self._endpoint_id

    async def get_containers(self) -> list[dict]:
        """Obtener todos los contenedores."""
        async def _do():
            ep_id = await self.get_endpoint_id()
            session = await self._get_session()
            url = f"{self.url}/api/endpoints/{ep_id}/docker/containers/json?all=1"
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    return await resp.json()
                raise Exception(f"Failed to get containers: {resp.status}")
        
        await self._ensure_auth()
        return await with_retry(_do())

    async def get_container_inspect(self, container_id: str) -> dict:
        """Obtener detalle de un contenedor."""
        async def _do():
            ep_id = await self.get_endpoint_id()
            session = await self._get_session()
            url = f"{self.url}/api/endpoints/{ep_id}/docker/containers/{container_id}/json"
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    return await resp.json()
                raise Exception(f"Failed to inspect container: {resp.status}")
        
        await self._ensure_auth()
        return await with_retry(_do())

    async def container_action(self, container_id: str, action: str) -> bool:
        """Ejecutar acción en contenedor (start/stop/restart)."""
        async def _do():
            ep_id = await self.get_endpoint_id()
            session = await self._get_session()
            url = f"{self.url}/api/endpoints/{ep_id}/docker/containers/{container_id}/{action}"
            async with session.post(url, headers=self._headers()) as resp:
                if resp.status in (200, 204):
                    return True
                text = await resp.text()
                raise Exception(f"Action '{action}' failed: {resp.status} - {text}")
        
        await self._ensure_auth()
        return await with_retry(_do())

    async def container_delete(self, container_id: str, force: bool = True) -> bool:
        """Eliminar un contenedor."""
        async def _do():
            ep_id = await self.get_endpoint_id()
            session = await self._get_session()
            url = f"{self.url}/api/endpoints/{ep_id}/docker/containers/{container_id}?force={str(force).lower()}"
            async with session.delete(url, headers=self._headers()) as resp:
                if resp.status in (200, 204):
                    return True
                text = await resp.text()
                raise Exception(f"Delete failed: {resp.status} - {text}")
        
        await self._ensure_auth()
        return await with_retry(_do())

    # ── Helper para hacer build de ContainerDetail desde dict raw ──
    def build_container_summary(self, raw: dict) -> ContainerSummary:
        return ContainerSummary(
            id=raw.get("Id", ""),
            name=raw["Names"][0].lstrip("/") if raw.get("Names") else "unnamed",
            image=raw.get("Image", "unknown"),
            state=raw.get("State", "unknown"),
            status=raw.get("Status", "unknown"),
            ports=raw.get("Ports", []),
        )

    def build_container_detail(self, raw: dict) -> ContainerDetail:
        inspect_state = raw.get("State", {})
        host_config = raw.get("HostConfig", {})
        return ContainerDetail(
            id=raw.get("Id", ""),
            name=raw["Names"][0].lstrip("/") if raw.get("Names") else "unnamed",
            image=raw.get("Image", "unknown"),
            state=raw.get("State", "unknown"),
            created=raw.get("Created", ""),
            started_at=inspect_state.get("StartedAt", ""),
            restart_count=inspect_state.get("RestartCount", 0),
            network_mode=host_config.get("NetworkMode", "default"),
            memory_limit=host_config.get("Memory", 0),
            env_vars=raw.get("Config", {}).get("Env", []),
        )


# Singleton con lazy init
_client: Optional[PortainerClient] = None

def get_client() -> PortainerClient:
    global _client
    if _client is None:
        _client = PortainerClient()
    return _client


async def close_client():
    global _client
    if _client:
        await _client.close()
        _client = None
