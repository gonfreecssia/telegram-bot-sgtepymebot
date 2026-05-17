"""Pytest fixtures para los tests."""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_env(monkeypatch):
    """Env vars de test."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
    monkeypatch.setenv("PORTAINER_URL", "http://localhost:9000")
    monkeypatch.setenv("PORTAINER_USER", "admin")
    monkeypatch.setenv("PORTAINER_PASSWORD", "testpass")


@pytest.fixture
def event_loop():
    """Event loop para tests async."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_container():
    """Contenedor de ejemplo desde API."""
    return {
        "Id": "abc123def456789012345678901234567890123456789012345678901234",
        "Names": ["/nginx-proxy"],
        "Image": "nginx:latest",
        "State": "running",
        "Status": "Up 2 hours",
        "Ports": [
            {"PublicPort": 80, "PrivatePort": 80, "Type": "tcp"},
            {"PublicPort": 443, "PrivatePort": 443, "Type": "tcp"},
        ],
    }


@pytest.fixture
def sample_container_inspect(sample_container):
    """Inspect data de ejemplo."""
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat()
    return {
        "Id": sample_container["Id"],
        "Name": "/nginx-proxy",
        "Image": "nginx:latest",
        "State": {
            "Status": "running",
            "Running": True,
            "StartedAt": started,
            "RestartCount": 0,
        },
        "Config": {
            "Env": [
                "NGINX_PORT=80",
                "PASSWORD=secret123",  # Should be filtered
                "NGINX_HOST=example.com",
            ],
        },
        "HostConfig": {
            "NetworkMode": "bridge",
            "Memory": 256 * 1024 * 1024,
        },
        "Created": "2024-01-01T10:00:00.000000000Z",
    }


@pytest.fixture
def mock_aiohttp_success(sample_container, sample_container_inspect):
    """Mock de aiohttp que retorna datos válidos."""
    import respx
    from httpx import Response
    
    # Auth endpoint
    respx.post("http://localhost:9000/api/auth").mock(
        return_value=Response(200, json={"jwt": "fake_token"})
    )
    # Endpoints endpoint
    respx.get("http://localhost:9000/api/endpoints").mock(
        return_value=Response(200, json=[{"Id": 3}])
    )
    # Containers list
    respx.get(f"http://localhost:9000/api/endpoints/3/docker/containers/json?all=1").mock(
        return_value=Response(200, json=[sample_container])
    )
    # Container inspect
    cid = sample_container["Id"]
    respx.get(f"http://localhost:9000/api/endpoints/3/docker/containers/{cid}/json").mock(
        return_value=Response(200, json=sample_container_inspect)
    )
    
    return respx
