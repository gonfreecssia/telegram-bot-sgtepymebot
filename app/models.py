"""Modelos de datos para el bot."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContainerSummary:
    """Resumen de un contenedor (de /containers/json)."""
    id: str
    name: str
    image: str
    state: str
    status: str
    ports: list[dict] = field(default_factory=list)

    @property
    def short_id(self) -> str:
        return self.id[:12]

    @property
    def is_running(self) -> bool:
        return self.state == "running"

    @property
    def emoji(self) -> str:
        return "🟢" if self.is_running else "🔴"


@dataclass
class ContainerDetail:
    """Detalle extendido de un contenedor (de /containers/{id}/json)."""
    id: str
    name: str
    image: str
    state: str
    created: str = ""
    started_at: str = ""
    restart_count: int = 0
    network_mode: str = "default"
    memory_limit: int = 0
    env_vars: list[str] = field(default_factory=list)

    @property
    def short_id(self) -> str:
        return self.id[:12]

    @property
    def is_running(self) -> bool:
        return self.state == "running"

    @property
    def emoji(self) -> str:
        return "🟢" if self.is_running else "🔴"

    @property
    def uptime_str(self) -> str:
        """Formatear uptime desde timestamp ISO."""
        if not self.is_running or not self.started_at:
            return "N/A"
        try:
            from datetime import datetime, timezone
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta = now - started
            hours, rem = divmod(int(delta.total_seconds()), 3600)
            minutes, _ = divmod(rem, 60)
            if hours > 24:
                return f"{hours // 24}d {hours % 24}h"
            elif hours > 0:
                return f"{hours}h {minutes}m"
            else:
                return f"{minutes}m"
        except Exception:
            return "desconocido"

    @property
    def memory_str(self) -> str:
        if self.memory_limit > 0:
            return f"{self.memory_limit / 1024 / 1024:.0f}MB"
        return "sin límite"

    def safe_env_count(self) -> int:
        """Count non-sensitive env vars."""
        sensitive = {"PASSWORD", "TOKEN", "SECRET", "KEY", "API_KEY", "CREDENTIAL", "PRIVATE"}
        return sum(
            1 for e in self.env_vars
            if not any(s in e.upper() for s in sensitive)
        )
