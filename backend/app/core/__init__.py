"""Cross-cutting application concerns: settings and build identity."""

from .config import Settings, get_settings
from .version import ENGINE_VERSION

__all__ = ["ENGINE_VERSION", "Settings", "get_settings"]
