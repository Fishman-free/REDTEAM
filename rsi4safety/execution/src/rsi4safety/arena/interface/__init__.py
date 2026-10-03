"""Public attack interface (minimal prototype): HTTP sessions + trusted execution."""
from .service import (
    InterfaceConfig,
    InterfaceError,
    InterfaceService,
    QuotaError,
    SURFACE_PATHS,
    token_fingerprint,
)
from .server import serve

__all__ = [
    "InterfaceConfig", "InterfaceError", "InterfaceService", "QuotaError",
    "SURFACE_PATHS", "token_fingerprint", "serve",
]
