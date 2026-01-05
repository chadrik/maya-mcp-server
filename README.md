# maya-mcp-server

MCP server for interacting with Autodesk Maya sessions.

## Features

- **Multi-session support**: Manage multiple Maya sessions from a single MCP server. The server scans for new Maya sessions that have been started and shutdown by the user.
- **Full Python expressiveness**: Execute arbitrary Python code, not just predefined tools. Agents can create virtual python modules to expose functions for execution, including by the user.
- **Streaming output**: Real-time log streaming for long-running operations.  Agents can subscribe to the output from the active Maya session, so that they're aware of updates made by their code or by the user.
- **Zero Maya-side setup**: Leverages Maya's default command port
- **Easy installation**: Install and run via `uvx maya-mcp-server`

## Installation

```bash
# Using uvx (recommended)
uvx maya-mcp-server

# Or install with pip
pip install maya-mcp-server
```

## Usage

### Claude Code Configuration

Add to your Claude Code MCP configuration, run:

```commandline
claude mcp add --transport stdio maya -- uvx maya-mcp-server
```

The default scope is "local", which adds it to your `~/.claude.json` keyed to a particular project directory.  Setting `--scope=user` adds to `~/.claude.json` across all projects, and `--scope=project` to add the configuration into a `.mcp.json` in the current project directory, so that it can be commited to your repo.

For local development use: 
```commandline
claude mcp add --transport stdio maya -- uv run --directory /path/to/maya-mcp-server/ maya-mcp-server
```

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

```json
      "mcpServers": {
        "maya": {
          "type": "stdio",
          "command": "uv",
          "args": [
            "run",
            "--directory",
            "/Users/chad/dev/maya-mcp-server",
            "maya-mcp-server"
          ],
          "env": {
            "PYTHONUNBUFFERED": "1"
          }
        }
      },
```

### Maya Setup

The server automatically discovers Maya sessions via command ports. To enable a Python command port in Maya:

```python
import maya.cmds as cmds
cmds.commandPort(name=":7002", sourceType="python")
```

Or add to your `userSetup.py` for automatic startup.

## Tools

- `list_sessions`: List all active Maya sessions
- `use_session`: Activate a session for subsequent operations
- `write_module`: Create a virtual Python module in Maya
- `execute_code`: Execute Python code in the active session

## Similar tools

### [MayaMCP](https://github.com/PatrickPalmer/MayaMCP/)

This looks to be the first publicly available MCP server for Maya and I was inspired by a few aspects of this tool, especially the goal of zero Maya-side setup.

Disadvantages:
* The MCP server is bound to a single Maya session running on the default port.
* It is limited to a bespoke set of tools.  This could be seen as a security advantage, but it cripples the ability of an agent to do just about anything.
* No support for reading stdout or stderr, so the agent is blind to what's happening in the Maya session.
* Can't run via `uvx`, or `pip install` from pypi.

### [ChatGPT4Maya](https://github.com/thejoltjoker/ChatGPTforMaya)

This is the OG LLM integration for Maya, which embeds ChatGPT directly in a PySide window and enables the LLM to respond to user commands and queries by executing code in the session.

Disadvantages:
* Not an MCP server, so it cannot take full advantage of agentic workflows.
* Only works with ChatGPT.

### [Jupyter MCP Server](https://jupyter-mcp-server.datalayer.tech/)

This provided a solid reference for how to create an MCP server that works with multiple remote sessions (in this case, notebooks) to execute arbitrary code.

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Run the server
uv run maya-mcp-server
```

## License

MIT

## TODO

- [x] Start a new command port for each client, so that multiple clients can connect.
- [ ] Provide an option to `execute` to run in global or private context.
- [ ] list_sessions should have one session per maya instance, not per instance x port. we need to track configuration ports separately from communication ports.  For maya-command-ports, there's one commandport per active MCP client.  For qt-command-servers, there's one port for all acive MCP clients.
- [ ] Raise exceptions instead of returning dict with error key
- [ ] Make scene status into a resource
- [ ] Replace TypedDict with dataclasses for tools and resources
- [ ] Yield output as it's printed?
