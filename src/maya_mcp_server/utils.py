import logging
import socket
from collections.abc import Iterator

import psutil

from maya_mcp_server.types import MayaListeningPort


logger = logging.getLogger(__name__)


def get_maya_process() -> Iterator[psutil.Process]:
    """
    Find all Maya processes.

    Yields:
        Maya Process objects
    """
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            name = proc.info["name"]
            # Maya process names vary by platform
            if name in ["Maya", "maya", "maya.exe", "Maya.exe"]:
                yield proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def get_maya_listening_ports() -> Iterator[MayaListeningPort]:
    """
    Get all ports that Maya processes are listening on.

    Yields:
        MayaListeningPort dictionaries with port, address, and process_id
    """
    found_any_maya = False

    for maya_proc in get_maya_process():
        found_any_maya = True
        logger.debug(f"Found Maya process: PID {maya_proc.pid}")

        try:
            # Get all network connections for Maya process
            connections = maya_proc.net_connections(kind="inet")

            for conn in connections:
                # Only get listening TCP connections on IPv4 (command ports are always IPv4)
                if (
                    conn.status == "LISTEN"
                    and conn.type == socket.SOCK_STREAM
                    and conn.family == socket.AF_INET
                ):
                    yield MayaListeningPort(
                        port=conn.laddr.port,
                        address=conn.laddr.ip,
                        process_id=maya_proc.pid,
                    )

        except psutil.AccessDenied:
            logger.warning(
                f"Access denied getting Maya connections for PID {maya_proc.pid} - "
                "try running as administrator/sudo"
            )
            continue

    if not found_any_maya:
        logger.debug("Maya is not running")
