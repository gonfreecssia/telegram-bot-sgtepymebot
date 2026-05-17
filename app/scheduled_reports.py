"""Reportes programados (scheduled reports) — F2."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import cfg
from app.logger import log
from app.portainer_client import get_client

log = logging.getLogger(__name__)


async def _build_report_text() -> str:
    """Construir texto del reporte de estado."""
    client = get_client()
    try:
        containers = await client.get_containers()
    except Exception as e:
        return f"⚠️ No se pudo obtener estado de Portainer: {str(e)[:100]}"

    total = len(containers)
    running = sum(1 for c in containers if c.get("State") == "running")
    stopped = total - running

    # Contenedores propios
    own_matches = [
        c for c in containers
        if c.get("Names")
        and (
            c["Names"][0].lstrip("/") == cfg.bot_container_name
            or c["Id"][:12] == cfg.bot_container_name
        )
    ]
    own_name = own_matches[0].get("Names", ["?"])[0].lstrip("/") if own_matches else "?"

    # Caídos
    down = [
        c.get("Names", ["?"])[0].lstrip("/")
        for c in containers
        if c.get("State") != "running"
        and (
            not c.get("Names")
            or (
                c["Names"][0].lstrip("/") != cfg.bot_container_name
                and c["Id"][:12] != cfg.bot_container_name
            )
        )
    ]

    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    text = (
        f"📊 *Reporte de Estado* — {now}\n\n"
        f"🟢 Ejecutándose: {running}/{total}\n"
        f"🔴 Detenidos: {stopped}/{total}\n"
    )

    if down:
        text += f"\n⚠️ *Caídos:*\n" + "\n".join(f"  • {n}" for n in down)
    else:
        text += "\n🎉 Todos los contenedores externos operativos"

    text += f"\n\n🤖 Bot: `{own_name}` — 🟢 OK"
    return text


async def send_scheduled_report(bot) -> None:
    """Enviar reporte a todos los IDs configurados en REPORT_TELEGRAM_IDS."""
    if not cfg.report_schedule:
        log.debug("Scheduled reports disabled (REPORT_SCHEDULE not set)")
        return

    report_ids = cfg.get_report_ids()
    if not report_ids:
        log.debug("No REPORT_TELEGRAM_IDS configured, skipping report")
        return

    text = await _build_report_text()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver menú", callback_data="back_main")]
    ])

    for user_id in report_ids:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            log.info(f"Report sent to user {user_id}")
        except Exception as e:
            log.error(f"Failed to send report to {user_id}: {e}")


def setup_scheduled_tasks(app: Application) -> None:
    """Registrar tareas programadas si REPORT_SCHEDULE está configurado."""
    if not cfg.report_schedule:
        return

    try:
        from telegram.ext import Application
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()
        # REPORT_SCHEDULE es una expresión cron, ej: "0 9 * * *" (diario 9am)
        trigger = CronTrigger.from_crontab(cfg.report_schedule)
        scheduler.add_job(
            send_scheduled_report,
            trigger=trigger,
            args=[app.bot],
            id="scheduled_report",
            name="Daily/weekly report",
            replace_existing=True,
        )
        scheduler.start()
        log.info(f"Scheduled report task registered: {cfg.report_schedule}")
    except Exception as e:
        log.warning(f"Could not setup scheduled reports: {e}")
