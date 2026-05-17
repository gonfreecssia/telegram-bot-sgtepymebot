"""Alert engine — detecta cambios de estado de contenedores y notifica."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.config import cfg
from app.logger import log
from app.portainer_client import get_client

logger = logging.getLogger(__name__)


class AlertType(Enum):
    CONTAINER_DOWN = "down"
    CONTAINER_UP = "up"
    CONTAINER_RESTARTED = "restarted"


@dataclass
class AlertRule:
    """Regla de alerta configurada por usuario."""
    container_name: str          # nombre o prefijo para matchear
    alert_type: AlertType        # qué tipo de cambio notificar
    telegram_ids: set[int]       # a quién notificar
    enabled: bool = True


@dataclass
class ContainerSnapshot:
    """Snapshot del estado conocido de un contenedor."""
    id: str
    name: str
    state: str
    restart_count: int = 0
    last_notified: dict[AlertType, str] = field(default_factory=dict)


class AlertEngine:
    """Motor de alertas — polling periódico que detecta cambios de estado.

    Uso:
        engine = AlertEngine(app.bot)
        asyncio.create_task(engine.start(interval_seconds=120))
    """

    def __init__(self, bot) -> None:
        self.bot = bot
        self._snapshots: dict[str, ContainerSnapshot] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def _build_rules(self) -> list[AlertRule]:
        """Construir reglas de alerta desde config.

        Formato env ALERT_RULES (JSON array):
        [{"name": "nginx", "types": ["down","up"], "ids": [472171448]}]

        O más simple, si no está configurado: generar reglas desde
        los contenedores con REPORT_TELEGRAM_IDS.
        """
        import json, os as _os
        rules_json = _os.getenv("ALERT_RULES", "").strip()
        if not rules_json:
            return []
        try:
            rules_data = json.loads(rules_json)
            rules = []
            for r in rules_data:
                for t in r.get("types", []):
                    try:
                        at = AlertType(t)
                        rules.append(AlertRule(
                            container_name=r["name"],
                            alert_type=at,
                            telegram_ids=set(r.get("ids", [])) or cfg.get_report_ids(),
                        ))
                    except ValueError:
                        pass
            return rules
        except Exception:
            return []

    async def _check_and_notify(self) -> None:
        """Verificar estado actual y notificar cambios."""
        client = get_client()
        try:
            containers = await client.get_containers()
        except Exception as e:
            logger.warning(f"Alert engine: no se pudo obtener contenedores: {e}")
            return

        rules = self._build_rules()
        now = datetime.now().strftime("%d/%m %H:%M")

        for c in containers:
            name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
            cid = c.get("Id", "")[:12]
            state = c.get("State", "unknown")
            restart_count = 0

            # Obtener restart count si está corriendo
            try:
                inspect = await client.get_container_inspect(c["Id"])
                restart_count = inspect.get("State", {}).get("RestartCount", 0)
            except Exception:
                pass

            is_own = (
                name == cfg.bot_container_name
                or cid == cfg.bot_container_name
            )

            # Inicializar snapshot si no existe
            if cid not in self._snapshots:
                self._snapshots[cid] = ContainerSnapshot(
                    id=cid, name=name, state=state, restart_count=restart_count
                )
                continue

            snap = self._snapshots[cid]
            prev_state = snap.state
            prev_restart = snap.restart_count

            # Detectar cambios
            changes: list[tuple[AlertType, str]] = []

            # Estado cambió
            if prev_state != state:
                if state == "running" and prev_state != "running":
                    changes.append((AlertType.CONTAINER_UP, now))
                elif state != "running" and prev_state == "running":
                    changes.append((AlertType.CONTAINER_DOWN, now))

            # Restart count cambió (mientras estaba corriendo)
            if state == "running" and prev_restart < restart_count:
                changes.append((AlertType.CONTAINER_RESTARTED, now))

            # Enviar notificaciones
            for alert_type, ts in changes:
                # Filtrar por reglas
                matching_rules = [
                    r for r in rules
                    if r.enabled
                    and r.alert_type == alert_type
                    and (
                        r.container_name.lower() in name.lower()
                        or r.container_name == "*"
                    )
                ]

                # Si no hay reglas específicas, notificar a todos en REPORT_TELEGRAM_IDS
                if not matching_rules:
                    target_ids = cfg.get_report_ids()
                else:
                    target_ids = set()
                    for r in matching_rules:
                        target_ids.update(r.telegram_ids)

                for user_id in target_ids:
                    emoji = {
                        AlertType.CONTAINER_DOWN: "🔴",
                        AlertType.CONTAINER_UP: "🟢",
                        AlertType.CONTAINER_RESTARTED: "🔄",
                    }[alert_type]

                    msg = {
                        AlertType.CONTAINER_DOWN: (
                            f"{emoji} *CONTENEDOR CAÍDO*\n"
                            f"`{name}` dejó de funcionar\n"
                            f"Último estado: `{state}`"
                        ),
                        AlertType.CONTAINER_UP: (
                            f"{emoji} *CONTENEDOR ACTIVO*\n"
                            f"`{name}` se recuperó\n"
                            f"Estado: `{state}`"
                        ),
                        AlertType.CONTAINER_RESTARTED: (
                            f"{emoji} *CONTENEDOR REINICIADO*\n"
                            f"`{name}` tuvo un restart\n"
                            f"Restart count: {restart_count}"
                        ),
                    }[alert_type]

                    try:
                        await self.bot.send_message(
                            chat_id=user_id,
                            text=msg,
                            parse_mode="Markdown",
                        )
                        logger.info(f"Alert {alert_type.value} sent to {user_id} for {name}")
                    except Exception as e:
                        logger.error(f"Failed to send alert to {user_id}: {e}")

                # Marcar como notificado
                snap.last_notified[alert_type] = ts

            # Actualizar snapshot
            snap.state = state
            snap.restart_count = restart_count

    async def start(self, interval_seconds: int = 120) -> None:
        """Iniciar el loop de polling de alertas."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(interval_seconds))
        log.info(f"Alert engine started (interval: {interval_seconds}s)")

    async def stop(self) -> None:
        """Detener el loop de alertas."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Alert engine stopped")

    async def _run(self, interval_seconds: int) -> None:
        """Loop principal del alert engine."""
        while self._running:
            try:
                await self._check_and_notify()
            except Exception as e:
                log.error(f"Alert engine error: {e}")
            await asyncio.sleep(interval_seconds)


# Instancia global (se crea en bot.py)
_alert_engine = None


def get_alert_engine(bot) -> AlertEngine:
    global _alert_engine
    if _alert_engine is None:
        _alert_engine = AlertEngine(bot)
    return _alert_engine
