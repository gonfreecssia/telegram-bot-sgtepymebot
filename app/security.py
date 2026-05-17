"""Middleware de seguridad — verifica whitelist antes de procesar callbacks."""
from telegram import Update
from telegram.ext import ContextTypes

from app.config import cfg
from app.logger import log
from app.userdb import is_user_allowed, log_usage


class WhitelistMiddleware:
    """Middleware que bloquea usuarios no autorizados.
    
    Uso en bot.py:
        app.add_handler(WhitelistMiddleware(button_handler))
    """

    def __init__(self, handler):
        self.handler = handler

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user:
            return

        user_id = update.effective_user.id
        username = update.effective_user.username or ""

        if not is_user_allowed(user_id):
            log.warning(f"Unauthorized access attempt from user {user_id} ({username})")
            if update.callback_query:
                await update.callback_query.answer(
                    text="⛔ No tienes permiso para usar este bot.",
                    show_alert=True,
                )
            elif update.message:
                await update.message.reply_text(
                    "⛔ No tienes permiso para usar este bot. "
                    "Contacta al administrador."
                )
            return

        # Log usage y continuar
        if update.callback_query and update.callback_query.data:
            log_usage(user_id, update.callback_query.data)
        elif update.message and update.message.text:
            log_usage(user_id, update.message.text)

        return await self.handler(update, ctx)


def whitelist_middleware(handler):
    """Decorador para aplicar whitelist a un handler."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return
        user_id = update.effective_user.id
        username = update.effective_user.username or ""

        if not is_user_allowed(user_id):
            log.warning(f"Blocked unauthorized user {user_id} ({username})")
            if update.callback_query:
                await update.callback_query.answer(
                    "⛔ No tienes permiso para usar este bot.",
                    show_alert=True,
                )
            elif update.message:
                await update.message.reply_text(
                    "⛔ No tienes permiso. Contacta al administrador."
                )
            return

        if update.callback_query and update.callback_query.data:
            log_usage(user_id, update.callback_query.data)
        elif update.message and update.message.text:
            log_usage(user_id, update.message.text)

        return await handler(update, ctx)
    return wrapper
