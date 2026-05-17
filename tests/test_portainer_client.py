"""Tests para portainer_client."""
import pytest
import respx
from httpx import Response

from app.portainer_client import PortainerClient, CircuitBreaker, with_retry, get_client
from app.config import cfg


class TestCircuitBreaker:
    """Tests del circuit breaker."""
    
    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        assert not cb.is_open()
        assert cb.state == "closed"
    
    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open()  # Not yet
        cb.record_failure()  # 3rd failure
        assert cb.is_open()
        assert cb.state == "open"
    
    def test_success_resets_failures(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failures == 0
        assert cb.state == "closed"


class TestContainerSummary:
    """Tests del modelo ContainerSummary."""
    
    def test_short_id(self):
        from app.models import ContainerSummary
        cs = ContainerSummary(
            id="abc123def456789",
            name="nginx",
            image="nginx:latest",
            state="running",
            status="Up 5 minutes",
        )
        assert cs.short_id == "abc123def456"
        assert cs.emoji == "🟢"
        assert cs.is_running is True
    
    def test_stopped_container_emoji(self):
        from app.models import ContainerSummary
        cs = ContainerSummary(
            id="abc123",
            name="mysql",
            image="mysql:8",
            state="exited",
            status="Exited (1)",
        )
        assert cs.emoji == "🔴"
        assert cs.is_running is False


class TestPortainerClient:
    """Tests del cliente de Portainer."""
    
    @pytest.mark.asyncio
    async def test_auth_success(self, mock_env):
        with respx.mock:
            respx.post("http://localhost:9000/api/auth").mock(
                return_value=Response(200, json={"jwt": "test_token_123"})
            )
            client = PortainerClient(
                url="http://localhost:9000",
                user="admin",
                pw="testpass"
            )
            token = await client.auth()
            assert token == "test_token_123"
            assert client._jwt == "test_token_123"
    
    @pytest.mark.asyncio
    async def test_get_endpoint_id(self, mock_env):
        with respx.mock:
            respx.post("http://localhost:9000/api/auth").mock(
                return_value=Response(200, json={"jwt": "t"}))
            respx.get("http://localhost:9000/api/endpoints").mock(
                return_value=Response(200, json=[{"Id": 5}]))
            
            client = PortainerClient()
            ep_id = await client.get_endpoint_id()
            assert ep_id == 5
            # Cached
            assert client._endpoint_id == 5
    
    @pytest.mark.asyncio
    async def test_get_containers(self, mock_env, sample_container):
        with respx.mock:
            respx.post("http://localhost:9000/api/auth").mock(
                return_value=Response(200, json={"jwt": "t"}))
            respx.get("http://localhost:9000/api/endpoints").mock(
                return_value=Response(200, json=[{"Id": 3}]))
            respx.get("http://localhost:9000/api/endpoints/3/docker/containers/json?all=1").mock(
                return_value=Response(200, json=[sample_container]))
            
            client = PortainerClient()
            containers = await client.get_containers()
            assert len(containers) == 1
            assert containers[0]["Names"][0] == "/nginx-proxy"
            assert containers[0]["State"] == "running"
    
    def test_build_container_summary(self, sample_container):
        client = PortainerClient()
        cs = client.build_container_summary(sample_container)
        assert cs.name == "nginx-proxy"
        assert cs.image == "nginx:latest"
        assert cs.state == "running"
        assert cs.short_id == "abc123def456"
        assert cs.emoji == "🟢"
    
    def test_build_container_detail(self, sample_container_inspect):
        client = PortainerClient()
        cd = client.build_container_detail(sample_container_inspect)
        assert cd.name == "nginx-proxy"
        assert cd.restart_count == 0
        assert cd.network_mode == "bridge"
        assert cd.memory_limit == 256 * 1024 * 1024
        # Password should be filtered (safe_env_count excludes it)
        # safe_env_count counts only non-sensitive, so PASSWORD is excluded
        assert cd.safe_env_count() == 2  # NGINX_PORT and NGINX_HOST
        assert cd.uptime_str != "N/A"
        assert cd.memory_str == "256MB"
