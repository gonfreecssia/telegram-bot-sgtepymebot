"""Configuración centralizada del bot."""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Configuración del bot. Carga de variables de entorno con defaults."""
    
    # Telegram
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    
    # Portainer
    portainer_url: str = field(default_factory=lambda: os.getenv("PORTAINER_URL", "http://192.168.1.184:9000"))
    portainer_user: str = field(default_factory=lambda: os.getenv("PORTAINER_USER", "admin"))
    portainer_pass: str = field(default_factory=lambda: os.getenv("PORTAINER_PASSWORD", "casaportainer"))
    
    # Bot
    bot_container_name: str = field(default_factory=lambda: os.getenv("BOT_CONTAINER_NAME", ""))
    
    # Retry config
    max_retries: int = field(default_factory=lambda: int(os.getenv("MAX_RETRIES", "3")))
    retry_base_delay: float = field(default_factory=lambda: float(os.getenv("RETRY_BASE_DELAY", "1.0")))
    
    # Rate limiting
    rate_limit_max_calls: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_MAX_CALLS", "5"))
    )
    rate_limit_window: float = field(
        default_factory=lambda: float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60.0"))
    )

    # Health server
    health_port: int = field(
        default_factory=lambda: int(os.getenv("HEALTH_PORT", "8080"))
    )

    def validate(self) -> list[str]:
        """Validar configuración. Retorna lista de errores. Vacío = OK."""
        errors = []
        if not self.telegram_token:
            errors.append("TELEGRAM_BOT_TOKEN no está definido")
        if not self.portainer_url:
            errors.append("PORTAINER_URL no está definido")
        return errors


# Singleton global
cfg = Config()
