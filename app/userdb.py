"""Base de datos SQLite para whitelist de usuarios (S1)."""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

from app.config import cfg

log = logging.getLogger(__name__)

# ── DB path (volumen persistente en Docker) ──────────────────────────────────
_DB_PATH = os.getenv("BOT_DB_PATH", "/data/bot.db")


def _get_db_path() -> Path:
    """Obtener ruta de la DB, creando el directorio si es necesario."""
    path = Path(_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db() -> None:
    """Crear las tablas de la DB si no existen."""
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                telegram_id INTEGER PRIMARY KEY,
                dark_mode INTEGER DEFAULT 0,
                language TEXT DEFAULT "es",
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
        
            CREATE TABLE IF NOT EXISTS allowed_users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                added_at TEXT DEFAULT (datetime('now')),
                active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                telegram_id INTEGER PRIMARY KEY,
                dark_mode INTEGER DEFAULT 0,
                language TEXT DEFAULT "es",
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
        
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                command TEXT,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()
        log.info(f"Database initialized at {_get_db_path()}")
    except Exception as e:
        log.error(f"Failed to initialize database: {e}")


def is_user_allowed(telegram_id: int) -> bool:
    """Verificar si un usuario está en la whitelist.
    
    Si ALLOWED_TELEGRAM_IDS está configurado en env var, se usa ese como
    whitelist global (todos los usuarios fuera de la lista quedan bloqueados).
    La DB SQLite sirve para whitelist granular por usuario.
    """
    # Si no hay restricciones configuradas, permitir a todos
    allowed_ids = cfg.get_allowed_ids()
    if not allowed_ids:
        return True
    return telegram_id in allowed_ids


def add_allowed_user(telegram_id: int, username: Optional[str] = None) -> bool:
    """Agregar un usuario a la whitelist (INSERT OR REPLACE)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.execute(
            "INSERT OR REPLACE INTO allowed_users (telegram_id, username, active) VALUES (?, ?, 1)",
            (telegram_id, username),
        )
        conn.commit()
        conn.close()
        log.info(f"User {telegram_id} ({username}) added to whitelist")
        return True
    except Exception as e:
        log.error(f"Failed to add user {telegram_id} to whitelist: {e}")
        return False


def remove_allowed_user(telegram_id: int) -> bool:
    """Quitar un usuario de la whitelist (marcar como inactivo)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.execute(
            "UPDATE allowed_users SET active = 0 WHERE telegram_id = ?",
            (telegram_id,),
        )
        conn.commit()
        conn.close()
        log.info(f"User {telegram_id} removed from whitelist")
        return True
    except Exception as e:
        log.error(f"Failed to remove user {telegram_id}: {e}")
        return False


def list_allowed_users() -> list[tuple[int, Optional[str], str]]:
    """Listar todos los usuarios activos en la whitelist."""
    try:
        conn = sqlite3.connect(_get_db_path())
        rows = conn.execute(
            "SELECT telegram_id, username, added_at FROM allowed_users WHERE active = 1 ORDER BY added_at"
        ).fetchall()
        conn.close()
        return rows
    except Exception as e:
        log.error(f"Failed to list allowed users: {e}")
        return []


def log_usage(telegram_id: int, command: str) -> None:
    """Registrar uso de comando (para métricas)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.execute(
            "INSERT INTO usage_log (user_id, command) VALUES (?, ?)",
            (telegram_id, command),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # No fallar por logging

def set_user_pref(telegram_id: int, **kwargs) -> bool:
    """Actualizar preferencias de un usuario (dark_mode, language, etc)."""
    try:
        conn = sqlite3.connect(_get_db_path())
        for key, value in kwargs.items():
            if key in ("dark_mode", "language"):
                conn.execute(
                    f"INSERT OR REPLACE INTO user_prefs (telegram_id, {key}, updated_at) VALUES (?, ?, datetime('now'))",
                    (telegram_id, value),
                )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.error(f"Failed to set user pref {kwargs} for {telegram_id}: {e}")
        return False


def get_user_pref(telegram_id: int, key: str, default=None):
    """Obtener una preferencia específica de un usuario."""
    try:
        conn = sqlite3.connect(_get_db_path())
        row = conn.execute(
            f"SELECT {key} FROM user_prefs WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def get_all_user_ids() -> list[int]:
    """Obtener todos los telegram IDs de usuarios activos."""
    try:
        conn = sqlite3.connect(_get_db_path())
        rows = conn.execute(
            "SELECT telegram_id FROM allowed_users WHERE active = 1"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        log.error(f"Failed to get all user ids: {e}")
        return []
