"""Bot principal — arquitectura modular, todas las mejoras de Mes 1 y Mes 2."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from app.config import cfg
from app.logger import log
from app.portainer_client import get_client, close_client
from app.health import start_health_server, stop_health_server
from app.rate_limiter import rate_limit
from app.userdb import init_db
from app.security import whitelist_middleware
from app.scheduled_reports import setup_scheduled_tasks

from app.handlers.callback_data import parse_callback, CallbackActionType
from app.handlers.status import (
    handle_estado,
    handle_ayuda,
    handle_config_menu,
    handle_cfg_server,
    handle_cfg_avail,
    handle_cfg_list,
    handle_cfg_status,
    handle_back_config,
    handle_back_main,
)
from app.handlers.actions import handle_cfg_actions, handle_detail, handle_container_action
from app.handlers.logs import logs


# ── Signal handlers ───────────────────────────────────────────────────────────

async def shutdown_signal_handler(sig: signal.Signals, app: Application) -> None:
    """Manejar SIGTERM/SIGINT — shutdown limpio."""
    log.warning(f"Received signal {sig.name} — initiating graceful shutdown")
    try:
        await app.bot.send_message(
            chat_id=cfg.telegram_token.split(":")[0] if ":" in cfg.telegram_token else "",
            text="🔄 Bot reiniciándose... espera un momento.",
        )
    except Exception:
        pass
    await app.stop()
    await app.shutdown()
    await close_client()
    await stop_health_server()
    log.info("Shutdown complete")


def setup_signal_handlers(app: Application) -> None:
    """Registrar handlers para SIGTERM y SIGINT."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown_signal_handler(s, app)),
        )
    log.info("Signal handlers registered (SIGTERM/SIGINT)")


# ── Command handlers ───────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hola. Soy tu bot de monitorización.\n"
        "Usa /menu para abrir el menú.",
        reply_markup=main_menu(),
    )


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📋 Menú principal", reply_markup=main_menu()
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *Ayuda del Bot de Monitorización*\n\n"
        "/start — Iniciar bot\n"
        "/menu — Abrir menú principal\n"
        "/help — Mostrar ayuda\n"
        "/logs \u003ccontainer\u003e [líneas] — Ver últimos logs\n\n"
        "⚠️ _Rate limit: 5 comandos por minuto._",
        parse_mode="Markdown",
    )


# ── Menús ─────────────────────────────────────────────────────────────────────

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Estado", callback_data="estado"),
            InlineKeyboardButton("❓ Ayuda", callback_data="ayuda"),
        ],
        [
            InlineKeyboardButton("⚙️ Configuración", callback_data="config"),
        ],
    ])


# ── Callback handler principal ─────────────────────────────────────────────────

@rate_limit
@whitelist_middleware
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    # Feedback visual para acciones que mutan estado
    if data.startswith(("start_", "stop_", "restart_", "remove_")):
        await query.edit_message_text(
            text="⏳ Procesando...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Volver", callback_data="cfg_actions")]
            ]),
        )

    parsed = parse_callback(data)
    if parsed is None:
        log.warning(f"Unknown callback_data: {data}")
        return

    # Callbacks sin parámetro
    if parsed == CallbackActionType.ESTADO:
        await handle_estado(query)
    elif parsed == CallbackActionType.HELP:
        await handle_ayuda(query)
    elif parsed == CallbackActionType.CONFIG_MENU:
        await handle_config_menu(query)
    elif parsed == CallbackActionType.CFG_SERVER:
        await handle_cfg_server(query)
    elif parsed == CallbackActionType.CFG_AVAIL:
        await handle_cfg_avail(query)
    elif parsed == CallbackActionType.CFG_LIST:
        await handle_cfg_list(query)
    elif parsed == CallbackActionType.CFG_STATUS:
        await handle_cfg_status(query)
    elif parsed == CallbackActionType.CFG_ACTIONS:
        await handle_cfg_actions(query)
    elif parsed == CallbackActionType.BACK_CONFIG:
        await handle_back_config(query)
    elif parsed == CallbackActionType.BACK_MAIN:
        await handle_back_main(query)

    # Callbacks con short_id
    else:
        from app.handlers.callback_data import ContainerCallback
        if isinstance(parsed, ContainerCallback):
            if parsed.action == CallbackActionType.DETAIL:
                await handle_detail(query, parsed.short_id)
            elif parsed.action == CallbackActionType.START:
                await handle_container_action(query, parsed.short_id, "start")
            elif parsed.action == CallbackActionType.STOP:
                await handle_container_action(query, parsed.short_id, "stop")
            elif parsed.action == CallbackActionType.RESTART:
                await handle_container_action(query, parsed.short_id, "restart")
            elif parsed.action == CallbackActionType.REMOVE:
                await handle_container_action(query, parsed.short_id, "remove")


# ── App runner ────────────────────────────────────────────────────────────────

def run() -> None:
    errors = cfg.validate()
    if errors:
        for err in errors:
            logging.error(f"Config error: {err}")
        raise RuntimeError("Config errors: " + "; ".join(errors))

    # Inicializar base de datos SQLite
    init_db()

    log.info("Starting Telegram bot...")

    app = Application.builder().token(cfg.telegram_token).build()

    # Health check HTTP server en segundo plano
    asyncio.create_task(start_health_server(port=cfg.health_port))
    log.info(f"Health server scheduled on port {cfg.health_port}")

    # Tareas programadas (reportes)
    setup_scheduled_tasks(app)

    # Registrar handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Graceful shutdown
    setup_signal_handlers(app)

    log.info("Bot ready — polling started")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        read_timeout=60,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    run()
