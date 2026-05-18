"""Bot principal — Mes 1 + Mes 2 + Mes 3 (F3/F4/C2/C4/C5)."""
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
from app.alert_engine import get_alert_engine
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
    handle_cfg_endpoint,
    handle_ep_select,
    handle_back_config,
    handle_back_main,
)
from app.handlers.actions import (
    handle_cfg_actions,
    handle_detail,
    handle_container_action,
    handle_confirm_action,
    handle_cancel_action,
)
from app.handlers.logs import logs
from app.handlers.stats import stats
from app.handlers.batch import (
    handle_batch_select,
    handle_batch_toggle,
    handle_batch_execute,
    handle_batch_cancel,
)


# ── Signal handlers ───────────────────────────────────────────────────────────

async def shutdown_signal_handler(sig: signal.Signals, app: Application) -> None:
    log.warning(f"Received signal {sig.name} — initiating graceful shutdown")
    try:
        await app.bot.send_message(
            chat_id=cfg.telegram_token.split(":")[0] if ":" in cfg.telegram_token else "",
            text="Bot reiniciandose... espera un momento.",
        )
    except Exception:
        pass
    await app.stop()
    await app.shutdown()
    await close_client()
    await stop_health_server()
    if hasattr(app, "_alert_engine"):
        await app._alert_engine.stop()
    log.info("Shutdown complete")


def setup_signal_handlers(app: Application) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown_signal_handler(s, app)),
        )
    log.info("Signal handlers registered (SIGTERM/SIGINT)")


# ── Command handlers ─────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hola. Soy tu bot de monitorizacion.\nUsa /menu para abrir el menu.",
        reply_markup=main_menu(),
    )


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Menu principal", reply_markup=main_menu())


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Ayuda del Bot de Monitorizacion\n"
        "===============================\n\n"
        "COMANDOS BASICOS\n"
        "/start - Iniciar el bot\n"
        "/menu - Abrir menu principal\n"
        "/help - Mostrar esta ayuda\n\n"
        "COMANDOS DE CONSULTA\n"
        "/status - Resumen rapido de contenedores\n"
        "/stats [nombre] - Uso de CPU/RAM\n"
        "  Ejemplo: /stats portainer\n"
        "  Ejemplo: /stats (muestra todos)\n\n"
        "COMANDOS DE CONTROL\n"
        "/logs <nombre> [lineas] - Ver logs de un contenedor\n"
        "  Ejemplo: /logs telegram-bot\n"
        "  Ejemplo: /logs portainer 100\n\n"
        "OPERACIONES EN LOTE\n"
        "/batch_start - Seleccionar y arrancar varios contenedores\n"
        "/batch_stop - Seleccionar y detener varios contenedores\n"
        "/batch_restart - Seleccionar y reiniciar varios contenedores\n\n"
        "ADMINISTRACION (solo admins)\n"
        "/broadcast <mensaje> - Enviar mensaje a todos los usuarios\n"
        "  Ejemplo: /broadcast Mantenimiento a las 22:00\n"
        "/setlang es|en - Cambiar idioma del bot\n"
        "  Ejemplo: /setlang en\n\n"
        "LIMITE DE USO\n"
        "Rate limit: 5 comandos por minuto por usuario\n"
        "Solo usuarios autorizados pueden usar el bot\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── F6: /broadcast ───────────────────────────────────────────────────────

from app.userdb import get_all_user_ids


