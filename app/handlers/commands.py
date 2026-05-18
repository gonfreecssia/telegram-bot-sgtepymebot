"""Handlers de comandos (/start, /menu, /help, /broadcast)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import cfg
from app.userdb import get_all_user_ids


def main_menu_keyboard():
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


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola. Soy tu bot de monitorizacion de contenedores.\n\n"
        "Usa /menu para abrir el menu principal.\n"
        "Usa /help para ver todos los comandos disponibles.",
        reply_markup=main_menu_keyboard(),
    )


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Menu principal", reply_markup=main_menu_keyboard()
    )


# ─── R5: Help detallado con ejemplos ──────────────────────────────────────

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "Ayuda del Bot de Monitorizacion\n"
        "===============================\n\n"
        "COMANDOS BASICOS\n"
        "/start - Iniciar el bot\n"
        "/menu - Abrir menu principal\n"
        "/help - Mostrar esta ayuda\n\n"
        "COMANDOS DE CONSULTA\n"
        "/status - Resumen rapido de todos los contenedores\n"
        "/stats [nombre] - Uso de CPU/RAM de uno o todos los contenedores\n"
        "  Ejemplo: /stats portainer\n"
        "  Ejemplo: /stats (muestra todos)\n\n"
        "COMANDOS DE CONTROL\n"
        "/logs <nombre> [lineas] - Ver logs de un contenedor\n"
        "  Ejemplo: /logs telegram-bot\n"
        "  Ejemplo: /logs portainer 100\n\n"
        "COMANDOS DE OPERACION MASIVA\n"
        "/batch_start - Seleccionar y arrancar varios contenedores\n"
        "/batch_stop - Seleccionar y detener varios contenedores\n"
        "/batch_restart - Seleccionar y reiniciar varios contenedores\n\n"
        "CONFIGURACION\n"
        "/broadcast <mensaje> - Enviar mensaje a todos los usuarios (solo admins)\n"
        "  Ejemplo: /broadcast Mantenimiento programado a las 22:00\n"
        "/setlang es|en - Cambiar idioma del bot\n"
        "  Ejemplo: /setlang en\n\n"
        "NAVEGACION POR MENU\n"
        "Desde el menu puedes:\n"
        "- Ver estado general de todos los contenedores\n"
        "- Ver stats en tiempo real (CPU, RAM, red)\n"
        "- Ver detalle de cada contenedor\n"
        "- Iniciar/detener/reiniciar contenedores\n"
        "- Eliminar contenedores (con confirmacion)\n"
        "- Operaciones en lote (varios a la vez)\n\n"
        "LIMITES\n"
        "Rate limit: 5 comandos por minuto por usuario\n"
        "Solo usuarios autorizados pueden usar el bot\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── F6: /broadcast ───────────────────────────────────────────────────────

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Enviar mensaje a todos los usuarios autorizados."""
    # Verificar que es un admin (esta en allowed_telegram_ids)
    user_id = str(update.effective_user.id if update.effective_user else 0)
    allowed_ids = [str(x) for x in cfg.allowed_telegram_ids]
    if user_id not in allowed_ids:
        await update.message.reply_text(
            "No tienes permiso para enviar broadcasts."
        )
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

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=int(uid), text=f"Broadcast:\n\n{message}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"Broadcast enviado.\n"
        f"Exito: {sent}\n"
        f"Fallidos: {failed}"
    )