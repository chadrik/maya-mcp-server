# Maya MCP Server - Development Plan

## Overview

This document outlines the development plan for `maya-mcp-server`, a Model Context Protocol (MCP) server for Autodesk Maya that enables AI assistants like Claude Code to interact with multiple Maya sessions from a single server instance.

## Project Goals

1. **Multi-session support**: A single MCP server manages multiple Maya sessions simultaneously
2. **Full Python expressiveness**: Clients can execute arbitrary Python code, not just predefined tools
3. **Streaming output**: Support for long-running operations with real-time stdout streaming
4. **Zero Maya-side setup**: Leverage Maya's default command port for automatic session discovery
5. **Easy installation**: Installable and runnable via `uvx maya-mcp-server`
6. **Namespace control**: Clients can create virtual modules and expose functions to users

## Research Findings

### Maya Command Port System

Maya provides socket-based command execution through `commandPort`:

- **Default MEL port**: `commandportDefault` on port **50007** (configurable in Maya Preferences > Applications > External Communication)
- **Port format**: INET sockets use `:port_number` format (e.g., `:7001`)
- **Source types**: `mel` (default) or `python`
- **Buffer size**: Default 4096 characters; commands exceeding this close the connection
- **Security**: No authentication required; all commands execute with Maya user permissions
- **Multiple ports**: Maya supports multiple simultaneous command ports
- **Response format**: Results returned as UTF-8 with null terminator (`\n\x00`)
- **IPv4 only**: Command ports only use IPv4; IPv6 ports Maya opens are for internal use and should be ignored

**Multiple Maya Sessions**:
- Each Maya instance attempts to open `commandportDefault` on port 50007
- If port 50007 is occupied, subsequent instances fail to open the default port
- Users must manually configure unique ports or use userSetup scripts
- Query open ports via `cmds.commandPort(listPorts=True)`

### Maya Command Port Execution Behavior

**Critical**: Maya's Python command port has unique execution semantics that differ from a standard Python REPL:

1. **Isolated Scope**: Each command runs in a fresh local namespace. Variables defined in one command are NOT available in subsequent commands.

2. **Statement Return Values**: When using semicolons to separate statements (e.g., `x=1; y=2; x+y`), Maya returns the result of the **first** statement, not the last. This means `x=1; y=2; x+y` returns `None` (from the assignment), not `3`.

3. **Persistence via sys.modules**: The only way to persist state between commands is to store objects in `sys.modules`. Modules stored there remain accessible across commands.

4. **exec() Behavior**: Using `exec(code)` creates variables in a local scope that disappears. To persist definitions, use `exec(code, globals())`.

5. **Import Statements**: `import x; x.value` returns `None` because the import statement's result (None) is returned, not the expression. Use `__import__('x').value` instead.

**Bootstrap Strategy**: To work around these limitations, the server:
1. Creates a persistent `_mcp` module in `sys.modules` containing helper classes
2. Uses `exec(bootstrap_code, globals())` to execute the bootstrap
3. Accesses helpers via `__import__('_mcp').helper.method()` in single expressions

### Session Discovery

Session discovery uses `psutil` to find Maya processes and their listening ports:

