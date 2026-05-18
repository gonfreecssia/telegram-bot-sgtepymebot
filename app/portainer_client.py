"""Cliente de la API de Portainer con retries y circuit breaker."""
import asyncio
import json
import aiohttp
from dataclasses import dataclass, field
from typing import Optional

from app.config import cfg
from app.logger import log, request_id_var
from app.models import ContainerSummary, ContainerDetail


# ── Types ───────────────────────────────────────────────────────────────────
_JSON = dict[str, object]  # type alias for decoded JSON


# ── Multi-endpoint support ────────────────────────────────────────────────────

@dataclass
class EndpointConfig:
    """Configuracion de un endpoint Portainer."""
    name: str
    url: str
    user: str
    password: str


def get_endpoint_configs() -> list[EndpointConfig]:
    """Parsear PORTAINER_ENDPOINTS JSON array.

    Formato env var:
    PORTAINER_ENDPOINTS='[{"name":"CasaOS","url":"http://192.168.1.184:9000","user":"admin","password":"xxx"}]'

    Si no esta definido, retorna una lista con el endpoint unico legacy
    (usando PORTAINER_URL, PORTAINER_USER, PORTAINER_PASSWORD).
    """
    raw = cfg.portainer_endpoints_json
    if raw:
        try:
            data = json.loads(raw)
            return [
                EndpointConfig(
                    name=ep.get("name", f"ep{i}"),
                    url=ep["url"],
                    user=ep.get("user", "admin"),
                    password=ep.get("password", ""),
                )
                for i, ep in enumerate(data)
            ]
        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"Failed to parse PORTAINER_ENDPOINTS JSON: {e}")
            return _legacy_endpoint_list()
    return _legacy_endpoint_list()


def _legacy_endpoint_list() -> list[EndpointConfig]:
    """Endpoint unico usando variables legacy."""
    return [
        EndpointConfig(
            name="Default",
            url=cfg.portainer_url,
            user=cfg.portainer_user,
            password=cfg.portainer_pass,
        )
    ]


# ── Circuit Breaker ──────────────────────────────────────────────────────────

