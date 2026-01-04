"""Bootstrap code injected into Maya sessions.

Maya's command port has specific behavior:
- Each command runs in a fresh local namespace
- Statements with `;` return the result of the FIRST statement, not the last
- Modules stored in sys.modules persist between commands
- Use `__import__('module')` to access persistent modules in single expressions

This module provides bootstrap code that creates a persistent `_mcp` module
in sys.modules, accessible via `__import__('_mcp')`.
"""

# Bootstrap code that creates the _mcp module in sys.modules
# This must be executed as multi-line code (not with ; separators)
BOOTSTRAP_CODE = '''
import sys as _mcp_sys
import json as _mcp_json
import types as _mcp_types
import traceback as _mcp_traceback

# Create the _mcp module
_mcp_module = _mcp_types.ModuleType("_mcp")
_mcp_module.__doc__ = "MCP helper module for Maya integration"


class _MCPStreamWriter:
    """Custom writer that captures output for MCP Resource streaming."""

    def __init__(self, stream_type, original):
        self.stream_type = stream_type
        self._original = original
        self._buffer = []

    def write(self, text):
        if text:
            self._buffer.append(text)
        if self._original:
            self._original.write(text)

    def flush(self):
        if self._original:
            self._original.flush()

    def get_buffer(self):
        result = "".join(self._buffer)
        self._buffer.clear()
        return result

    def __getattr__(self, name):
        return getattr(self._original, name)


class _MCPHelper:
    """Helper class for MCP server operations."""

    def __init__(self):
        self._stdout_writer = None
        self._stderr_writer = None
        self._original_stdout = None
        self._original_stderr = None
        self.json = _mcp_json
        self.sys = _mcp_sys
        self.traceback = _mcp_traceback
        self.types = _mcp_types

    def install_stream_capture(self):
        if self._stdout_writer is None:
            self._original_stdout = self.sys.stdout
            self._original_stderr = self.sys.stderr
            self._stdout_writer = _MCPStreamWriter("stdout", self._original_stdout)
            self._stderr_writer = _MCPStreamWriter("stderr", self._original_stderr)
            self.sys.stdout = self._stdout_writer
            self.sys.stderr = self._stderr_writer
        return self.json.dumps({"success": True})

    def uninstall_stream_capture(self):
        if self._original_stdout is not None:
            self.sys.stdout = self._original_stdout
            self.sys.stderr = self._original_stderr
            self._stdout_writer = None
            self._stderr_writer = None
            self._original_stdout = None
            self._original_stderr = None
        return self.json.dumps({"success": True})

    def get_buffered_output(self):
        stdout = self._stdout_writer.get_buffer() if self._stdout_writer else ""
        stderr = self._stderr_writer.get_buffer() if self._stderr_writer else ""
        return self.json.dumps({"stdout": stdout, "stderr": stderr})

    def get_session_info(self):
        import maya.cmds as cmds
        import os
        import getpass
        scene_path = cmds.file(q=True, sceneName=True) or ""
        scene_name = os.path.basename(scene_path) if scene_path else "untitled"
        return self.json.dumps({
            "pid": os.getpid(),
            "user": getpass.getuser(),
            "maya_version": cmds.about(version=True),
            "scene_name": scene_name,
            "scene_path": scene_path
        })

    def execute(self, code, result_type="NONE"):
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
                "traceback": self.traceback.format_exc()
            }
        return self.json.dumps({"result": result, "error": error})

    def create_module(self, name, code, overwrite=False):
        parts = name.split(".")
        for i in range(len(parts) - 1):
            parent_name = ".".join(parts[:i + 1])
            if parent_name not in self.sys.modules:
                parent_mod = self.types.ModuleType(parent_name)
                parent_mod.__path__ = []
                self.sys.modules[parent_name] = parent_mod
        if name in self.sys.modules and not overwrite:
            return self.json.dumps({"error": f"Module '{name}' already exists. Use overwrite=True."})
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
_mcp_module.helper = _MCPHelper()
_mcp_module.StreamWriter = _MCPStreamWriter
_mcp_module.Helper = _MCPHelper

# Register module in sys.modules
_mcp_sys.modules["_mcp"] = _mcp_module
'''

# Access the helper via __import__ (works in single expressions)
_MCP = "__import__('_mcp').helper"

# Templates that use __import__ to access the persistent module
GET_SESSION_INFO = f"{_MCP}.get_session_info()"
EXECUTE_TEMPLATE = f"{_MCP}.execute({{code!r}}, {{result_type!r}})"
CREATE_MODULE_TEMPLATE = f"{_MCP}.create_module({{name!r}}, {{code!r}}, {{overwrite!r}})"
INSTALL_STREAM_CAPTURE = f"{_MCP}.install_stream_capture()"
UNINSTALL_STREAM_CAPTURE = f"{_MCP}.uninstall_stream_capture()"
GET_BUFFERED_OUTPUT = f"{_MCP}.get_buffered_output()"

# Check if bootstrap has been done
CHECK_BOOTSTRAP = "'_mcp' in __import__('sys').modules"