async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Enviar mensaje a todos los usuarios autorizados."""
    user_id = str(update.effective_user.id if update.effective_user else 0)
    allowed_ids = [str(x) for x in cfg.allowed_telegram_ids]
    if user_id not in allowed_ids:
        await update.message.reply_text("No tienes permiso para enviar broadcasts.")
        return

    if not ctx.args:
        await update.message.reply_text(
            "Uso: /broadcast <mensaje>\n"
            "Ejemplo: /broadcast Mantenimiento a las 22:00"
        )
        return

    message = " ".join(ctx.args)
    user_ids = get_all_user_ids()
    bot = ctx.bot

    sent = failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=int(uid), text=f"Broadcast:\n\n{message}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"Broadcast enviado.\nExito: {sent}  Fallidos: {failed}"
    )


# ── Batch commands ────────────────────────────────────────────────────────────

async def batch_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Pulsa para entrar al modo de seleccion multiple.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Seleccionar contenedores", callback_data="batch_enter_start")],
            [InlineKeyboardButton("Cancelar", callback_data="back_main")],
        ]),
    )


async def batch_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Pulsa para entrar al modo de seleccion multiple.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Seleccionar contenedores", callback_data="batch_enter_stop")],
            [InlineKeyboardButton("Cancelar", callback_data="back_main")],
        ]),
    )


async def batch_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Pulsa para entrar al modo de seleccion multiple.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Seleccionar contenedores", callback_data="batch_enter_restart")],
            [InlineKeyboardButton("Cancelar", callback_data="back_main")],
        ]),
    )


# ── Menus ────────────────────────────────────────────────────────────────────

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Estado", callback_data="estado"),
            InlineKeyboardButton("Stats", callback_data="stats_inline"),
            InlineKeyboardButton("Ayuda", callback_data="ayuda"),
        ],
        [
            InlineKeyboardButton("Configuracion", callback_data="config"),
        ],
    ])


# ── Stats inline ─────────────────────────────────────────────────────────────

async def handle_stats_inline(query) -> None:
    client = get_client()
    try:
        containers = await client.get_containers()
        running = [c for c in containers if c.get("State") == "running"]
        if not running:
            await query.edit_message_text(
                "No hay contenedores en ejecucion.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Volver", callback_data="back_main")]
                ]),
            )
            return

        lines = []
        for c in running:
            name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
            short_id = c.get("Id", "")[:12]
            is_own = name == cfg.bot_container_name or short_id == cfg.bot_container_name
            try:
                sd = await client.get_container_stats(c["Id"])
                cpu = sd.get("cpu_percent", "?")
                mem = sd.get("memory_percent", "?")
                cpu_str = f"{cpu}%" if isinstance(cpu, (int, float)) else str(cpu)
                mem_str = f"{mem}%" if isinstance(mem, (int, float)) else str(mem)
                tag = " [BOT]" if is_own else ""
                lines.append(f"{name}{tag}: CPU {cpu_str}  RAM {mem_str}")
            except Exception:
                tag = " [BOT]" if is_own else ""
                lines.append(f"{name}{tag}: stats no disponibles")

        text = "Stats de contenedores en ejecucion\n\n" + "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n(truncado)"

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Actualizar", callback_data="stats_inline")],
                [InlineKeyboardButton("Menu", callback_data="back_main")],
            ]),
        )
    except Exception as e:
        await query.edit_message_text(
            f"Error: {str(e)[:200]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Volver", callback_data="back_main")]
            ]),
        )


# ── Callback handler principal ───────────────────────────────────────────────

@rate_limit
@whitelist_middleware
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id if update.effective_user else 0

    # F5: Endpoint selection
    if data.startswith("ep_select_"):
        ep_name = data.replace("ep_select_", "")
        await handle_ep_select(query, ep_name)
        return
    if data.startswith("batch_enter_"):
        action = data.replace("batch_enter_", "")
        await handle_batch_select(query, user_id, action)
        return
    if data.startswith("batch_toggle_"):
        short_id = data.replace("batch_toggle_", "")
        await handle_batch_toggle(query, user_id, short_id)
        return
    if data == "batch_execute":
        await handle_batch_execute(query, user_id)
        return
    if data == "batch_cancel":
        await handle_batch_cancel(query, user_id)
        return

    # Stats inline refresh
    if data == "stats_inline":
        await handle_stats_inline(query)
        return

    # R2: Confirm/Cancel para acciones peligrosas
    if data == "cancel_action":
        await handle_cancel_action(query)
        return

    if data.startswith("confirm_action_"):
        # formato: confirm_action_<short_id>_<action>
        parts = data.split("_", 2)  # ["confirm", "action", "<short_id>_<action>"]
        if len(parts) == 3:
            rest = parts[2]
            if len(rest) > 13:
                short_id = rest[:12]
                action_name = rest[13:]
                if action_name in ("start", "stop", "restart", "remove"):
                    await handle_confirm_action(query, short_id, action_name)
                    return

    # Feedback visual para acciones (sin confirmacion para stop/remove — ya la piden)
    if data.startswith(("start_", "restart_")):
        await query.edit_message_text(
            text="Procesando...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Volver", callback_data="cfg_actions")]
            ]),
        )

    parsed = parse_callback(data)
    if parsed is None:
        log.warning(f"Unknown callback_data: {data}")
        return

    # Callbacks sin parametro
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
    elif parsed == CallbackActionType.CFG_ENDPOINT:
        await handle_cfg_endpoint(query)
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

    init_db()
    log.info("Starting Telegram bot...")

    app = Application.builder().token(cfg.telegram_token).build()

    # Health check HTTP server
    asyncio.create_task(start_health_server(port=cfg.health_port))
    log.info(f"Health server scheduled on port {cfg.health_port}")

    # Alert engine (F3)
    alert_eng = get_alert_engine(app.bot)
    app._alert_engine = alert_eng
    asyncio.create_task(alert_eng.start(interval_seconds=120))
    log.info("Alert engine started")

    # Scheduled reports (F2)
    setup_scheduled_tasks(app)

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("batch_start", batch_start))
    app.add_handler(CommandHandler("batch_stop", batch_stop))
    app.add_handler(CommandHandler("batch_restart", batch_restart))
    app.add_handler(CallbackQueryHandler(button_handler))

    setup_signal_handlers(app)

    log.info("Bot ready — polling started")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        read_timeout=60,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    run()
