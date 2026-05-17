import sys
import os
import asyncio
import socket

sys.path.insert(0, ".")

from app.bot import (
    portainer_auth,
    get_endpoint_id,
    get_containers,
    is_own_container,
    get_container_name,
    validate_portainer_server,
    list_external_containers,
    external_containers_detailed_status,
    external_availability_check,
    main_menu,
    config_menu,
    OWN_CONTAINER_HOSTNAME,
)


def test_menus():
    """Test that the keyboards have the expected buttons."""
    main_markup = main_menu()
    config_markup = config_menu()
    main_buttons = [btn.text for row in main_markup.inline_keyboard for btn in row]
    config_buttons = [btn.text for row in config_markup.inline_keyboard for btn in row]

    # Main menu
    assert "Estado" in main_buttons, f"Missing 'Estado' in main menu: {main_buttons}"
    assert "Ayuda" in main_buttons, f"Missing 'Ayuda' in main menu: {main_buttons}"
    assert "Configuración" in main_buttons, f"Missing 'Configuración' in main menu: {main_buttons}"

    # Config menu - new buttons
    assert "🔍 Validar Servidor" in config_buttons, f"Missing 'Validar Servidor': {config_buttons}"
    assert "📊 Disponibilidad" in config_buttons, f"Missing 'Disponibilidad': {config_buttons}"
    assert "📋 Contenedores Externos" in config_buttons, f"Missing 'Contenedores Externos': {config_buttons}"
    assert "📄 Estado Detallado" in config_buttons, f"Missing 'Estado Detallado': {config_buttons}"
    assert "Volver" in config_buttons, f"Missing 'Volver': {config_buttons}"

    # Verify callback_data for new buttons
    config_callbacks = [btn.callback_data for row in config_markup.inline_keyboard for btn in row]
    assert "cfg_server" in config_callbacks, f"Missing 'cfg_server' callback"
    assert "cfg_avail" in config_callbacks, f"Missing 'cfg_avail' callback"
    assert "cfg_list" in config_callbacks, f"Missing 'cfg_list' callback"
    assert "cfg_status" in config_callbacks, f"Missing 'cfg_status' callback"
    assert "back_main" in config_callbacks, f"Missing 'back_main' callback"

    print("✓ Menus have correct buttons and callbacks")


def test_own_container_hostname():
    """Test that OWN_CONTAINER_HOSTNAME is set from socket."""
    hostname = socket.gethostname()
    assert OWN_CONTAINER_HOSTNAME == hostname, f"Hostname mismatch: {OWN_CONTAINER_HOSTNAME} != {hostname}"
    assert len(OWN_CONTAINER_HOSTNAME) > 0, "Hostname is empty"
    print(f"✓ Own container hostname: {OWN_CONTAINER_HOSTNAME}")


def test_is_own_container():
    """Test the is_own_container detection logic."""
    hostname = socket.gethostname()

    # Container matching hostname
    own = {"Names": [f"/{hostname}"], "State": "running", "Image": "test"}
    assert is_own_container(own) is True, "Failed to detect own container"

    # Container NOT matching hostname
    other = {"Names": ["/other-container"], "State": "running", "Image": "test"}
    assert is_own_container(other) is False, "Incorrectly detected other container as own"

    # Container with multiple names (one matching)
    multi = {"Names": [f"/{hostname}", "/alias"], "State": "running", "Image": "test"}
    assert is_own_container(multi) is True, "Failed to detect own container with multiple names"

    # Empty names
    empty = {"Names": [], "State": "running", "Image": "test"}
    assert is_own_container(empty) is False, "Empty names incorrectly detected as own"

    print("✓ is_own_container detection works correctly")


def test_get_container_name():
    """Test container name extraction."""
    assert get_container_name({"Names": ["/my-container"]}) == "my-container"
    assert get_container_name({"Names": []}) == "unnamed"
    assert get_container_name({"Names": ["/a", "/b"]}) == "a"
    print("✓ get_container_name extracts names correctly")


async def test_async_functions_exist():
    """Test that all async functions are defined as coroutines."""
    coroutines = [
        portainer_auth, get_endpoint_id, get_containers,
        validate_portainer_server, list_external_containers,
        external_containers_detailed_status, external_availability_check,
    ]
    for fn in coroutines:
        assert asyncio.iscoroutinefunction(fn), f"{fn.__name__} is not a coroutine"
    print("✓ All async functions are defined as coroutines")


if __name__ == "__main__":
    test_menus()
    test_own_container_hostname()
    test_is_own_container()
    test_get_container_name()
    asyncio.run(test_async_functions_exist())
    print("\n✅ All tests passed")
