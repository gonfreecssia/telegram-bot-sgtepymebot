"""Handlers de comandos (/start, /menu, /help)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import cfg


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Estado", callback_data="estado"),
            InlineKeyboardButton("❓ Ayuda", callback_data="ayuda"),
        ],
        [
            InlineKeyboardButton("⚙️ Configuración", callback_data="config"),
        ],
    ])


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hola. Soy tu bot de monitorizacion.\n"
        "Usa /menu para abrir el menu.",
        reply_markup=main_menu_keyboard(),
    )


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Menu principal",
        reply_markup=main_menu_keyboard(),
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Comandos disponibles:*\n\n"
        "/start — Iniciar bot\n"
        "/menu — Abrir menu principal\n"
        "/help — Mostrar esta ayuda\n\n"
        "⚙️ *Configuracion:*\n"
        "🔍 Validar Servidor — Estado de Portainer\n"
        "📊 Disponibilidad — Resumen externo\n"
        "📋 Contenedores — Lista rapida\n"
        "📄 Detalle — Info completa\n"
        "🎮 Acciones — Controlar contenedores\n\n"
        "🤖 Hostname del bot: " + ("`" + cfg.bot_container_name + "`" if cfg.bot_container_name else "`auto`"),
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )
