"""Type definitions for maya-mcp-server."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypedDict


# Port ranges
# Communication ports: per-client dedicated ports created during bootstrap
# These are filtered out when scanning for configuration ports
COMMUNICATION_PORT_MIN = 50000
COMMUNICATION_PORT_MAX = 60000


class ResultType(str, Enum):
    """How to interpret execution results."""

    NONE = "NONE"  # Don't capture result
    JSON = "JSON"  # JSON encode/decode result
    RAW = "RAW"  # Return raw string result


class PortType(str, Enum):
    """Type of Maya command port."""

    MEL = "mel"
    PYTHON = "python"
    UNKNOWN = "unknown"


class ClientType(str, Enum):
    """Type of client to use for Maya communication."""

    NATIVE = "native"  # Maya's built-in commandPort
    QT = "qt"  # Custom Qt-based TCP server


class ErrorInfo(TypedDict):
    """Exception information from remote execution."""

    type: str  # Full dotted path of exception type
    message: str  # Exception message
    traceback: str  # Full traceback string


class ExecutionResult(TypedDict):
    """Result of remote code execution.

    Note: stdout/stderr are delivered via MCP Resource subscriptions,
    not in this result. Subscribe to:
    - maya://sessions/{host}:{port}/stdout
    - maya://sessions/{host}:{port}/stderr
    """

    result: Any | None  # Captured result (None if ResultType.NONE)
    error: ErrorInfo | None  # Exception info if error occurred


@dataclass
class SessionInfo:
    """Information about a Maya session."""

    session_key: str
    host: str
    port: int
    pid: int
    user: str
    maya_version: str = ""
    scene_name: str = ""
    scene_path: str = ""


@dataclass
class OutputBuffer:
    """Captured stdout/stderr output."""

    stdout: str = ""
    stderr: str = ""


class MayaListeningPort(TypedDict):
    """Information about a listening port for a Maya process."""

    port: int  # Port number
    address: str  # IP address (usually 127.0.0.1)
    process_id: int  # PID of the Maya process


@dataclass
class CommandResponse:
    """Response from a Maya command execution.

    This is the unified return type for _send_receive in both
    MayaClient and MayaQtClient.
    """

    result: Any  # The result value (can be None)
    error: ErrorInfo | None  # Error info if command failed
