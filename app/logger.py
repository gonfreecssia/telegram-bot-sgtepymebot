"""Logging estructurado para todo el bot."""
import logging
import sys
import uuid
from contextvars import ContextVar
from functools import wraps
from typing import Callable

# ── Context para request IDs ──────────────────────────────────────
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Obtener request ID actual o generar uno nuevo."""
    rid = request_id_var.get()
    if not rid:
        rid = uuid.uuid4().hex[:8]
        request_id_var.set(rid)
    return rid


def with_request_id(func: Callable) -> Callable:
    """Decorador que inyecta request ID en cada llamada."""
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        rid = get_request_id()
        return await func(*args, **kwargs)
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        rid = get_request_id()
        return func(*args, **kwargs)
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


class StructuredFormatter(logging.Formatter):
    """Formateador que incluye request_id y módulo."""
    
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get() or "-"
        record.request_id = rid
        return (
            f"%(asctime)s | %(levelname)-8s | %(name)-20s | "
            f"[%(request_id)s] | %(message)s"
        ) % record.__dict__


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configurar logging estructurado para toda la aplicación."""
    logger = logging.getLogger("telegram_bot")
    logger.setLevel(level)
    
    # Evitar duplicados
    if logger.handlers:
        return logger
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    
    # Reducir ruido de librerías
    for noisy in ("aiohttp", "urllib3", "telegram"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    
    return logger


# Logger singleton
log = setup_logging()
