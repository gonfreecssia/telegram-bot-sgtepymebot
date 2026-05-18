"""Parser para callback_data de los botones inline.

Contiene:
- CallbackActionType: acciones sin parametro
- ContainerCallback: acciones con short_id de contenedor
- parse_callback(): factory que devuelve el tipo correspondiente
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional


class CallbackActionType(StrEnum):
    """Acciones de menu sin parametro de contenedor."""

    # Menu principal
    ESTADO = "estado"
    HELP = "ayuda"
    CONFIG = "config"

    # Submenu configuracion
    CFG_SERVER = "cfg_server"
    CFG_AVAIL = "cfg_avail"
    CFG_LIST = "cfg_list"
    CFG_STATUS = "cfg_status"
    CFG_ACTIONS = "cfg_actions"

    # Navegacion
    BACK_CONFIG = "back_config"
    BACK_MAIN = "back_main"
    STATS_INLINE = "stats_inline"
    STATS_REFRESH = "stats_refresh"

    # Batch mode
    BATCH_ENTER_START = "batch_enter_start"
    BATCH_ENTER_STOP = "batch_enter_stop"
    BATCH_ENTER_RESTART = "batch_enter_restart"
    BATCH_EXECUTE = "batch_execute"
    BATCH_CANCEL = "batch_cancel"

    # R2: Confirmacion inline
    CONFIRM_ACTION = "confirm_action"
    CANCEL_ACTION = "cancel_action"


@dataclass
class ContainerCallback:
    """Accion sobre un contenedor especifico (que tiene short_id)."""
    short_id: str
    action: CallbackActionType


def parse_callback(data: str) -> Optional[ContainerCallback | CallbackActionType]:
    """Parsear callback_data string del boton.

    Formatos:
      - "estado", "ayuda", "config" -> CallbackActionType
      - "start_<short_id>" -> ContainerCallback(short_id, START)
      - "stop_<short_id>"  -> ContainerCallback(short_id, STOP)
      - "restart_<short_id>" -> ContainerCallback(short_id, RESTART)
      - "remove_<short_id>"  -> ContainerCallback(short_id, REMOVE)
      - "detail_<short_id>"  -> ContainerCallback(short_id, DETAIL)
      - "batch_toggle_<short_id>" -> ContainerCallback(short_id, BATCH_TOGGLE)
      - "confirm_action_<short_id>_<action>" -> ContainerCallback(short_id, action)
      - "cancel_action" -> CallbackActionType.CANCEL_ACTION
    """
    if data is None:
        return None

    # Acciones sin parametro
    simple_map = {
        "estado": CallbackActionType.ESTADO,
        "ayuda": CallbackActionType.HELP,
        "config": CallbackActionType.CONFIG,
        "cfg_server": CallbackActionType.CFG_SERVER,
        "cfg_avail": CallbackActionType.CFG_AVAIL,
        "cfg_list": CallbackActionType.CFG_LIST,
        "cfg_status": CallbackActionType.CFG_STATUS,
        "cfg_actions": CallbackActionType.CFG_ACTIONS,
        "back_config": CallbackActionType.BACK_CONFIG,
        "back_main": CallbackActionType.BACK_MAIN,
        "stats_inline": CallbackActionType.STATS_INLINE,
        "stats_refresh": CallbackActionType.STATS_REFRESH,
        "batch_enter_start": CallbackActionType.BATCH_ENTER_START,
        "batch_enter_stop": CallbackActionType.BATCH_ENTER_STOP,
        "batch_enter_restart": CallbackActionType.BATCH_ENTER_RESTART,
        "batch_execute": CallbackActionType.BATCH_EXECUTE,
        "batch_cancel": CallbackActionType.BATCH_CANCEL,
        "cancel_action": CallbackActionType.CANCEL_ACTION,
    }
    if data in simple_map:
        return simple_map[data]

    # Confirmacion de accion peligrosa
    if data.startswith("confirm_action_"):
        # formato: confirm_action_<short_id>_<action>
        parts = data.split("_", 2)  # ["confirm", "action", "<short_id>_<action>"]
        if len(parts) == 3:
            rest = parts[2]
            # buscar el underscore separando short_id de action
            # short_id tiene 12 chars hex, action es lo que queda
            if len(rest) > 13:
                short_id = rest[:12]
                action_name = rest[13:]  # "stop", "remove", "restart"
                action_map = {
                    "start": CallbackActionType.START,
                    "stop": CallbackActionType.STOP,
                    "restart": CallbackActionType.RESTART,
                    "remove": CallbackActionType.REMOVE,
                }
                if action_name in action_map:
                    return ContainerCallback(short_id, action_map[action_name])
        return None

    # Batch toggle
    if data.startswith("batch_toggle_"):
        short_id = data.replace("batch_toggle_", "")
        return ContainerCallback(short_id, CallbackActionType.START)  # reutilizado como TOGGLE

    # Acciones con short_id
    prefixes = {
        "start_": CallbackActionType.START,
        "stop_": CallbackActionType.STOP,
        "restart_": CallbackActionType.RESTART,
        "remove_": CallbackActionType.REMOVE,
        "detail_": CallbackActionType.DETAIL,
    }
    for prefix, action in prefixes.items():
        if data.startswith(prefix):
            short_id = data[len(prefix):]
            if short_id:
                return ContainerCallback(short_id, action)

    return None
