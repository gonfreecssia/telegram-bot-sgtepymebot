"""Handlers para acciones sobre contenedores (start/stop/restart/remove/detail)."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import cfg
from app.logger import log
from app.portainer_client import get_client

from app.handlers.status import config_menu_inline


def _is_own_container(container: dict) -> bool:
    name = container.get("Names", [""])[0].lstrip("/") if container.get("Names") else ""
    return bool(
        name == cfg.bot_container_name
        or container.get("Id", "")[:12] == cfg.bot_container_name
    )


def _build_actions_keyboard(containers: list, state: str, short_id: str) -> list:
    keyboard = []
    target = next((c for c in containers if c.get("Id", "")[:12] == short_id), None)
    is_own = _is_own_container(target) if target else False
    
    if not is_own:
        if state == "running":
            keyboard.append([
                InlineKeyboardButton("Reiniciar", callback_data=f"restart_{short_id}"),
                InlineKeyboardButton("Detener", callback_data=f"stop_{short_id}"),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("Iniciar", callback_data=f"start_{short_id}"),
            ])
    else:
        keyboard.append([
            InlineKeyboardButton("Reiniciar Bot", callback_data=f"restart_{short_id}"),
        ])
    keyboard.append([InlineKeyboardButton("Volver a Acciones", callback_data="cfg_actions")])
    return keyboard


async def handle_cfg_actions(query) -> None:
    client = get_client()
    try:
        containers = await client.get_containers()
    except Exception as e:
        log.error(f"Error getting containers for actions menu: {e}")
        await query.edit_message_text(
            text="Error conectando a Portainer.", reply_markup=config_menu_inline()
        )
        return

    keyboard = []
    for c in containers:
        name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
        state = c.get("State", "unknown")
        short_id = c.get("Id", "")[:12]
        emoji_state = "running" if state == "running" else "stopped"
        is_own = _is_own_container(c)

        if is_own:
            keyboard.append([
                InlineKeyboardButton(f"BOT: {name}", callback_data=f"detail_{short_id}")
            ])
        else:
            restart_or_start = "restart" if state == "running" else "start"
            restart_cb = f"restart_{short_id}" if state == "running" else f"start_{short_id}"
            stop_btn = (
                InlineKeyboardButton("Detener", callback_data=f"stop_{short_id}")
                if state == "running"
                else InlineKeyboardButton("Eliminar", callback_data=f"remove_{short_id}")
            )
            keyboard.append([
                InlineKeyboardButton(f"{name} ({emoji_state})", callback_data=f"detail_{short_id}"),
                InlineKeyboardButton(restart_or_start, callback_data=restart_cb),
                stop_btn,
            ])

    keyboard.append([InlineKeyboardButton("Volver", callback_data="back_config")])
    await query.edit_message_text(
        text="Acciones sobre contenedores\nToca un nombre para ver detalles\nrestart=reiniciar  start=iniciar  stop=detener  remove=eliminar",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_detail(query, short_id: str) -> None:
    client = get_client()
    try:
        containers = await client.get_containers()
        target = next(
            (c for c in containers if c.get("Id", "")[:12] == short_id), None
        )
        if not target:
            await query.edit_message_text(
                text=f"Contenedor {short_id} no encontrado.",
                reply_markup=config_menu_inline(),
            )
            return

        inspect = await client.get_container_inspect(target["Id"])
        detail = client.build_container_detail(inspect)
        state = target.get("State", "unknown")
        is_own = _is_own_container(target)

        text = (
            f"{detail.emoji} {detail.name}{' [ESTE BOT]' if is_own else ''}\n\n"
            f"ID: {detail.short_id}\n"
            f"Image: {detail.image}\n"
            f"Estado: {detail.state}\n"
            f"Uptime: {detail.uptime_str}\n"
            f"Restart count: {detail.restart_count}\n"
            f"Network: {detail.network_mode}\n"
            f"Memory: {detail.memory_str}\n"
        )
        if detail.safe_env_count() > 0:
            text += f"Env vars: {detail.safe_env_count()}\n"

        keyboard = _build_actions_keyboard(containers, state, short_id)
        await query.edit_message_text(
            text=text, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        log.error(f"Error showing container detail {short_id}: {e}")
        await query.edit_message_text(
            text=f"Error obteniendo detalle: {str(e)[:200]}",
            reply_markup=config_menu_inline(),
        )


# R2: Confirmation inline para acciones peligrosas

DANGEROUS_ACTIONS = {"stop", "remove"}


async def ask_confirmation(query, short_id: str, action: str) -> None:
    action_labels = {"stop": "detener", "remove": "eliminar"}
    label = action_labels.get(action, action)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Si, continuar", callback_data=f"confirm_action_{short_id}_{action}"),
            InlineKeyboardButton("No, cancelar", callback_data="cancel_action"),
        ]
    ])
    await query.edit_message_text(
        text=(
            f"Confirmar accion\n\n"
            f"Estas a punto de {label} este contenedor.\n"
            f"Esta accion puede interrumpir servicios activos.\n\n"
            f"ID: {short_id}\n\n"
            f"Confirmas?"
        ),
        reply_markup=keyboard,
    )


async def handle_confirm_action(query, short_id: str, action: str) -> None:
    client = get_client()
    action_names = {"start": "iniciado", "stop": "detenido", "restart": "reiniciado", "remove": "eliminado"}

    await query.edit_message_text(text="Procesando...")

    try:
        containers = await client.get_containers()
        target = next((c for c in containers if c.get("Id", "")[:12] == short_id), None)
        if not target:
            await query.edit_message_text(
                text=f"Contenedor {short_id} no encontrado.",
                reply_markup=config_menu_inline(),
            )
            return

        name = target.get("Names", ["?"])[0].lstrip("/") if target.get("Names") else "?"
        is_own = _is_own_container(target)
        full_id = target.get("Id", "")

        if is_own and action in ("stop", "remove"):
            await query.edit_message_text(
                text=f"No puedes {action} el bot (te apagarias a ti mismo).",
                reply_markup=config_menu_inline(),
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

        log.info(f"Action '{action}' confirmed on container {name} ({short_id})")
        await query.edit_message_text(
            text=f"Contenedor {name} {action_names.get(action, action)}.",
            reply_markup=config_menu_inline(),
        )
    except Exception as e:
        log.error(f"Error performing confirmed action {action} on {short_id}: {e}")
        await query.edit_message_text(
            text=f"Error: {str(e)[:200]}",
            reply_markup=config_menu_inline(),
        )


async def handle_cancel_action(query) -> None:
    await query.edit_message_text(
        text="Accion cancelada.",
        reply_markup=config_menu_inline(),
    )


async def handle_container_action(query, short_id: str, action: str) -> None:
    # R2: stop y remove requieren confirmacion inline
    if action in DANGEROUS_ACTIONS:
        await ask_confirmation(query, short_id, action)
        return

    client = get_client()
    action_names = {"start": "iniciado", "stop": "detenido", "restart": "reiniciado", "remove": "eliminado"}

    try:
        containers = await client.get_containers()
        target = next((c for c in containers if c.get("Id", "")[:12] == short_id), None)
        if not target:
            await query.edit_message_text(
                text=f"Contenedor {short_id} no encontrado.",
                reply_markup=config_menu_inline(),
            )
            return

        name = target.get("Names", ["?"])[0].lstrip("/") if target.get("Names") else "?"
        is_own = _is_own_container(target)
        full_id = target.get("Id", "")

        if is_own and action in ("stop", "remove"):
            await query.edit_message_text(
                text=f"No puedes {action} el bot (te apagarias a ti mismo).",
                reply_markup=config_menu_inline(),
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
            text=f"Contenedor {name} {action_names.get(action, action)}.",
            reply_markup=config_menu_inline(),
        )
    except Exception as e:
        log.error(f"Error performing action {action} on {short_id}: {e}")
        await query.edit_message_text(
            text=f"Error: {str(e)[:200]}",
            reply_markup=config_menu_inline(),
        )