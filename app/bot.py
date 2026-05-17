"""Bot principal con graceful shutdown."""
import asyncio
import logging
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


# ── Signal handlers para graceful shutdown ──────────────────────
shutdown_event: asyncio.Event = None


async def shutdown_signal_handler(sig: signal.Signals, app: Application):
    """Manejar SIGTERM/SIGINT — shutdown limpio."""
    log.warning(f"Received signal {sig.name} — initiating graceful shutdown")
    
    # Notificar a los usuarios que el bot se reinicia
    try:
        await app.bot.send_message(
            chat_id=cfg.telegram_token.split(":")[0] if ":" in cfg.telegram_token else "",
            text="🔄 Bot reiniciándose... espera un momento.",
        )
    except Exception:
        pass
    
    # Detener polling
    await app.stop()
    await app.shutdown()
    
    # Cerrar cliente Portainer
    await close_client()
    log.info("Shutdown complete")


def setup_signal_handlers(app: Application):
    """Registrar handlers para SIGTERM y SIGINT."""
    loop = asyncio.get_running_loop()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown_signal_handler(s, app))
        )
    log.info("Signal handlers registered (SIGTERM/SIGINT)")


# ── Menús ────────────────────────────────────────────────────────

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


def config_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Validar Servidor", callback_data="cfg_server"),
            InlineKeyboardButton("📊 Disponibilidad", callback_data="cfg_avail"),
        ],
        [
            InlineKeyboardButton("📋 Contenedores", callback_data="cfg_list"),
            InlineKeyboardButton("📄 Detalle", callback_data="cfg_status"),
        ],
        [
            InlineKeyboardButton("🎮 Acciones", callback_data="cfg_actions"),
        ],
        [
            InlineKeyboardButton("🔙 Volver", callback_data="back_main"),
        ],
    ])


# ── Command handlers ─────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hola. Soy tu bot de monitorización.\n"
        "Usa /menu para abrir el menú.",
        reply_markup=main_menu(),
    )


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Menú principal",
        reply_markup=main_menu(),
    )


