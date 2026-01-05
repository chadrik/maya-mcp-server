"""MCP helper"""

from __future__ import annotations

import ast
import json
import sys
import traceback
from typing import Any


# Try importing Qt from PySide2 (Maya 2022-2023) or PySide6 (Maya 2024+)
try:
    from PySide2.QtCore import QIODevice, QTimer  # type: ignore[import-not-found]
    from PySide2.QtNetwork import (  # type: ignore[import-not-found]
        QHostAddress,
        QTcpServer,
        QTcpSocket,
    )
except ImportError:
    try:
        from PySide6.QtCore import QIODevice, QTimer
        from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket
    except ImportError:
        # Qt not available - Qt server functions will fail gracefully
        QTcpServer = None
        QTcpSocket = None
        QHostAddress = None
        QTimer = None
        QIODevice = None

CAPTURE_VARIABLE = "_mcp_result"


def prepare_code_for_result_capture(
    code: str, capture_variable: str = CAPTURE_VARIABLE
) -> tuple[str, bool]:
    """
    Transform Python code to capture the result of the final expression.

    If the final statement is a standalone expression at the module level
    (not nested in a loop, function, or class, and not an assignment),
    prepends `_mcp_result = ` to capture its value.

    Args:
        code: Python source code string

    Returns:
        A tuple of (transformed_code, was_transformed).
        If no transformation was needed, returns (original_code, False).
    """
    code = code.rstrip()

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, False

    if not tree.body:
        return code, False

    last_stmt = tree.body[-1]

    # Only transform standalone expressions
    # ast.Expr is a statement node that wraps an expression value
    # This excludes: assignments, augmented assignments, annotated assignments,
    # function/class definitions, control flow (if/for/while/try), imports, etc.
    if not isinstance(last_stmt, ast.Expr):
        return code, False

    # Get the expression as a string using ast.unparse (Python 3.9+)
    expr_str = ast.unparse(last_stmt.value)

    # Build the new code: all statements except the last + new assignment
    # We use ast.unparse for preceding statements to handle edge cases like
    # semicolon-separated statements on the same line (e.g., "x = 1; 2")
    preceding_stmts = tree.body[:-1]
    if preceding_stmts:
        before = "\n".join(ast.unparse(stmt) for stmt in preceding_stmts) + "\n"
    else:
        before = ""

    new_stmt = f"{capture_variable} = {expr_str}\n"

    return before + new_stmt, True


class StreamWriter:
    """Custom writer that captures output for MCP Resource streaming."""

    def __init__(self, stream_type: str, original: Any) -> None:
        self.stream_type = stream_type
        self._wrapped = original
        self._buffer: list[str] = []

    def write(self, text: str) -> None:
        if text:
            self._buffer.append(text)
        if self._wrapped:
            self._wrapped.write(text)

    def flush(self) -> None:
        if self._wrapped:
            self._wrapped.flush()

    def get_buffer(self) -> str:
        result = "".join(self._buffer)
        self._buffer.clear()
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


_stdout_writer: StreamWriter | None = None
_stderr_writer: StreamWriter | None = None


def install_stream_capture() -> str:
    """Install stream capture for stdout/stderr."""
    global _stdout_writer
    global _stderr_writer

    if _stdout_writer is None:
        _stdout_writer = StreamWriter("stdout", sys.stdout)
        sys.stdout = _stdout_writer
    if _stderr_writer is None:
        _stderr_writer = StreamWriter("stderr", sys.stderr)
        sys.stderr = _stderr_writer
    return json.dumps({"success": True})


def uninstall_stream_capture() -> str:
    """Remove stream capture and restore original streams."""
    global _stdout_writer
    global _stderr_writer

    if _stdout_writer is not None:
        sys.stdout = _stdout_writer._wrapped
        _stdout_writer = None
    if _stderr_writer is not None:
        sys.stderr = _stderr_writer._wrapped
        _stderr_writer = None
    return json.dumps({"success": True})


def get_buffered_output() -> str:
    """Get buffered stdout/stderr and clear buffers."""
    stdout = _stdout_writer.get_buffer() if _stdout_writer else ""
    stderr = _stderr_writer.get_buffer() if _stderr_writer else ""
    return json.dumps({"stdout": stdout, "stderr": stderr})


