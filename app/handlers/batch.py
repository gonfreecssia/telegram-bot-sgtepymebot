"""Handlers para batch operations — start/stop/restart múltiples contenedores."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import cfg
from app.logger import log
from app.portainer_client import get_client
from app.handlers.status import config_menu_inline


# ── Batch selection state (en memoria por sesión) ───────────────────────────
# key: user_id, value: {container_ids: set, action: str, message_id: int}
_batch_selections: dict[int, dict] = {}


def enter_batch_select_mode(user_id: int, action: str) -> None:
    """Iniciar modo de selección múltiple para un usuario."""
    _batch_selections[user_id] = {
        "container_ids": set(),
        "action": action,  # "start" | "stop" | "restart"
        "message_id": None,
    }


def add_to_batch(user_id: int, short_id: str) -> bool:
    """Agregar o quitar un contenedor de la selección batch."""
    if user_id not in _batch_selections:
        return False
    sel = _batch_selections[user_id]
    if short_id in sel["container_ids"]:
        sel["container_ids"].discard(short_id)
        return False
    else:
        sel["container_ids"].add(short_id)
        return True


def get_batch(user_id: int) -> dict | None:
    return _batch_selections.get(user_id)


def clear_batch(user_id: int) -> None:
    if user_id in _batch_selections:
        del _batch_selections[user_id]


def _build_batch_keyboard(
    containers: list,
    selected: set,
    action: str,
) -> list:
    """Construir keyboard de selección múltiple."""
    keyboard = []
    for c in containers:
        name = c.get("Names", ["?"])[0].lstrip("/") if c.get("Names") else "?"
        state = c.get("State", "unknown")
        short_id = c.get("Id", "")[:12]
        is_own = (
            name == cfg.bot_container_name
            or short_id == cfg.bot_container_name
        )
        if is_own:
            continue  # No mostrar el propio bot

        is_selected = short_id in selected
        checkbox = "✅" if is_selected else "⬜"
        emoji = "🟢" if state == "running" else "🔴"

        # Si la acción no aplica al estado actual, deshabilitar
        action_allowed = (
            (action == "start" and state != "running")
            or (action in ("stop", "restart") and state == "running")
        )

        label = f"{checkbox}{emoji} {name}"
        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"batch_toggle_{short_id}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            f"▶️ Ejecutar ({len(selected)})" if selected else "▶️ Ejecutar",
            callback_data="batch_execute",
        )
    ])
    keyboard.append([
        InlineKeyboardButton("🔙 Cancelar", callback_data="batch_cancel"),
    ])
    return keyboard


async def handle_batch_select(query, user_id: int, action: str) -> None:
    """Mostrar menú de selección múltiple para una acción."""
    client = get_client()
    try:
        containers = await client.get_containers()
    except Exception as e:
        log.error(f"Batch select: error getting containers: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)[:200]}")
        return

    enter_batch_select_mode(user_id, action)

    action_labels = {
        "start": "▶️ Iniciar",
        "stop": "⛔ Detener",
        "restart": "🔄 Reiniciar",
    }
    action_label = action_labels.get(action, action)

    keyboard = _build_batch_keyboard(containers, set(), action)
    text = (
        f"*{action_label} — selección múltiple*\n"
        f"Pulsa en cada contenedor para seleccionar\n"
        f"Luego pulsa 'Ejecutar' para confirmar\n\n"
        "_Usa /batch_cancel para cancelar_"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def handle_batch_toggle(query, user_id: int, short_id: str) -> None:
    """Agregar/quitar un contenedor de la selección batch."""
    client = get_client()
    sel = get_batch(user_id)
    if not sel:
        return

    was_added = add_to_batch(user_id, short_id)

    try:
        containers = await client.get_containers()
    except Exception:
        return

    keyboard = _build_batch_keyboard(
        containers,
        sel["container_ids"],
        sel["action"],
    )

    count = len(sel["container_ids"])
    action_labels = {
        "start": "▶️ Iniciar",
        "stop": "⛔ Detener",
        "restart": "🔄 Reiniciar",
    }
    action_label = action_labels.get(sel["action"], sel["action"])

    await query.edit_message_text(
        text=(
            f"*{action_label} — selección múltiple*\n"
            f"Seleccionados: {count}\n"
            "Pulsa en cada contenedor para cambiar selección\n\n"
            "_Usa /batch_cancel para cancelar_"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

    # Feedback visual
    emoji = "✅" if was_added else "⬜"
    await query.answer(f"{emoji} {'Añadido' if was_added else 'Quitado'}", show_alert=False)


async def handle_batch_execute(query, user_id: int) -> None:
    """Ejecutar la acción en todos los contenedores seleccionados."""
    client = get_client()
    sel = get_batch(user_id)
    if not sel or not sel["container_ids"]:
        await query.answer("Nada seleccionado", show_alert=True)
        return

    short_ids = list(sel["container_ids"])
    action = sel["action"]
    count = len(short_ids)

    # Feedback de正在处理
    await query.edit_message_text(
        text=f"⏳ Ejecutando {action} en {count} contenedores...",
    )

    action_names = {"start": "iniciados", "stop": "detenidos", "restart": "reiniciados"}
    success_ids = []
    failed_ids = []

    for short_id in short_ids:
        try:
            containers = await client.get_containers()
            target = next(
                (c for c in containers if c.get("Id", "")[:12] == short_id), None
            )
            if not target:
                failed_ids.append(short_id)
                continue

            full_id = target["Id"]
            if action == "restart":
                await client.container_action(full_id, "restart")
            elif action == "stop":
                await client.container_action(full_id, "stop")
            elif action == "start":
                await client.container_action(full_id, "start")
            success_ids.append(short_id)
        except Exception as e:
            log.error(f"Batch {action} failed for {short_id}: {e}")
            failed_ids.append(short_id)

    clear_batch(user_id)

    text = (
        f"✅ *Resultado del batch {action}*\n"
        f"Exitosos: {len(success_ids)}\n"
    )
    if failed_ids:
        text += f"Fallidos: {len(failed_ids)}\n"
        text += ", ".join(f"`{i}`" for i in failed_ids)

    await query.edit_message_text(
        text,
        reply_markup=config_menu_inline(),
        parse_mode="Markdown",
    )


async def handle_batch_cancel(query, user_id: int) -> None:
    """Cancelar selección batch."""
    clear_batch(user_id)
    await query.answer("Selección cancelada", show_alert=False)
    await query.edit_message_text(
        "❌ Selección cancelada.",
        reply_markup=config_menu_inline(),
    )
