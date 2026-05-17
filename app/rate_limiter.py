"""Rate limiter por usuario — evita spam que sature la API de Portainer."""
import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from app.logger import log


@dataclass
class RateLimitConfig:
    """Configuración del rate limiter."""
    max_calls: int = 5          # máximo comandos por ventana
    window_seconds: float = 60.0 # ventana de tiempo en segundos


@dataclass
class UserRatelimitEntry:
    """Tracking de comandos por usuario."""
    calls: list[float] = field(default_factory=list)  # timestamps
    
    def is_rate_limited(self, max_calls: int, window: float) -> bool:
        """True si el usuario excedió el límite."""
        now = time.monotonic()
        # Limpiar llamadas antiguas
        self.calls = [t for t in self.calls if now - t < window]
        return len(self.calls) >= max_calls
    
    def record_call(self):
        self.calls.append(time.monotonic())


class RateLimiter:
    """Rate limiter por Telegram user ID.
    
    Uso básico:
        limiter = RateLimiter()
        async def handler(update, ctx):
            if not limiter.check(update.effective_user.id):
                await update.message.reply_text("⛔ Demasiados comandos. Espera un momento.")
                return
            # ... resto del handler
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        from app.config import cfg
        if config is None:
            config = RateLimitConfig(
                max_calls=cfg.rate_limit_max_calls,
                window_seconds=cfg.rate_limit_window,
            )
        self.config = config
        self._users: dict[int, UserRatelimitEntry] = defaultdict(UserRatelimitEntry)
        self._lock = asyncio.Lock()
    
    def check(self, user_id: int) -> bool:
        """Verificar si el usuario puede continuar. Thread-safe."""
        entry = self._users[user_id]
        if entry.is_rate_limited(self.config.max_calls, self.config.window_seconds):
            log.warning(f"Rate limit exceeded for user {user_id}")
            return False
        return True
    
    def record(self, user_id: int):
        """Registrar una llamada del usuario."""
        self._users[user_id].record_call()
    
    def get_retry_after(self, user_id: int) -> float:
        """Obtener segundos hasta que el rate limit se resetee."""
        entry = self._users[user_id]
        if not entry.calls:
            return 0.0
        now = time.monotonic()
        oldest = min(entry.calls)
        return max(0.0, self.config.window_seconds - (now - oldest))
    
    def clear(self, user_id: int):
        """Limpiar historial de un usuario (útil para admins)."""
        if user_id in self._users:
            del self._users[user_id]


# Instancia global
rate_limiter = RateLimiter()


def rate_limit(func):
    """Decorador para aplicar rate limiting a un handler de callback.
    
    Uso:
        @rate_limit
        async def button_handler(update, ctx):
            ...
    """
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not rate_limiter.check(user_id):
            retry_after = int(rate_limiter.get_retry_after(user_id)) or 60
            await update.callback_query.answer(
                text=f"⛔ Demasiados comandos. Espera {retry_after}s.",
                show_alert=True,
            )
            return
        rate_limiter.record(user_id)
        return await func(update, ctx)
    return wrapper
