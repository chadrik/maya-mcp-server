import logging
import socket

import psutil


logger = logging.getLogger(__name__)


def get_maya_process() -> psutil.Process | None:
    """Find Maya process."""
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            name = proc.info["name"]
            # Maya process names vary by platform
            if name in ["Maya", "maya", "maya.exe", "Maya.exe"]:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def get_maya_listening_ports() -> list[dict]:
    """Get all ports Maya is listening on."""
    maya_proc = get_maya_process()

    if not maya_proc:
        logger.debug("Maya is not running")
        return []

    logger.debug(f"Found Maya process: PID {maya_proc.pid}")

    listening_ports = []

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
                listening_ports.append(
                    {
                        "port": conn.laddr.port,
                        "address": conn.laddr.ip,
                    }
                )

    except psutil.AccessDenied:
        logger.warning("Access denied getting Maya connections - try running as administrator/sudo")
        return []

    return listening_ports