class CircuitBreaker:
    """Circuit breaker simple para evitar llamadas a Portainer cuando esta caido."""

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
            log.error(f"Circuit breaker OPEN after {self.failures} failures")
        elif self.state == "half-open":
            self.state = "open"

    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"

    def can_attempt(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            assert self.last_failure is not None
            elapsed = asyncio.get_event_loop().time() - self.last_failure
            if elapsed >= self.reset_timeout:
                self.state = "half-open"
                log.warning("Circuit breaker HALF-OPEN, probing...")
                return True
            return False
        # half-open: allow one probe
        return True

    def reset(self) -> None:
        self.failures = 0
        self.state = "closed"


# ── Portainer Client ─────────────────────────────────────────────────────────

class PortainerClient:
    """Cliente de la API REST de Portainer 2.x con autenticacion JWT."""

    def __init__(
        self,
        url: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.url = (url or cfg.portainer_url).rstrip("/")
        self.user = user or cfg.portainer_user
        self.password = password or cfg.portainer_pass
        self.endpoint_id: int = 1
        self._jwt: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self.circuit = CircuitBreaker()

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    # ── Auth ───────────────────────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        """Obtener JWT de Portainer."""
        async with self.session.post(
            f"{self.url}/api/auth",
            json={"username": self.user, "password": self.password},
        ) as resp:
            if resp.status == 200:
                data: _JSON = await resp.json()
                self._jwt = data.get("jwt", "")
                # Extraer endpoint_id si viene en la respuesta
                if "jwt" in data:
                    log.info(f"Authenticated with Portainer at {self.url}")
            else:
                text = await resp.text()
                raise PortainerError(
                    f"Auth fallida: {resp.status} {text[:200]}"
                )

    async def _ensure_auth(self) -> None:
        """Lazy auth: re-autenticar solo si el JWT expiro."""
        if self._jwt:
            return
        await self._authenticate()

    def _auth_headers(self) -> dict[str, str]:
        if not self._jwt:
            return {}
        return {"Authorization": f"Bearer {self._jwt}"}

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _get(
        self,
        path: str,
        params: Optional[dict] = None,
        retry_count: int = 0,
    ) -> _JSON:
        """GET con retry exponencial y circuit breaker."""
        if not self.circuit.can_attempt():
            raise PortainerUnavailable("Circuit breaker open")

        try:
            async with self.session.get(
                f"{self.url}/api/{path}",
                params=params,
                headers=self._auth_headers(),
            ) as resp:
                if resp.status == 401:
                    # JWT expirado — re-autenticar y reintentar
                    if retry_count == 0:
                        self._jwt = None
                        await self._ensure_auth()
                        return await self._get(path, params, retry_count=1)
                    raise PortainerError("Auth fallida tras reintento")

                if resp.status == 404:
                    raise PortainerNotFound(f"Recurso no encontrado: {path}")

                if resp.status >= 500:
                    if retry_count < cfg.max_retries:
                        delay = cfg.retry_base_delay * (2 ** retry_count)
                        log.warning(
                            f"Portainer {resp.status}, reintento {retry_count + 1} "
                            f"en {delay:.1f}s: {path}"
                        )
                        await asyncio.sleep(delay)
                        return await self._get(path, params, retry_count + 1)
                    raise PortainerError(f"Portainer error: {resp.status}")

                if resp.status != 200:
                    text = await resp.text()
                    raise PortainerError(f"{resp.status} {text[:200]}")

                return await resp.json()

        except aiohttp.ClientError as e:
            self.circuit.record_failure()
            if retry_count < cfg.max_retries:
                delay = cfg.retry_base_delay * (2 ** retry_count)
                log.warning(f"Network error {e}, reintento {retry_count + 1} en {delay:.1f}s")
                await asyncio.sleep(delay)
                return await self._get(path, params, retry_count + 1)
            raise PortainerError(f"Error de red: {e}") from e

    async def _post(
        self,
        path: str,
        data: Optional[_JSON] = None,
        retry_count: int = 0,
    ) -> _JSON:
        """POST con retry."""
        if not self.circuit.can_attempt():
            raise PortainerUnavailable("Circuit breaker open")

        try:
            async with self.session.post(
                f"{self.url}/api/{path}",
                json=data or {},
                headers=self._auth_headers(),
            ) as resp:
                if resp.status == 401:
                    if retry_count == 0:
                        self._jwt = None
                        await self._ensure_auth()
                        return await self._post(path, data, retry_count=1)
                    raise PortainerError("Auth fallida tras reintento")

                if resp.status >= 500:
                    if retry_count < cfg.max_retries:
                        delay = cfg.retry_base_delay * (2 ** retry_count)
                        await asyncio.sleep(delay)
                        return await self._post(path, data, retry_count + 1)
                    raise PortainerError(f"Portainer error: {resp.status}")

                if resp.status not in (200, 201, 204):
                    text = await resp.text()
                    raise PortainerError(f"{resp.status} {text[:200]}")

                if resp.status == 204:
                    return {}
                return await resp.json()

        except aiohttp.ClientError as e:
            self.circuit.record_failure()
            raise PortainerError(f"Error de red: {e}") from e

    # ── Containers ─────────────────────────────────────────────────────────────

    async def get_containers(self) -> list[dict]:
        """Obtener lista de contenedores del endpoint activo."""
        await self._ensure_auth()
        data = await self._get(f"endpoints/{self.endpoint_id}/docker/containers/json")
        return list(data) if data else []

    async def get_container_stats(self, container_id: str) -> _JSON:
        """Obtener stats de CPU/RAM/network de un contenedor."""
        await self._ensure_auth()
        params = {"stream": "false"}
        try:
            data = await self._get(
                f"endpoints/{self.endpoint_id}/docker/containers/{container_id}/stats",
                params=params,
            )
        except PortainerNotFound:
            return {}
        except Exception:
            return {}

        # Parsear bloque de stats
        cpu_delta = data.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0) - \
                    data.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
        system_delta = data.get("cpu_stats", {}).get("system_cpu_usage", 0) - \
                      data.get("precpu_stats", {}).get("system_cpu_usage", 0)
        num_cpus = data.get("cpu_stats", {}).get("online_cpus", 1)

        if system_delta > 0 and cpu_delta > 0:
            cpu_pct = round((cpu_delta / system_delta) * num_cpus * 100.0, 1)
        else:
            cpu_pct = 0.0

        mem_usage = data.get("memory_stats", {}).get("usage", 0)
        mem_limit = data.get("memory_stats", {}).get("limit", 1)
        mem_pct = round(mem_usage / mem_limit * 100, 1) if mem_limit else 0

        # Network I/O
        networks = data.get("networks", {}) or {}
        net_rx = net_tx = 0.0
        for net_data in networks.values():
            net_rx += net_data.get("rx_bytes", 0)
            net_tx += net_data.get("tx_bytes", 0)

        # Block I/O
        blkio = data.get("blkio_stats", {}).get("io_service_bytes_recursive", []) or []
        block_r = block_w = 0
        for entry in blkio:
            if entry.get("op", "").lower() == "read":
                block_r += entry.get("value", 0)
            elif entry.get("op", "").lower() == "write":
                block_w += entry.get("value", 0)

        return {
            "cpu_percent": cpu_pct,
            "memory_percent": mem_pct,
            "memory_used_mb": round(mem_usage / 1024 / 1024, 1),
            "memory_limit_mb": round(mem_limit / 1024 / 1024, 1),
            "network_rx_mb": round(net_rx / 1024 / 1024, 2),
            "network_tx_mb": round(net_tx / 1024 / 1024, 2),
            "block_read_mb": round(block_r / 1024 / 1024, 2),
            "block_write_mb": round(block_w / 1024 / 1024, 2),
        }

    async def get_container_logs(
        self, container_id: str, lines: int = 50
    ) -> str:
        """Obtener logs de un contenedor."""
        await self._ensure_auth()
        params = {"stdout": "true", "stderr": "true", "tail": str(lines)}
        try:
            data = await self._get(
                f"endpoints/{self.endpoint_id}/docker/containers/{container_id}/logs",
                params=params,
            )
            if isinstance(data, str):
                return data
            return json.dumps(data)
        except Exception as e:
            log.error(f"Error getting logs for {container_id}: {e}")
            return f"Error obteniendo logs: {e}"

    async def get_container_inspect(self, container_id: str) -> _JSON:
        """Obtener informacion detallada de un contenedor."""
        await self._ensure_auth()
        return await self._get(f"endpoints/{self.endpoint_id}/docker/containers/{container_id}/json")

    async def container_action(self, container_id: str, action: str) -> None:
        """Ejecutar una accion sobre un contenedor (start/stop/restart)."""
        await self._ensure_auth()
        path = f"endpoints/{self.endpoint_id}/docker/containers/{container_id}/{action}"
        await self._post(path)

    async def container_delete(self, container_id: str) -> None:
        """Eliminar un contenedor (primero detenerlo)."""
        await self._ensure_auth()
        path = f"endpoints/{self.endpoint_id}/docker/containers/{container_id}"
        await self._session.delete(
            f"{self.url}/api/{path}",
            headers=self._auth_headers(),
        )

    def build_container_summary(self, raw: dict) -> ContainerSummary:
        names = raw.get("Names", []) or []
        return ContainerSummary(
            id=raw.get("Id", ""),
            names=names,
            state=raw.get("State", ""),
            status=raw.get("Status", ""),
            image=raw.get("Image", ""),
            created=raw.get("Created", 0),
            ip=raw.get("IP", ""),
        )

    def build_container_detail(self, inspect: _JSON) -> ContainerDetail:
        raw = inspect.get("Config", {}) or {}
        inspect_state = inspect.get("State", {}) or {}
        host_config = inspect.get("HostConfig", {}) or {}
        config_section = inspect.get("Config", {}) or {}

        names = inspect.get("Name", "")
        return ContainerDetail(
            id=inspect.get("Id", ""),
            name=names.lstrip("/") if names else "unnamed",
            image=raw.get("Image", "unknown"),
            state=inspect_state.get("Status", "unknown"),
            started_at=inspect_state.get("StartedAt", ""),
            restart_count=inspect_state.get("RestartCount", 0),
            network_mode=host_config.get("NetworkMode", "default"),
            memory_limit=host_config.get("Memory", 0),
            env_vars=raw.get("Env", []),
        )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# ── Singleton ────────────────────────────────────────────────────────────────

_client: Optional[PortainerClient] = None
_active_endpoint_name: Optional[str] = None


def get_client() -> PortainerClient:
    """Obtener cliente singleton (lazy init)."""
    global _client
    if _client is None:
        _client = PortainerClient()
    return _client


def get_active_endpoint_name() -> str:
    """Nombre del endpoint activo."""
    global _active_endpoint_name
    return _active_endpoint_name or "Default"


async def close_client() -> None:
    """Cerrar sesion y limpiar cliente singleton."""
    global _client, _active_endpoint_name
    if _client:
        await _client.close()
        _client = None


async def switch_endpoint(name: str) -> bool:
    """Cambiar endpoint activo. Retorna True si el nombre existe."""
    global _client, _active_endpoint_name

    endpoints = get_endpoint_configs()
    target = next((ep for ep in endpoints if ep.name == name), None)
    if target is None:
        return False

    # Cerrar cliente anterior
    if _client:
        await _client.close()

    _client = PortainerClient(
        url=target.url,
        user=target.user,
        password=target.password,
    )
    _active_endpoint_name = target.name
    log.info(f"Switched to endpoint: {name} ({target.url})")
    return True


# ── Error types ───────────────────────────────────────────────────────────────

class PortainerError(Exception):
    pass


class PortainerNotFound(PortainerError):
    pass


class PortainerUnavailable(PortainerError):
    pass