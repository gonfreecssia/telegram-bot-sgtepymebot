"""Handler del comando /logs \u003ccontainer\u003e."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.config import cfg
from app.logger import log
from app.portainer_client import get_client


async def logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostrar últimos logs de un contenedor.
    
    Uso: /logs \u003ccriteria\u003e [líneas]
    Ejemplos:
      /logs telegram-bot           → últimos 50 logs
      /logs telegram-bot 100       → últimos 100 logs
      /logs abc123def              → buscar por short ID
    """
    if not ctx.args:
        await update.message.reply_text(
            "📖 *Uso:* `/logs \u003ccontainer\u003e [líneas]`\n\n"
            "Ejemplos:\n"
            "`/logs telegram-bot` — últimos 50 logs\n"
            "`/logs telegram-bot 100` — últimos 100 logs\n"
            "`/logs abc123` — buscar por short ID",
            parse_mode="Markdown",
        )
        return

    # Parsear: último arg puede ser número de líneas
    lines = 50
    args = ctx.args[:]
    if len(args) > 1 and args[-1].isdigit():
        lines = min(int(args[-1]), 200)  # max 200 líneas
        args = args[:-1]

    name_or_id = " ".join(args)
    short_id = name_or_id[:12] if len(name_or_id) >= 12 else name_or_id

    client = get_client()
    try:
        containers = await client.get_containers()
        target = next(
            (c for c in containers if c.get("Id", "")[:12] == short_id), None
        )
        if not target:
            # Buscar por nombre parcial
            matches = [
                c for c in containers
                if name_or_id.lower() in c.get("Names", [""])[0].lower()
            ]
            if not matches:
                await update.message.reply_text(
                    f"❌ No se encontró contenedor que coincida con `{name_or_id}`.",
                    parse_mode="Markdown",
                )
                return
            target = matches[0]
            if len(matches) > 1:
                names = ", ".join(c.get("Names", ["?"])[0].lstrip("/") for c in matches[:5])
                await update.message.reply_text(
                    f"⚠️ Múltiples coincidencias: {names}. "
                    "Usa el nombre completo o el short ID.",
                    parse_mode="Markdown",
                )
                return

        full_id = target["Id"]
        container_name = target.get("Names", ["?"])[0].lstrip("/")
        state = target.get("State", "unknown")

        logs_text = await client.get_container_logs(full_id, lines=lines)

        emoji = "🟢" if state == "running" else "🔴"
        # Truncar si es muy largo para Telegram (max 4096 chars)
        if len(logs_text) > 3800:
            logs_text = logs_text[:3800] + "\n... _(truncado)_"

        text = (
            f"{emoji} `{container_name}` — últimos {lines} logs\n"
            "─────────────────\n"
            f"```{logs_text or '(sin logs)'}```"
        )
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Error getting logs for {short_id}: {e}")
        await update.message.reply_text(
            f"❌ Error obteniendo logs: {str(e)[:200]}",
            disable_web_page_preview=True,
        )