def get_session_info() -> str:
    """Return session information as JSON."""
    import getpass
    import os

    import maya.cmds as cmds

    scene_path = cmds.file(query=True, sceneName=True) or ""
    scene_name = os.path.basename(scene_path) if scene_path else "untitled"
    return json.dumps(
        {
            "pid": os.getpid(),
            "user": getpass.getuser(),
            "maya_version": cmds.about(version=True),
            "scene_name": scene_name,
            "scene_path": scene_path,
        }
    )


def execute(code: str, result_type: str = "NONE") -> str:
    """Execute code and return result as JSON."""
    result = None
    error = None
    context = globals()
    try:
        modified_code, was_modified = prepare_code_for_result_capture(code)
        if result_type != "NONE" and was_modified is False:
            raise RuntimeError(
                "Results were requested but the code cannot be modified to capture a result."
                "If you want to capture a result, make sure that the last line of code is in "
                "the module scope (i.e. not in a function or loop"
            )

        exec(compile(modified_code, "<mcp>", "exec"), context)
        if was_modified:
            result = context[CAPTURE_VARIABLE]
            if result_type == "JSON":
                result = json.dumps(result)

    except Exception as e:
        error = {
            "type": f"{type(e).__module__}.{type(e).__name__}",
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
    return json.dumps({"result": result, "error": error})


def start_command_port(port: int) -> str:
    import maya.cmds as cmds

    cmds.commandPort(name=f":{port}", sourceType="python")
    return json.dumps({"success": True, "port": port})


class QtCommandServer:
    """Qt-based TCP command server for Maya MCP.

    Runs on Maya's main thread using Qt's event loop.
    Uses QTimer for non-blocking I/O processing.
    Supports multiple concurrent client connections.
    """

    def __init__(self, port: int = 0):
        if QTcpServer is None:
            raise RuntimeError("Qt not available - cannot create command server")

        self._server = QTcpServer()
        # client_id -> {socket, input_buffer, output_queue}
        self._clients: dict[int, dict[str, Any]] = {}
        self._process_timer = QTimer()
        self._port = port
        self._running = False
        self._next_client_id = 0

        # Connect signals
        self._server.newConnection.connect(self._on_new_connection)
        self._process_timer.timeout.connect(self._process_messages)

    def start(self) -> None:
        """Start listening on OS-assigned port."""
        # Listen on loopback with OS-assigned port (port 0)
        if not self._server.listen(QHostAddress.LocalHost, self._port):
            raise RuntimeError(f"Failed to start server: {self._server.errorString()}")

        # if port was 0, it's OS-assigned, so reassign new value
        self._port = self._server.serverPort()
        self._running = True

        # Start message processing timer (check every 50ms)
        self._process_timer.start(50)

    def stop(self) -> None:
        """Stop the server and close connections."""
        self._running = False
        self._process_timer.stop()

        # Disconnect all clients
        for client_id in list(self._clients.keys()):
            client_info = self._clients[client_id]
            client_info["socket"].disconnectFromHost()

        self._clients.clear()
        self._server.close()

    @property
    def port(self) -> int:
        """Get the actual port the server is listening on."""
        return self._port

    def _on_new_connection(self) -> None:
        """Handle new client connection."""
        socket = self._server.nextPendingConnection()

        # Assign unique client ID
        client_id = self._next_client_id
        self._next_client_id += 1

        # Store client info
        self._clients[client_id] = {"socket": socket, "input_buffer": "", "output_queue": []}

        # Connect signals with client_id
        socket.readyRead.connect(lambda cid=client_id: self._on_ready_read(cid))
        socket.disconnected.connect(lambda cid=client_id: self._on_disconnected(cid))

    def _on_ready_read(self, client_id: int) -> None:
        """Read data from client (called by Qt signal)."""
        # Just mark that data is available; actual processing in timer
        pass

    def _on_disconnected(self, client_id: int) -> None:
        """Handle client disconnect."""
        if client_id in self._clients:
            del self._clients[client_id]

    def _process_messages(self) -> None:
        """Process incoming/outgoing messages (called by timer)."""
        # Cleanup stale clients (disconnected sockets)
        stale_clients = []
        for client_id, client_info in self._clients.items():
            socket = client_info["socket"]
            if not socket.isValid() or socket.state() != QTcpSocket.ConnectedState:
                stale_clients.append(client_id)

        for client_id in stale_clients:
            del self._clients[client_id]

        # Process each client
        for client_id, client_info in list(self._clients.items()):
            socket = client_info["socket"]
            input_buffer = client_info["input_buffer"]
            output_queue = client_info["output_queue"]

            # Process incoming messages
            if socket.bytesAvailable() > 0:
                data = bytes(socket.readAll()).decode("utf-8")
                input_buffer += data
                client_info["input_buffer"] = input_buffer

                # Process complete lines
                while "\n" in input_buffer:
                    line, input_buffer = input_buffer.split("\n", 1)
                    client_info["input_buffer"] = input_buffer
                    if line.strip():
                        self._handle_message(client_id, line.strip())

            # Process outgoing messages
            if output_queue:
                message = output_queue.pop(0)
                socket.write((message + "\n").encode("utf-8"))
                socket.flush()

    def _handle_message(self, client_id: int, line: str) -> None:
        """Handle a complete JSON message."""
        if client_id not in self._clients:
            return

        output_queue = self._clients[client_id]["output_queue"]
        request: Any = None

        try:
            request = json.loads(line)
            response = self._dispatch_request(request)
            output_queue.append(json.dumps(response))
        except Exception as e:
            error_response = {
                "id": request.get("id") if isinstance(request, dict) else None,
                "result": None,
                "error": {
                    "type": f"{type(e).__module__}.{type(e).__name__}",
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                },
            }
            output_queue.append(json.dumps(error_response))

    def _dispatch_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch request to appropriate handler."""
        method = request.get("method")
        params = request.get("params", {})
        req_id = request.get("id")

        try:
            # Dispatch to existing helper functions
            if method == "execute":
                result_str = execute(params.get("code", ""), params.get("result_type", "NONE"))
                result_obj = json.loads(result_str)
                return {
                    "id": req_id,
                    "result": result_obj.get("result"),
                    "error": result_obj.get("error"),
                }

            elif method == "get_session_info":
                result_str = get_session_info()
                return {"id": req_id, "result": json.loads(result_str), "error": None}

            elif method == "install_stream_capture":
                install_stream_capture()
                return {"id": req_id, "result": {"success": True}, "error": None}

            elif method == "uninstall_stream_capture":
                uninstall_stream_capture()
                return {"id": req_id, "result": {"success": True}, "error": None}

            elif method == "get_buffered_output":
                result_str = get_buffered_output()
                return {"id": req_id, "result": json.loads(result_str), "error": None}

            elif method == "create_module":
                # Import create_module from maya_bootstrap
                create_module_func = globals().get("create_module")
                if create_module_func is None:
                    return {
                        "id": req_id,
                        "result": None,
                        "error": {"message": "create_module function not available"},
                    }
                result_str = create_module_func(
                    params.get("name", ""), params.get("code", ""), params.get("overwrite", False)
                )
                result_obj = json.loads(result_str)
                if "error" in result_obj:
                    return {"id": req_id, "result": None, "error": {"message": result_obj["error"]}}
                return {"id": req_id, "result": result_obj, "error": None}

            elif method == "ping":
                return {"id": req_id, "result": "pong", "error": None}

            else:
                return {
                    "id": req_id,
                    "result": None,
                    "error": {"message": f"Unknown method: {method}"},
                }
        except Exception as e:
            return {
                "id": req_id,
                "result": None,
                "error": {
                    "type": f"{type(e).__module__}.{type(e).__name__}",
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                },
            }


# Global Qt server instance
_qt_server: QtCommandServer | None = None


def start_qt_server(port: int) -> str:
    """Start the Qt command server and return the port number."""
    global _qt_server

    if _qt_server is not None:
        return json.dumps({"port": _qt_server.port, "already_running": True})

    try:
        _qt_server = QtCommandServer(port)
        _qt_server.start()
        return json.dumps({"port": _qt_server.port, "already_running": False})
    except Exception as e:
        return json.dumps(
            {
                "error": {
                    "type": f"{type(e).__module__}.{type(e).__name__}",
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                }
            }
        )


def stop_qt_server() -> str:
    """Stop the Qt command server."""
    global _qt_server
    if _qt_server:
        _qt_server.stop()
        _qt_server = None
    return json.dumps({"success": True})


def get_qt_server_port() -> str:
    """Get the port of the running Qt server."""
    if _qt_server is None:
        return json.dumps({"error": "Server not running"})
    return json.dumps({"port": _qt_server.port})
