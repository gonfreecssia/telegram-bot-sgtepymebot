"""Configuración centralizada del bot con validación robusta."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Configuración del bot. Carga de variables de entorno con defaults."""

    # ── Telegram ──────────────────────────────────────────────
    telegram_token: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )

    # ── Portainer ─────────────────────────────────────────────
    portainer_url: str = field(
        default_factory=lambda: os.getenv("PORTAINER_URL", "http://192.168.1.184:9000")
    )
    portainer_user: str = field(
        default_factory=lambda: os.getenv("PORTAINER_USER", "admin")
    )
    portainer_pass: str = field(
        default_factory=lambda: os.getenv("PORTAINER_PASSWORD", "")
    )

    # ── Bot ───────────────────────────────────────────────────
    bot_container_name: str = field(
        default_factory=lambda: os.getenv("BOT_CONTAINER_NAME", "")
    )

    # ── Retry ────────────────────────────────────────────────
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("MAX_RETRIES", "3"))
    )
    retry_base_delay: float = field(
        default_factory=lambda: float(os.getenv("RETRY_BASE_DELAY", "1.0"))
    )

    # ── Rate limiting ─────────────────────────────────────────
    rate_limit_max_calls: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_MAX_CALLS", "5"))
    )
    rate_limit_window: float = field(
        default_factory=lambda: float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60.0"))
    )

    # ── Health server ─────────────────────────────────────────
    health_port: int = field(
        default_factory=lambda: int(os.getenv("HEALTH_PORT", "8080"))
    )

    # ── Whitelist / Seguridad ─────────────────────────────────
    allowed_telegram_ids: str = field(
        default_factory=lambda: os.getenv("ALLOWED_TELEGRAM_IDS", "")
    )  # comma-separated: "472171448,123456789"

    # ── Multi-endpoint (F5) ────────────────────────────────────
    portainer_endpoints_json: str = field(
        default_factory=lambda: os.getenv("PORTAINER_ENDPOINTS", "")
    )  # JSON array de endpoints

    # ── Reportes programados ──────────────────────────────────
    report_schedule: str = field(
        default_factory=lambda: os.getenv("REPORT_SCHEDULE", "")
    )  # cron: "0 9 * * *" (diario a las 9am)
    report_telegram_ids: str = field(
        default_factory=lambda: os.getenv("REPORT_TELEGRAM_IDS", "")
    )

    # ── Logging ───────────────────────────────────────────────
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    log_file: str = field(
        default_factory=lambda: os.getenv("LOG_FILE", "/var/log/bot.log")
    )

    def get_allowed_ids(self) -> set[int]:
        """Parsear ALLOWED_TELEGRAM_IDS a set de enteros."""
        if not self.allowed_telegram_ids:
            return set()
        return set(int(uid.strip()) for uid in self.allowed_telegram_ids.split(",") if uid.strip())

    def get_report_ids(self) -> set[int]:
        """Parsear REPORT_TELEGRAM_IDS a set de enteros."""
        if not self.report_telegram_ids:
            return set()
        return set(int(uid.strip()) for uid in self.report_telegram_ids.split(",") if uid.strip())

    def validate(self) -> list[str]:
        """Validación completa de configuración. Retorna lista de errores."""
        errors = []

        if not self.telegram_token:
            errors.append(
                "TELEGRAM_BOT_TOKEN no está definido. "
                "Obtén uno de @BotFather en Telegram."
            )

        if not self.portainer_url:
            errors.append("PORTAINER_URL no está definido.")
        else:
            # Basic URL format check
            if not self.portainer_url.startswith(("http://", "https://")):
                errors.append(
                    f"PORTAINER_URL '{self.portainer_url}' debe empezar con http:// o https://"
                )

        if not self.portainer_pass:
            errors.append(
                "PORTAINER_PASSWORD no está definido. "
                "Verifica la contraseña de admin en Portainer."
            )

        if self.max_retries < 0:
            errors.append(f"MAX_RETRIES debe ser ≥ 0,got {self.max_retries}")

        if self.retry_base_delay <= 0:
            errors.append(f"RETRY_BASE_DELAY debe ser > 0, got {self.retry_base_delay}")

        if self.rate_limit_max_calls <= 0:
            errors.append(
                f"RATE_LIMIT_MAX_CALLS debe ser > 0, got {self.rate_limit_max_calls}"
            )

        if self.rate_limit_window <= 0:
            errors.append(
                f"RATE_LIMIT_WINDOW_SECONDS debe ser > 0, got {self.rate_limit_window}"
            )

        if self.health_port <= 0 or self.health_port > 65535:
            errors.append(f"HEALTH_PORT debe estar entre 1 y 65535, got {self.health_port}")

        return errors


# Singleton global
cfg = Config()