# ── Callback handler principal ────────────────────────────────────

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    client = get_client()

    # R4: Feedback visual — "⏳ Procesando..." para acciones que tardan
    action_callbacks = {"start_", "stop_", "restart_", "remove_"}
    if any(data.startswith(a) for a in action_callbacks):
        await query.edit_message_text(
            text="⏳ Procesando...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Volver", callback_data="cfg_actions")]
            ])
        )

    # ── Main menu ──
    if data == "estado":
        try:
            containers = await client.get_containers()
            running = sum(1 for c in containers if c.get("State") == "running")
            total = len(containers)
            await query.edit_message_text(
                text=f"🟢 Bot operativo\n📦 Contenedores: {running}/{total} activos",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Volver", callback_data="back_main")]
                ]),
            )
        except Exception as e:
            log.error(f"Error in estado: {e}")
            await query.edit_message_text(
                text="🟡 Bot operativo\n⚠️ Portainer no disponible",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Volver", callback_data="back_main")]
                ]),
            )

    elif data == "ayuda":
        await query.edit_message_text(
            text=(
                "📖 *Comandos disponibles:*\n\n"
                "/start — Iniciar bot\n"
                "/menu — Abrir menú principal\n"
                "/help — Mostrar ayuda\n\n"
                "⚙️ *Configuración:*\n"
                "🔍 Validar Servidor\n"
                "📊 Disponibilidad\n"
                "📋 Contenedores\n"
                "📄 Detalle\n"
                "🎮 Acciones\n\n"
                f"🤖 Hostname: `{cfg.bot_container_name or 'auto'}`"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Volver", callback_data="back_main")]
            ]),
            parse_mode="Markdown",
        )

    elif data == "config":
        await query.edit_message_text(
            text="⚙️ Configuración — Portainer",
            reply_markup=config_menu(),
        )

    # ── Config callbacks ──
    elif data == "cfg_server":
        try:
            await client.auth()
            ep_id = await client.get_endpoint_id()
            containers = await client.get_containers()
            running = sum(1 for c in containers if c.get("State") == "running")
            stopped = sum(1 for c in containers if c.get("State") != "running")
            
            # Find own container
            own_name = next(
                (c["Names"][0].lstrip("/") for c in containers
                 if c["Names"] and (
                     c["Names"][0].lstrip("/") == cfg.bot_container_name
                     or c["Id"][:12] == cfg.bot_container_name
                 )),
                None
            )
            
            await query.edit_message_text(
                text=(
                    f"🟢 Servidor Portainer: Operativo\n"
                    f"🔗 URL: {cfg.portainer_url}\n"
                    f"📦 Total contenedores: {len(containers)}\n"
                    f"✅ Ejecutándose: {running}\n"
                    f"⛔ Detenidos: {stopped}\n\n"
                    f"── Contenedor Propio ──\n"
                    f"🟢 {own_name or 'No detectado'}"
                ),
                reply_markup=config_menu(),
            )
        except Exception as e:
            log.error(f"Error in cfg_server: {e}")
            await query.edit_message_text(
                text=f"🔴 Servidor Portainer: Error\n{str(e)[:200]}",
                reply_markup=config_menu(),
            )

    elif data == "cfg_avail":
        try:
            containers = await client.get_containers()
            ext_running = ext_stopped = 0
            stopped_names = []
            for c in containers:
                if c["Names"] and (
                    c["Names"][0].lstrip("/") == cfg.bot_container_name
                    or c["Id"][:12] == cfg.bot_container_name
                ):
                    continue
                if c.get("State") == "running":
                    ext_running += 1
                else:
                    ext_stopped += 1
                    stopped_names.append(c["Names"][0].lstrip("/") if c.get("Names") else "?")
            
            total = ext_running + ext_stopped
            text = (
                f"📊 Disponibilidad Externa\n"
                f"✅ Funcionando: {ext_running}/{total}\n"
                f"⛔ Caídos: {ext_stopped}/{total}\n"
            )
            if stopped_names:
                text += "\n⚠️ Caídos:\n" + "\n".join(f"  • {n}" for n in stopped_names)
            else:
                text += "\n🎉 Todos los contenedores externos están operativos"
            
            await query.edit_message_text(text=text, reply_markup=config_menu())
        except Exception as e:
            log.error(f"Error in cfg_avail: {e}")
            await query.edit_message_text(
                text=f"Error: {str(e)[:200]}",
                reply_markup=config_menu(),
            )

    elif data == "cfg_list":
        try:
            containers = await client.get_containers()
            lines = []
            for c in containers:
                name = c["Names"][0].lstrip("/") if c.get("Names") else "?"
                is_own = name == cfg.bot_container_name or c["Id"][:12] == cfg.bot_container_name
                emoji = "🟢" if c.get("State") == "running" else "🔴"
                tag = " [BOT]" if is_own else ""
                lines.append(f"{emoji} {name}{tag} — {c.get('Image', '?')}")
            
            await query.edit_message_text(
                text="📋 Contenedores\n\n" + "\n".join(lines),
                reply_markup=config_menu(),
            )
        except Exception as e:
            log.error(f"Error in cfg_list: {e}")
            await query.edit_message_text(
                text=f"Error: {str(e)[:200]}",
                reply_markup=config_menu(),
            )

    elif data == "cfg_status":
        try:
            containers = await client.get_containers()
            lines = []
            for c in containers:
                name = c["Names"][0].lstrip("/") if c.get("Names") else "?"
                is_own = name == cfg.bot_container_name or c["Id"][:12] == cfg.bot_container_name
                emoji = "🟢" if c.get("State") == "running" else "🔴"
                ports = c.get("Ports", [])
                port_str = ", ".join(
                    str(p.get("PublicPort") or p.get("PrivatePort", "?"))
                    for p in ports if p.get("PublicPort") or p.get("PrivatePort")
                ) or "none"
                lines.append(
                    f"{emoji} {name}{' [BOT]' if is_own else ''}\n"
                    f"  Image: {c.get('Image', '?')}\n"
                    f"  Status: {c.get('Status', '?')}\n"
                    f"  Ports: {port_str}"
                )
            
            await query.edit_message_text(
                text="📄 Detalle de Contenedores\n\n" + "\n\n".join(lines),
                reply_markup=config_menu(),
            )
        except Exception as e:
            log.error(f"Error in cfg_status: {e}")
            await query.edit_message_text(
                text=f"Error: {str(e)[:200]}",
                reply_markup=config_menu(),
            )

    elif data == "cfg_actions":
        await _show_actions_menu(query)

    elif data == "back_config":
        await query.edit_message_text(
            text="⚙️ Configuración — Portainer",
            reply_markup=config_menu(),
        )

    elif data == "back_main":
        await query.edit_message_text(
            text="📋 Menú principal",
            reply_markup=main_menu(),
        )

    # ── Container action callbacks ──
    elif data.startswith("detail_"):
        short_id = data.replace("detail_", "")
        await _show_container_detail(query, short_id, client)

    elif data.startswith("start_"):
        short_id = data.replace("start_", "")
        await _do_container_action(query, short_id, "start", client)

    elif data.startswith("stop_"):
        short_id = data.replace("stop_", "")
        await _do_container_action(query, short_id, "stop", client)

    elif data.startswith("restart_"):
        short_id = data.replace("restart_", "")
        await _do_container_action(query, short_id, "restart", client)

    elif data.startswith("remove_"):
        short_id = data.replace("remove_", "")
        await _do_container_action(query, short_id, "remove", client)


