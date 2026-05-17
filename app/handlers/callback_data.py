"""Definiciones de acciones de callback y parser para el button_handler."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CallbackActionType(Enum):
    """Tipos de acción que vienen desde botones inline."""
    MAIN_MENU = "main"
    STATUS_MENU = "status"
    HELP = "ayuda"
    CONFIG_MENU = "config"
    # Status callbacks
    ESTADO = "estado"
    CFG_SERVER = "cfg_server"
    CFG_AVAIL = "cfg_avail"
    CFG_LIST = "cfg_list"
    CFG_STATUS = "cfg_status"
    CFG_ACTIONS = "cfg_actions"
    BACK_CONFIG = "back_config"
    BACK_MAIN = "back_main"
    # Container actions (prefix-based)
    DETAIL = "detail"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    REMOVE = "remove"


@dataclass(frozen=True)
class ContainerCallback:
    """Callback que incluye el short_id del contenedor."""
    action: CallbackActionType
    short_id: str


def parse_callback(data: str) -> Optional[ContainerCallback | CallbackActionType]:
    """Parsear callback_data string del botón.
    
    Returns:
        - CallbackActionType para callbacks sin parámetro (ej: "estado", "cfg_server")
        - ContainerCallback para acciones con short_id (ej: "start_abc123")
        - None si el callback es desconocido
    """
    # Acciones sin parámetros
    simple_map: dict[str, CallbackActionType] = {
        "estado": CallbackActionType.ESTADO,
        "ayuda": CallbackActionType.HELP,
        "config": CallbackActionType.CONFIG_MENU,
        "cfg_server": CallbackActionType.CFG_SERVER,
        "cfg_avail": CallbackActionType.CFG_AVAIL,
        "cfg_list": CallbackActionType.CFG_LIST,
        "cfg_status": CallbackActionType.CFG_STATUS,
        "cfg_actions": CallbackActionType.CFG_ACTIONS,
        "back_config": CallbackActionType.BACK_CONFIG,
        "back_main": CallbackActionType.BACK_MAIN,
    }
    
    if data in simple_map:
        return simple_map[data]
    
    # Acciones con short_id como prefijo
    prefix_map: dict[str, CallbackActionType] = {
        "detail_": CallbackActionType.DETAIL,
        "start_": CallbackActionType.START,
        "stop_": CallbackActionType.STOP,
        "restart_": CallbackActionType.RESTART,
        "remove_": CallbackActionType.REMOVE,
    }
    
    for prefix, action in prefix_map.items():
        if data.startswith(prefix):
            short_id = data[len(prefix):]
            return ContainerCallback(action=action, short_id=short_id)
    
    return None


# Alias para backwards-compatibility
CallbackData = ContainerCallback
