"""Internacionalización (i18n) — español/inglés para el bot."""
from __future__ import annotations

import os
from enum import Enum

from app.userdb import get_user_pref


class Lang(str, Enum):
    ES = "es"
    EN = "en"


# ── Mensajes en español ───────────────────────────────────────────────────────
ES = {
    # Main menu
    "menu_title": "📋 Menú principal",
    "menu_status": "📊 Estado",
    "menu_help": "❓ Ayuda",
    "menu_config": "⚙️ Configuración",

    # Status
    "status_ok": "🟢 Bot operativo",
    "status_degraded": "🟡 Bot operativo — Portainer no disponible",
    "status_containers": "📦 Contenedores: {running}/{total} activos",

    # Config menu
    "config_title": "⚙️ Configuración — Portainer",
    "config_validate": "🔍 Validar Servidor",
    "config_avail": "📊 Disponibilidad",
    "config_list": "📋 Contenedores",
    "config_detail": "📄 Detalle",
    "config_actions": "🎮 Acciones",
    "config_back": "🔙 Volver",

    # Alerts
    "alert_down": "🔴 *CONTENEDOR CAÍDO*\n`{name}` dejó de funcionar\nEstado: `{state}`",
    "alert_up": "🟢 *CONTENEDOR ACTIVO*\n`{name}` se recuperó\nEstado: `{state}`",
    "alert_restarted": "🔄 *CONTENEDOR REINICIADO*\n`{name}` tuvo un restart\nRestart: {count}",

    # Actions
    "action_start": "iniciado",
    "action_stop": "detenido",
    "action_restart": "reiniciado",
    "action_remove": "eliminado",
    "action_start_emoji": "▶️",
    "action_stop_emoji": "⛔",
    "action_restart_emoji": "🔄",
    "action_remove_emoji": "🗑️",

    # Errors
    "error_portainer": "❌ Error de conexión a Portainer",
    "error_generic": "❌ Error: {msg}",
    "error_not_allowed": "⛔ No tienes permiso para usar este bot.",
    "error_rate_limit": "⛔ Demasiados comandos. Espera {secs}s.",
    "error_not_found": "❌ No encontrado: `{name}`",
    "error_own_container": "⚠️ No puedes {action} el contenedor del bot.",

    # Processing
    "processing": "⏳ Procesando...",

    # Help
    "help_text": (
        "📖 *Ayuda del Bot de Monitorización*\n\n"
        "/start — Iniciar bot\n"
        "/menu — Abrir menú principal\n"
        "/help — Mostrar ayuda\n"
        "/logs \u003ccontainer\u003e [líneas] — Ver últimos logs\n"
        "/stats [container] — Uso de CPU/RAM\n\n"
        "⚠️ Rate limit: 5 comandos por minuto."
    ),

    # Stats
    "stats_title": "📊 *Uso de recursos* — contenedores en ejecución",
    "stats_na": "Stats no disponibles",

    # Logs
    "logs_title": "{lines} últimos logs de `{name}`",
    "logs_truncated": "... _(truncado)_",
}

# ── Mensajes en inglés ──────────────────────────────────────────────────────
EN = {
    # Main menu
    "menu_title": "📋 Main menu",
    "menu_status": "📊 Status",
    "menu_help": "❓ Help",
    "menu_config": "⚙️ Settings",

    # Status
    "status_ok": "🟢 Bot operational",
    "status_degraded": "🟡 Bot operational — Portainer unavailable",
    "status_containers": "📦 Containers: {running}/{total} running",

    # Config menu
    "config_title": "⚙️ Settings — Portainer",
    "config_validate": "🔍 Validate Server",
    "config_avail": "📊 Availability",
    "config_list": "📋 Containers",
    "config_detail": "📄 Detail",
    "config_actions": "🎮 Actions",
    "config_back": "🔙 Back",

    # Alerts
    "alert_down": "🔴 *CONTAINER DOWN*\n`{name}` stopped working\nState: `{state}`",
    "alert_up": "🟢 *CONTAINER UP*\n`{name}` recovered\nState: `{state}`",
    "alert_restarted": "🔄 *CONTAINER RESTARTED*\n`{name}` had a restart\nRestart count: {count}",

    # Actions
    "action_start": "started",
    "action_stop": "stopped",
    "action_restart": "restarted",
    "action_remove": "removed",
    "action_start_emoji": "▶️",
    "action_stop_emoji": "⛔",
    "action_restart_emoji": "🔄",
    "action_remove_emoji": "🗑️",

    # Errors
    "error_portainer": "❌ Portainer connection error",
    "error_generic": "❌ Error: {msg}",
    "error_not_allowed": "⛔ You are not allowed to use this bot.",
    "error_rate_limit": "⛔ Too many commands. Wait {secs}s.",
    "error_not_found": "❌ Not found: `{name}`",
    "error_own_container": "⚠️ You cannot {action} the bot's own container.",

    # Processing
    "processing": "⏳ Processing...",

    # Help
    "help_text": (
        "📖 *Bot Help*\n\n"
        "/start — Start bot\n"
        "/menu — Open main menu\n"
        "/help — Show this help\n"
        "/logs \u003ccontainer\u003e [lines] — View container logs\n"
        "/stats [container] — CPU/RAM usage\n\n"
        "⚠️ Rate limit: 5 commands per minute."
    ),

    # Stats
    "stats_title": "📊 *Resource usage* — running containers",
    "stats_na": "Stats not available",

    # Logs
    "logs_title": "Last {lines} logs of `{name}`",
    "logs_truncated": "... _(truncated)_",
}

_MESSAGES: dict[str, dict[str, str]] = {"es": ES, "en": EN}


def t(key: str, user_id: int | None = None, **kwargs) -> str:
    """Obtener mensaje traducido.

    Args:
        key: clave del mensaje (ej: "status_ok")
        user_id: ID del usuario para detectar idioma
        **kwargs: variables de formato (ej: name="{name}")
    """
    lang_code = "es"
    if user_id:
        lang_pref = get_user_pref(user_id, "language", None)
        if lang_pref in ("es", "en"):
            lang_code = lang_pref

    messages = _MESSAGES.get(lang_code, ES)
    template = messages.get(key, ES.get(key, key))
    return template.format(**kwargs)
