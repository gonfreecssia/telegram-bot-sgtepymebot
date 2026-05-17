"""Cliente de la API de Portainer con retries y circuit breaker."""
import asyncio
import aiohttp
from typing import Optional

from app.config import cfg
from app.logger import log, request_id_var
from app.models import ContainerSummary, ContainerDetail


# ── Types ────────────────────────────────────────────────────────────────────
_JSON = dict[str, object]  # type alias for decoded JSON


# ── Circuit Breaker ───────────────────────────────────────────────────────────
class CircuitBreaker:
    """Circuit breaker simple para evitar llamadas a Portainer cuando está caído."""

    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 30.0) -> None:
        self.failure_threshold: int = failure_threshold
        self.reset_timeout: float = reset_timeout
        self.failures: int = 0
        self.last_failure: Optional[float] = None
        self.state: str = "closed"  # closed | open | half-open

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure = asyncio.get_event_loop().time()
        if self.failures >= self.failure_threshold:
            self.state = "open"
            log.warning("Circuit breaker OPENED — too many failures")

    def record_success(self) -> None:
        if self.state == "half-open":
            self.state = "closed"
            self.failures = 0
            log.info("Circuit breaker CLOSED — recovered")

    def is_open(self) -> bool:
        if self.state == "closed":
            return False
        if self.state == "open" and self.last_failure is not None:
            elapsed = asyncio.get_event_loop().time() - self.last_failure
            if elapsed >= self.reset_timeout:
                self.state = "half-open"
                log.info("Circuit breaker HALF-OPEN — testing...")
                return False
        return True


cb: CircuitBreaker = CircuitBreaker()


# ── Retry helpers ─────────────────────────────────────────────────────────────
async def with_retry(
    coro: object,  # Awaitable[_T]
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
) -> object:  # -> _T:
    """Ejecutar coroutine con exponential backoff."""
    max_retries_val: int = max_retries if max_retries is not None else cfg.max_retries
    base_delay_val: float = base_delay if base_delay is not None else cfg.retry_base_delay

    for attempt in range(max_retries_val + 1):
        try:
            rid: Optional[str] = request_id_var.get()
            log.debug(f"Portainer API attempt {attempt + 1}", extra={"request_id": rid})
            result = await coro  # type: ignore[misc]
            cb.record_success()
            return result
        except aiohttp.ClientConnectorError as e:
            cb.record_failure()
            log.warning(f"Connection error (attempt {attempt + 1}/{max_retries_val + 1}): {e}")
            if attempt < max_retries_val:
                await asyncio.sleep(base_delay_val * (2 ** attempt))
        except aiohttp.ClientResponseError as e:
            cb.record_failure()
            log.warning(f"HTTP {e.status} error (attempt {attempt + 1}/{max_retries_val + 1})")
            if attempt < max_retries_val:
                await asyncio.sleep(base_delay_val * (2 ** attempt))
            if e.status in (401, 403):
                raise Exception(f"Auth error: {e.status}")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            cb.record_failure()
            raise

    raise Exception(f"Max retries ({max_retries_val}) exceeded")


# ── Portainer Client ──────────────────────────────────────────────────────────

