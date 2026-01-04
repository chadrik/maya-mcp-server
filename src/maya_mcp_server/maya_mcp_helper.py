"""MCP helper"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any


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
    try:
        if result_type == "NONE":
            exec(compile(code, "<mcp>", "exec"), globals())
        else:
            result = eval(compile(code, "<mcp>", "eval"), globals())
            if result_type == "JSON":
                result = json.dumps(result)
    except Exception as e:
        error = {
            "type": f"{type(e).__module__}.{type(e).__name__}",
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
    return json.dumps({"result": result, "error": error})