1. Find Maya process by name (`Maya`, `maya`, `Maya.exe`, `maya.exe`)
2. Get all TCP LISTEN connections for that process via `process.net_connections()`
3. Filter to IPv4 only (command ports don't use IPv6)
4. Probe each port to determine if it's a command port and whether it speaks MEL or Python

### FastMCP Framework

FastMCP 2.0 is the recommended framework for building MCP servers in Python:

- **Decorator-based tools**: `@mcp.tool` automatically handles protocol details
- **Async-first**: Native support for `async def` tools
- **Type inference**: Uses type hints for schema generation; docstrings become descriptions
- **Resources**: Expose data sources that load into LLM context
- **Progress notifications**: Support for `progressToken` in requests with incremental updates
- **Transports**: stdio (default), SSE, and Streamable HTTP

### Comparison with Existing Tools

| Feature | maya-mcp-server | MayaMCP | ChatGPT4Maya |
|---------|----------------|---------|--------------|
| Multi-session | Yes | No | No |
| Arbitrary Python | Yes | Limited tools | Chat-based |
| Streaming output | Yes | No | No |
| Installation | `uvx` | Clone + setup | Plugin install |
| Maya-side setup | None required | None required | Plugin required |
| Protocol | MCP | MCP | OpenAI API |
| Virtual modules | Yes | No | No |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Client                               │
│                  (Claude Code, etc.)                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ MCP Protocol (stdio/HTTP)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Server (FastMCP)                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Tools                                  │  │
│  │  • list_sessions    • use_session     • unuse_session    │  │
│  │  • write_module     • execute_code    • get_session_info │  │
│  │  • get_output       • add_session                        │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  Resources                                │  │
│  │  • maya://sessions/{host}:{port}/stdout                  │  │
│  │  • maya://sessions/{host}:{port}/stderr                  │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                 SessionManager                            │  │
│  │  • Process-based port discovery (psutil)                  │  │
│  │  • Session lifecycle management                           │  │
│  │  • Active session tracking                                │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
   │ MayaClient  │     │ MayaClient  │     │ MayaClient  │
   │  (Session 1)│     │  (Session 2)│     │  (Session N)│
   └─────────────┘     └─────────────┘     └─────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
   │    Maya     │     │    Maya     │     │    Maya     │
   │  (Port X)   │     │  (Port Y)   │     │  (Port Z)   │
   └─────────────┘     └─────────────┘     └─────────────┘
```

---

## Module Structure

```
maya-mcp-server/
├── pyproject.toml
├── README.md
├── src/
│   └── maya_mcp_server/
│       ├── __init__.py
│       ├── __main__.py          # Entry point for `uvx`
│       ├── server.py            # FastMCP server and tools
│       ├── client.py            # MayaClient class
│       ├── session_manager.py   # SessionManager class
│       ├── types.py             # TypedDict definitions and enums
│       ├── bootstrap.py         # Bootstrap code for Maya sessions
│       └── utils.py             # Maya process discovery utilities
└── tests/
    ├── __init__.py
    ├── conftest.py              # Pytest fixtures
    ├── test_client.py
    ├── test_session_manager.py
    ├── test_server.py
    └── mocks/
        └── maya_mock.py         # Mock Maya command port for testing
```

---

## Implementation Status

### Completed

- **types.py**: `ResultType`, `PortType`, `ErrorInfo`, `ExecutionResult`, `SessionInfo`
- **client.py**: `MayaClient` with connect, disconnect, bootstrap, execute_code, write_module, session_info, stream capture
- **session_manager.py**: `SessionManager` with process-based discovery, session lifecycle, active session tracking
- **server.py**: FastMCP server with all tools (list_sessions, use_session, unuse_session, execute_code, write_module, get_session_info, get_output, add_session) and resources
- **bootstrap.py**: Persistent `_mcp` module with helper class for execution, module creation, stream capture
- **utils.py**: `get_maya_process()`, `get_maya_listening_ports()` using psutil
- **__main__.py**: CLI entry point with argument parsing

### Pending

- **MEL-to-Python port conversion**: Logic exists in `_probe_port()` but untested (requires Maya with default MEL port enabled)
- **Real-time streaming**: Stream capture infrastructure exists but MCP resource push notifications not implemented
- **Tests**: Mock server exists but tests need work to remove side effects

---

## Testing Strategy

### Unit Tests

1. **MayaClient tests** (`test_client.py`):
   - Connection/disconnection
   - Port type detection
   - Code execution with different result types
   - Module creation
   - Error handling
   - Timeout handling

2. **SessionManager tests** (`test_session_manager.py`):
   - Port scanning
   - Session discovery
   - Session activation
   - Dead session pruning
   - Multiple session management

3. **Server tests** (`test_server.py`):
   - Tool invocation
   - Error responses
   - Streaming behavior

### Integration Tests

For integration testing with actual Maya:
- Require Maya to be running with command port open
- Mark tests with `@pytest.mark.integration`
- Skip if Maya not available

---

## Usage Examples

### Claude Code Configuration

Add to Claude Code's MCP configuration:

```json
{
  "mcpServers": {
    "maya": {
      "command": "uvx",
      "args": ["maya-mcp-server"]
    }
  }
}
```

### Opening a Command Port in Maya

If Maya's default command port is not enabled, open one manually in Maya's Script Editor (Python):

```python
import maya.cmds as cmds
cmds.commandPort(name=':7001', sourceType='python')
```

Or enable the default port in Maya Preferences > Applications > Command Port (requires Maya restart).

### Example Interactions

```
User: List my Maya sessions

Claude: [calls list_sessions tool]
Found 2 Maya sessions:
1. localhost:7002 - Maya 2024, Scene: character_rig.ma (user: artist)
2. localhost:7003 - Maya 2024, Scene: untitled (user: artist)

User: Connect to the character rig session and create a helper module

Claude: [calls use_session(host="127.0.0.1", port=7002)]
[calls write_module(name="righelpers", code="...")]
Created module 'righelpers' with joint creation utilities.

User: Use the module to add a spine joint chain

Claude: [calls execute_code(code="import righelpers; righelpers.create_spine(5)")]
Created spine joint chain with 5 joints: spine_01 through spine_05
```

---

## Security Considerations

1. **Local-only by default**: Only scan localhost; remote connections opt-in
2. **No authentication**: Maya command ports have no auth; document this limitation
3. **Code execution warning**: Document that arbitrary Python runs with Maya user permissions
4. **Sandboxing**: Consider optional prefix-based command filtering
5. **Port range limits**: Restrict scanning to configured port ranges only

---

## Future Enhancements

1. **Remote session support**: Connect to Maya on remote hosts (with security warnings)
2. **Session persistence**: Remember previously connected sessions across server restarts
3. **Render farm integration**: Async execution across multiple render nodes
4. **MEL support**: Direct MEL execution in addition to Python
5. **Resource exposure**: Expose scene data as MCP resources for context
6. **Event subscriptions**: Notify clients of Maya events (scene changes, selections)
7. **Batch operations**: Execute same code across multiple sessions
8. **Real-time streaming**: Implement MCP resource push notifications for live stdout/stderr

---

## References

- [FastMCP Documentation](https://gofastmcp.com/)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [Maya commandPort Documentation](https://download.autodesk.com/us/maya/2011help/CommandsPython/commandPort.html)
- [MayaMCP (similar project)](https://github.com/PatrickPalmer/MayaMCP)
- [ChatGPT4Maya](https://github.com/thejoltjoker/ChatGPTforMaya)