class PortainerClient:
    """Cliente para la API de Portainer con sesiones reutilizadas."""

    def __init__(
        self,
        url: Optional[str] = None,
        user: Optional[str] = None,
        pw: Optional[str] = None,
    ) -> None:
        self.url: str = url or cfg.portainer_url
        self.user: str = user or cfg.portainer_user
        self.pw: str = pw or cfg.portainer_pass
        self._jwt: Optional[str] = None
        self._endpoint_id: Optional[int] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        if not self._jwt:
            raise Exception("Not authenticated — call auth() first")
        return {"Authorization": f"Bearer {self._jwt}"}

    async def auth(self) -> str:
        """Autenticar y guardar JWT. Requiere llamada periódica (Portainer expira tokens)."""
        url = f"{self.url}/api/auth"

        async def _do() -> str:
            session: aiohttp.ClientSession = await self._get_session()
            async with session.post(
                url, json={"username": self.user, "password": self.pw}
            ) as resp:
                if resp.status == 200:
                    data: _JSON = await resp.json()
                    jwt: str = data.get("jwt")  # type: ignore[assignment]
                    self._jwt = jwt
                    log.info("Portainer auth successful")
                    return jwt
                text: str = await resp.text()
                raise Exception(f"Auth failed: {resp.status} - {text}")

        self._jwt = await with_retry(_do())  # type: ignore[assignment]
        return self._jwt

    async def _ensure_auth(self) -> None:
        """Asegurar JWT válido antes de cada request."""
        if not self._jwt:
            await self.auth()

    async def get_endpoint_id(self) -> int:
        """Obtener endpoint ID (default: primer endpoint)."""
        if self._endpoint_id is not None:
            return self._endpoint_id

        async def _do() -> int:
            session: aiohttp.ClientSession = await self._get_session()
            url = f"{self.url}/api/endpoints"
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get endpoint: {resp.status}")
                data: object = await resp.json()
                ep_id: int
                if isinstance(data, list) and len(data) > 0:
                    first = data[0]  # type: ignore[index]
                    ep_id = first.get("Id")  # type: ignore[union-attr]
                elif isinstance(data, dict):
                    ep_id = data.get("Id", 0)  # type: ignore[union-attr]
                else:
                    raise Exception("Invalid endpoint response")
                if not ep_id:
                    raise Exception("No endpoint ID found")
                return ep_id

        await self._ensure_auth()
        self._endpoint_id = await with_retry(_do())
        return self._endpoint_id

    async def get_containers(self) -> list[dict[str, object]]:
        """Obtener todos los contenedores."""
        async def _do() -> list[dict[str, object]]:
            ep_id: int = await self.get_endpoint_id()
            session: aiohttp.ClientSession = await self._get_session()
            url = f"{self.url}/api/endpoints/{ep_id}/docker/containers/json?all=1"
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    result: list[dict[str, object]] = await resp.json()
                    return result
                raise Exception(f"Failed to get containers: {resp.status}")

        await self._ensure_auth()
        return await with_retry(_do())  # type: ignore[return-value]

    async def get_container_inspect(self, container_id: str) -> dict[str, object]:
        """Obtener detalle de un contenedor."""
        async def _do() -> dict[str, object]:
            ep_id: int = await self.get_endpoint_id()
            session: aiohttp.ClientSession = await self._get_session()
            url = f"{self.url}/api/endpoints/{ep_id}/docker/containers/{container_id}/json"
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    result: dict[str, object] = await resp.json()
                    return result
                raise Exception(f"Failed to inspect container: {resp.status}")

        await self._ensure_auth()
        return await with_retry(_do())  # type: ignore[return-value]

    async def container_action(self, container_id: str, action: str) -> bool:
        """Ejecutar acción en contenedor (start/stop/restart)."""
        async def _do() -> bool:
            ep_id: int = await self.get_endpoint_id()
            session: aiohttp.ClientSession = await self._get_session()
            url = (
                f"{self.url}/api/endpoints/{ep_id}/docker/containers/{container_id}/{action}"
            )
            async with session.post(url, headers=self._headers()) as resp:
                if resp.status in (200, 204):
                    return True
                text: str = await resp.text()
                raise Exception(f"Action '{action}' failed: {resp.status} - {text}")

        await self._ensure_auth()
        return await with_retry(_do())  # type: ignore[return-value]

    async def container_delete(self, container_id: str, force: bool = True) -> bool:
        """Eliminar un contenedor."""
        async def _do() -> bool:
            ep_id: int = await self.get_endpoint_id()
            session: aiohttp.ClientSession = await self._get_session()
            url = (
                f"{self.url}/api/endpoints/{ep_id}/docker/containers/{container_id}"
                f"?force={str(force).lower()}"
            )
            async with session.delete(url, headers=self._headers()) as resp:
                if resp.status in (200, 204):
                    return True
                text: str = await resp.text()
                raise Exception(f"Delete failed: {resp.status} - {text}")

        await self._ensure_auth()
        return await with_retry(_do())  # type: ignore[return-value]

    def build_container_summary(self, raw: dict[str, object]) -> ContainerSummary:
        names: list[str] = raw.get("Names")  # type: ignore[assignment]
        return ContainerSummary(
            id=raw.get("Id", ""),  # type: ignore[arg-type]
            name=names[0].lstrip("/") if names else "unnamed",
            image=raw.get("Image", "unknown"),  # type: ignore[arg-type]
            state=raw.get("State", "unknown"),  # type: ignore[arg-type]
            status=raw.get("Status", "unknown"),  # type: ignore[arg-type]
            ports=raw.get("Ports", []),  # type: ignore[arg-type]
        )

    def build_container_detail(self, raw: dict[str, object]) -> ContainerDetail:
        inspect_state: dict[str, object] = raw.get("State", {})  # type: ignore[assignment]
        host_config: dict[str, object] = raw.get("HostConfig", {})  # type: ignore[assignment]
        config_section: dict[str, object] = raw.get("Config", {})  # type: ignore[assignment]
        names: list[str] = raw.get("Names", [])  # type: ignore[assignment]
        return ContainerDetail(
            id=raw.get("Id", ""),  # type: ignore[arg-type]
            name=names[0].lstrip("/") if names else "unnamed",
            image=raw.get("Image", "unknown"),  # type: ignore[arg-type]
            state=raw.get("State", "unknown"),  # type: ignore[arg-type]
            created=raw.get("Created", ""),  # type: ignore[arg-type]
            started_at=inspect_state.get("StartedAt", ""),  # type: ignore[arg-type]
            restart_count=inspect_state.get("RestartCount", 0),  # type: ignore[arg-type]
            network_mode=host_config.get("NetworkMode", "default"),  # type: ignore[arg-type]
            memory_limit=host_config.get("Memory", 0),  # type: ignore[arg-type]
            env_vars=config_section.get("Env", []),  # type: ignore[arg-type]
        )


# Singleton con lazy init
_client: Optional[PortainerClient] = None


def get_client() -> PortainerClient:
    global _client
    if _client is None:
        _client = PortainerClient()
    return _client


async def close_client() -> None:
    global _client
    if _client:
        await _client.close()
        _client = None