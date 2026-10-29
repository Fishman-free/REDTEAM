"""Reference defender SDK for the four BYOA transports.

These modules are deliberately small and dependency-free (FastAPI + stdlib)
so a defender can vendor them or copy the transport shape into its own
harness.  The reference agent only pays owner tasks via the CVM wallet MCP.
"""

from .agent import ReferenceAgent
from .conformance import conformance_report
from .pull_client import PullClient
from .servers import (
    create_a2a_app,
    create_hosted_mcp_app,
    create_pull_app,
    create_webhook_app,
)
from .wallet_client import WalletMCPClient

__all__ = [
    "PullClient",
    "ReferenceAgent",
    "WalletMCPClient",
    "conformance_report",
    "create_a2a_app",
    "create_hosted_mcp_app",
    "create_pull_app",
    "create_webhook_app",
]
