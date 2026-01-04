"""Bootstrap code that runs in Maya to provide MCP server functionality.

This file is read and injected into Maya sessions to create a persistent
_mcp module with helper functions. It must be self-contained and use only
standard library imports that are available in Maya's Python environment.

The code is executed via: exec(open(__file__).read(), globals())
"""


def create_module(name: str, code: str, overwrite: bool = False) -> str:
    """Create a virtual module from source code."""
    import json
    import sys
    import types

    parts = name.split(".")
    for i in range(len(parts) - 1):
        parent_name = ".".join(parts[: i + 1])
        if parent_name not in sys.modules:
            parent_mod = types.ModuleType(parent_name)
            setattr(parent_mod, "__path__", [])  # Package marker
            sys.modules[parent_name] = parent_mod

    if name in sys.modules and not overwrite:
        return json.dumps({"error": f"Module '{name}' already exists. Use overwrite=True."})
    module = types.ModuleType(name)
    module.__file__ = f"<mcp:{name}>"
    compiled = compile(code, module.__file__, "exec")
    exec(compiled, module.__dict__)
    sys.modules[name] = module
    if len(parts) > 1:
        parent = sys.modules[".".join(parts[:-1])]
        setattr(parent, parts[-1], module)
    return json.dumps({"success": True, "message": f"Module '{name}' created"})
