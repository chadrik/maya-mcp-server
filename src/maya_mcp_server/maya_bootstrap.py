"""Bootstrap code that runs in Maya to provide MCP server functionality.

This file is read and injected into Maya sessions to create a persistent
_mcp module with helper functions. It must be self-contained and use only
standard library imports that are available in Maya's Python environment.

The code is executed via: exec(open(__file__).read(), globals())
"""

from __future__ import annotations

from typing import Any

import sys as _mcp_sys
import json as _mcp_json
import types as _mcp_types
import traceback as _mcp_traceback

# Create the _mcp module
_mcp_module = _mcp_types.ModuleType("_mcp")
_mcp_module.__doc__ = "MCP helper module for Maya integration"


class _MCPStreamWriter:
    """Custom writer that captures output for MCP Resource streaming."""

    def __init__(self, stream_type: str, original: Any) -> None:
        self.stream_type = stream_type
        self._original = original
        self._buffer: list[str] = []

    def write(self, text: str) -> None:
        if text:
            self._buffer.append(text)
        if self._original:
            self._original.write(text)

    def flush(self) -> None:
        if self._original:
            self._original.flush()

    def get_buffer(self) -> str:
        result = "".join(self._buffer)
        self._buffer.clear()
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class _MCPHelper:
    """Helper class for MCP server operations."""

    def __init__(self) -> None:
        self._stdout_writer: _MCPStreamWriter | None = None
        self._stderr_writer: _MCPStreamWriter | None = None
        self._original_stdout: Any = None
        self._original_stderr: Any = None
        self.json = _mcp_json
        self.sys = _mcp_sys
        self.traceback = _mcp_traceback
        self.types = _mcp_types

    def install_stream_capture(self) -> str:
        """Install stream capture for stdout/stderr."""
        if self._stdout_writer is None:
            self._original_stdout = self.sys.stdout
            self._original_stderr = self.sys.stderr
            self._stdout_writer = _MCPStreamWriter("stdout", self._original_stdout)
            self._stderr_writer = _MCPStreamWriter("stderr", self._original_stderr)
            self.sys.stdout = self._stdout_writer
            self.sys.stderr = self._stderr_writer
        return self.json.dumps({"success": True})

    def uninstall_stream_capture(self) -> str:
        """Remove stream capture and restore original streams."""
        if self._original_stdout is not None:
            self.sys.stdout = self._original_stdout
            self.sys.stderr = self._original_stderr
            self._stdout_writer = None
            self._stderr_writer = None
            self._original_stdout = None
            self._original_stderr = None
        return self.json.dumps({"success": True})

    def get_buffered_output(self) -> str:
        """Get buffered stdout/stderr and clear buffers."""
        stdout = self._stdout_writer.get_buffer() if self._stdout_writer else ""
        stderr = self._stderr_writer.get_buffer() if self._stderr_writer else ""
        return self.json.dumps({"stdout": stdout, "stderr": stderr})

    def get_session_info(self) -> str:
        """Return session information as JSON."""
        import maya.cmds as cmds
        import os
        import getpass

        scene_path = cmds.file(query=True, sceneName=True) or ""
        scene_name = os.path.basename(scene_path) if scene_path else "untitled"
        return self.json.dumps({
            "pid": os.getpid(),
            "user": getpass.getuser(),
            "maya_version": cmds.about(version=True),
            "scene_name": scene_name,
            "scene_path": scene_path,
        })

    def execute(self, code: str, result_type: str = "NONE") -> str:
        """Execute code and return result as JSON."""
        result = None
        error = None
        try:
            if result_type == "NONE":
                exec(compile(code, "<mcp>", "exec"), globals())
            else:
                result = eval(compile(code, "<mcp>", "eval"), globals())
                if result_type == "JSON":
                    result = self.json.dumps(result)
        except Exception as e:
            error = {
                "type": f"{type(e).__module__}.{type(e).__name__}",
                "message": str(e),
                "traceback": self.traceback.format_exc(),
            }
        return self.json.dumps({"result": result, "error": error})

    def create_module(self, name: str, code: str, overwrite: bool = False) -> str:
        """Create a virtual module from source code."""
        parts = name.split(".")
        for i in range(len(parts) - 1):
            parent_name = ".".join(parts[: i + 1])
            if parent_name not in self.sys.modules:
                parent_mod = self.types.ModuleType(parent_name)
                setattr(parent_mod, "__path__", [])  # Package marker
                self.sys.modules[parent_name] = parent_mod
        if name in self.sys.modules and not overwrite:
            return self.json.dumps(
                {"error": f"Module '{name}' already exists. Use overwrite=True."}
            )
        module = self.types.ModuleType(name)
        module.__file__ = f"<mcp:{name}>"
        compiled = compile(code, module.__file__, "exec")
        exec(compiled, module.__dict__)
        self.sys.modules[name] = module
        if len(parts) > 1:
            parent = self.sys.modules[".".join(parts[:-1])]
            setattr(parent, parts[-1], module)
        return self.json.dumps({"success": True, "message": f"Module '{name}' created"})


# Install helper instance in the module
_mcp_module.helper = _MCPHelper()  # type: ignore[attr-defined]
_mcp_module.StreamWriter = _MCPStreamWriter  # type: ignore[attr-defined]
_mcp_module.Helper = _MCPHelper  # type: ignore[attr-defined]

# Register module in sys.modules
_mcp_sys.modules["_mcp"] = _mcp_module
