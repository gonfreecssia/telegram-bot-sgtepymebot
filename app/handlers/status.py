"""Handlers para callbacks de status, menú y configuración."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import cfg
from app.logger import log
from app.portainer_client import get_client


def config_menu_inline() -> InlineKeyboardMarkup:
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


def main_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Estado", callback_data="estado"),
            InlineKeyboardButton("❓ Ayuda", callback_data="ayuda"),
        ],
        [
            InlineKeyboardButton("⚙️ Configuración", callback_data="config"),
        ],
    ])


async def handle_estado(query) -> None:
    """Mostrar resumen general de contenedores."""
    client = get_client()
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


async def handle_ayuda(query) -> None:
    """Mostrar ayuda."""
    await query.edit_message_text(
        text=(
            "📖 *Comandos disponibles:*\n\n"
            "/start — Iniciar bot\n"
            "/menu — Abrir menú principal\n"
            "/help — Mostrar ayuda\n"
            "/logs \u003ccontainer\u003e — Ver últimos logs\n\n"
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


async def handle_config_menu(query) -> None:
    """Mostrar menú de configuración."""
    await query.edit_message_text(
        text="⚙️ Configuración — Portainer",
        reply_markup=config_menu_inline(),
    )


async def handle_cfg_server(query) -> None:
    """Validar conexión a Portainer y mostrar resumen."""
    client = get_client()
    try:
        await client.auth()
        containers = await client.get_containers()
        running = sum(1 for c in containers if c.get("State") == "running")
        stopped = sum(1 for c in containers if c.get("State") != "running")
        own_name = next(
            (
                c["Names"][0].lstrip("/")
                for c in containers
                if c.get("Names")
                and (
                    c["Names"][0].lstrip("/") == cfg.bot_container_name
                    or c["Id"][:12] == cfg.bot_container_name
                )
            ),
            None,
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
            reply_markup=config_menu_inline(),
        )
    except Exception as e:
        log.error(f"Error in cfg_server: {e}")
        await query.edit_message_text(
            text=f"🔴 Servidor Portainer: Error\n{str(e)[:200]}",
            reply_markup=config_menu_inline(),
        )


async def handle_cfg_avail(query) -> None:
    """Disponibilidad de contenedores externos (excluyendo el propio bot)."""
    client = get_client()
    try:
        containers = await client.get_containers()
        ext_running = ext_stopped = 0
        stopped_names = []
        for c in containers:
            name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
            is_own = (
                name == cfg.bot_container_name
                or c.get("Id", "")[:12] == cfg.bot_container_name
            )
            if is_own:
                continue
            if c.get("State") == "running":
                ext_running += 1
            else:
                ext_stopped += 1
                stopped_names.append(name)
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
        await query.edit_message_text(text=text, reply_markup=config_menu_inline())
    except Exception as e:
        log.error(f"Error in cfg_avail: {e}")
        await query.edit_message_text(
            text=f"Error: {str(e)[:200]}", reply_markup=config_menu_inline()
        )


async def handle_cfg_list(query) -> None:
    """Lista rápida de todos los contenedores."""
    client = get_client()
    try:
        containers = await client.get_containers()
        lines = []
        for c in containers:
            name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
            is_own = (
                name == cfg.bot_container_name
                or c.get("Id", "")[:12] == cfg.bot_container_name
            )
            emoji = "🟢" if c.get("State") == "running" else "🔴"
            tag = " [BOT]" if is_own else ""
            lines.append(f"{emoji} {name}{tag} — {c.get('Image', '?')}")
        await query.edit_message_text(
            text="📋 Contenedores\n\n" + "\n".join(lines),
            reply_markup=config_menu_inline(),
        )
    except Exception as e:
        log.error(f"Error in cfg_list: {e}")
        await query.edit_message_text(
            text=f"Error: {str(e)[:200]}", reply_markup=config_menu_inline()
        )


async def handle_cfg_status(query) -> None:
    """Detalle de todos los contenedores (image, status, ports)."""
    client = get_client()
    try:
        containers = await client.get_containers()
        lines = []
        for c in containers:
            name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
            is_own = (
                name == cfg.bot_container_name
                or c.get("Id", "")[:12] == cfg.bot_container_name
            )
            emoji = "🟢" if c.get("State") == "running" else "🔴"
            ports = c.get("Ports", [])
            port_str = ", ".join(
                str(p.get("PublicPort") or p.get("PrivatePort", "?"))
                for p in ports
                if p.get("PublicPort") or p.get("PrivatePort")
            ) or "none"
            lines.append(
                f"{emoji} {name}{' [BOT]' if is_own else ''}\n"
                f"  Image: {c.get('Image', '?')}\n"
                f"  Status: {c.get('Status', '?')}\n"
                f"  Ports: {port_str}"
            )
        await query.edit_message_text(
            text="📄 Detalle de Contenedores\n\n" + "\n\n".join(lines),
            reply_markup=config_menu_inline(),
        )
    except Exception as e:
        log.error(f"Error in cfg_status: {e}")
        await query.edit_message_text(
            text=f"Error: {str(e)[:200]}", reply_markup=config_menu_inline()
        )


async def handle_back_config(query) -> None:
    await query.edit_message_text(
        text="⚙️ Configuración — Portainer",
        reply_markup=config_menu_inline(),
    )


async def handle_back_main(query) -> None:
    await query.edit_message_text(
        text="📋 Menú principal",
        reply_markup=main_menu_inline(),
    )
