"""Handler del comando /stats — uso de CPU/RAM por contenedor."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import cfg
from app.logger import log
from app.portainer_client import get_client


async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostrar uso de CPU/RAM de contenedores.

    Uso: /stats [container]
    Sin argumentos: muestra todos los contenedores en ejecución.
    Con argumento: muestra stats de ese contenedor específico.
    """
    client = get_client()

    try:
        containers = await client.get_containers()
    except Exception as e:
        log.error(f"Error getting containers for stats: {e}")
        await update.message.reply_text(
            f"Error conectando a Portainer: {str(e)[:200]}"
        )
        return

    if ctx.args:
        name_filter = " ".join(ctx.args).lower()
        containers = [
            c for c in containers
            if name_filter in c.get("Names", [""])[0].lower()
        ]
        if not containers:
            await update.message.reply_text(
                f"No se encontró: `{name_filter}`", parse_mode="Markdown"
            )
            return

    running = [c for c in containers if c.get("State") == "running"]
    if not running:
        await update.message.reply_text("No hay contenedores en ejecución.")
        return

    lines = []
    for c in running:
        name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
        short_id = c.get("Id", "")[:12]
        is_own = (
            name == cfg.bot_container_name
            or short_id == cfg.bot_container_name
        )
        tag = " 🤖" if is_own else ""

        try:
            stats_data = await client.get_container_stats(c["Id"])
            cpu = stats_data.get("cpu_percent", "N/A")
            mem = stats_data.get("memory_percent", "N/A")
            mem_limit = stats_data.get("memory_limit_mb", 0)
            mem_used = stats_data.get("memory_used_mb", 0)
            net_rx = stats_data.get("network_rx_mb", 0)
            net_tx = stats_data.get("network_tx_mb", 0)
            block_r = stats_data.get("block_read_mb", 0)
            block_w = stats_data.get("block_write_mb", 0)

            cpu_str = f"{cpu}%" if isinstance(cpu, (int, float)) else cpu
            mem_str = f"{mem}%" if isinstance(mem, (int, float)) else mem
            mem_detail = (
                f"{mem_used:.0f}MB / {mem_limit:.0f}MB" if mem_limit
                else f"{mem_used:.0f}MB"
            )

            entry = [
                f"*{name}{tag}*",
                f"  CPU: {cpu_str}  RAM: {mem_str} ({mem_detail})",
                f"  Net: {net_rx:.1f}MB down  {net_tx:.1f}MB up",
                f"  Disk: {block_r:.1f}MB read  {block_w:.1f}MB write",
            ]
            lines.append("\n".join(entry))
        except Exception:
            lines.append(f"*{name}{tag}*\n  Stats no disponibles")

    text = "📊 *Uso de recursos* — contenedores en ejecucion\n\n" + "\n\n".join(lines)

    if len(text) > 4000:
        text = text[:4000] + "\n_(truncado)_"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Actualizar", callback_data="stats_refresh"),
            InlineKeyboardButton("🔙 Menu", callback_data="back_main"),
        ]
    ])
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