async def _show_actions_menu(query):
    """Mostrar menú de acciones con botones para cada contenedor."""
    client = get_client()
    try:
        containers = await client.get_containers()
    except Exception as e:
        log.error(f"Error getting containers for actions menu: {e}")
        await query.edit_message_text(
            text="Error conectando a Portainer.",
            reply_markup=config_menu(),
        )
        return

    keyboard = []
    for c in containers:
        name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
        state = c.get("State", "unknown")
        short_id = c.get("Id", "")[:12]
        emoji = "🟢" if state == "running" else "🔴"
        is_own = name == cfg.bot_container_name or c.get("Id", "")[:12] == cfg.bot_container_name

        if is_own:
            keyboard.append([
                InlineKeyboardButton(f"🤖 {name} [BOT]", callback_data=f"detail_{short_id}")
            ])
        else:
            restart_or_start = "🔄" if state == "running" else "▶️"
            restart_cb = f"restart_{short_id}" if state == "running" else f"start_{short_id}"
            stop_btn = InlineKeyboardButton("⛔", callback_data=f"stop_{short_id}") if state == "running" else InlineKeyboardButton("🗑️", callback_data=f"remove_{short_id}")
            keyboard.append([
                InlineKeyboardButton(f"{emoji} {name}", callback_data=f"detail_{short_id}"),
                InlineKeyboardButton(restart_or_start, callback_data=restart_cb),
                stop_btn,
            ])

    keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="back_config")])
    
    await query.edit_message_text(
        text="🎮 Acciones sobre contenedores\n"
             "Toca un nombre para ver detalles\n"
             "🔄 = reiniciar  ▶️ = iniciar  ⛔ = detener",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_container_detail(query, short_id, client):
    """Mostrar detalle de un contenedor específico."""
    try:
        containers = await client.get_containers()
        target = next((c for c in containers if c.get("Id", "")[:12] == short_id), None)
        
        if not target:
            await query.edit_message_text(
                text=f"❌ Contenedor {short_id} no encontrado.",
                reply_markup=config_menu(),
            )
            return

        inspect = await client.get_container_inspect(target["Id"])
        detail = client.build_container_detail(inspect)
        state = target.get("State", "unknown")
        is_own = (
            target.get("Names", [""])[0].lstrip("/") == cfg.bot_container_name
            or target.get("Id", "")[:12] == cfg.bot_container_name
        )

        text = (
            f"{detail.emoji} {detail.name}{' [ESTE BOT]' if is_own else ''}\n\n"
            f"📦 ID: {detail.short_id}\n"
            f"🖼️ Image: {detail.image}\n"
            f"📊 Estado: {detail.state}\n"
            f"⏱️ Uptime: {detail.uptime_str}\n"
            f"🔄 Restart count: {detail.restart_count}\n"
            f"🌐 Network: {detail.network_mode}\n"
            f"💾 Memory: {detail.memory_str}\n"
        )
        if detail.safe_env_count() > 0:
            text += f"🔧 Env: {detail.safe_env_count()} variables\n"

        keyboard = []
        if not is_own:
            if state == "running":
                keyboard.append([
                    InlineKeyboardButton("🔄 Reiniciar", callback_data=f"restart_{short_id}"),
                    InlineKeyboardButton("⛔ Detener", callback_data=f"stop_{short_id}"),
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton("▶️ Iniciar", callback_data=f"start_{short_id}"),
                ])
        else:
            keyboard.append([
                InlineKeyboardButton("🔄 Reiniciar Bot", callback_data=f"restart_{short_id}"),
            ])
        keyboard.append([InlineKeyboardButton("🔙 Volver a Acciones", callback_data="cfg_actions")])

        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        log.error(f"Error showing container detail {short_id}: {e}")
        await query.edit_message_text(
            text=f"Error obteniendo detalle: {str(e)[:200]}",
            reply_markup=config_menu(),
        )


async def _do_container_action(query, short_id, action, client):
    """Ejecutar acción en contenedor (start/stop/restart/remove)."""
    action_names = {"start": "iniciado", "stop": "detenido", "restart": "reiniciado", "remove": "eliminado"}
    action_emoji = {"start": "▶️", "stop": "⛔", "restart": "🔄", "remove": "🗑️"}
    
    try:
        containers = await client.get_containers()
        target = next((c for c in containers if c.get("Id", "")[:12] == short_id), None)
        
        if not target:
            await query.edit_message_text(
                text=f"❌ Contenedor {short_id} no encontrado.",
                reply_markup=config_menu(),
            )
            return

        name = target.get("Names", ["?"])[0].lstrip("/") if target.get("Names") else "?"
        is_own = name == cfg.bot_container_name or target.get("Id", "")[:12] == cfg.bot_container_name
        full_id = target.get("Id", "")

        # Safety check
        if is_own and action in ("stop", "remove"):
            await query.edit_message_text(
                text=f"⚠️ No puedes {action} el contenedor del bot (te apagarías a ti mismo).",
                reply_markup=config_menu(),
            )
            return

        if action == "remove":
            try:
                await client.container_action(full_id, "stop")
            except Exception:
                pass
            await client.container_delete(full_id)
        else:
            await client.container_action(full_id, action)

        log.info(f"Action '{action}' performed on container {name} ({short_id})")
        await query.edit_message_text(
            text=f"{action_emoji.get(action, '❓')} Contenedor `{name}` {action_names.get(action, action)}.",
            reply_markup=config_menu(),
        )
    except Exception as e:
        log.error(f"Error performing action {action} on {short_id}: {e}")
        await query.edit_message_text(
            text=f"❌ Error: {str(e)[:200]}",
            reply_markup=config_menu(),
        )


# ── App runner con graceful shutdown ─────────────────────────────

def run():
    errors = cfg.validate()
    if errors:
        raise RuntimeError("Config errors: " + "; ".join(errors))

    log.info("Starting Telegram bot...")
    
    app = Application.builder().token(cfg.telegram_token).build()
    
    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Setup graceful shutdown
    setup_signal_handlers(app)
    
    log.info("Bot ready — polling started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run()
