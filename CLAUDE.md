# Maya MCP Server - Developer Guide

## ⚠️ Critical Testing Rules

1. **Prefer testing with open Maya session** - Use manual test scripts in project root
2. **Module updates** - Always update `maya_mcp` module when reconnecting (module may be cached from previous sessions)

## 🏗️ Architecture Overview

### Dedicated CommandPort Design

**Two types of ports per Maya session:**

1. **Configuration Port** (e.g., 7001): One per Maya session (PID)
   - Used only for bootstrap and discovery
   - Clients connect temporarily to create dedicated ports
   - Outside communication port range

2. **Communication Ports** (50000-60000): One per MCP client
   - Created during bootstrap via `start_command_port()`
   - Dedicated to single client for entire session
   - Automatically filtered during port scanning

```
Maya Session (PID 8453)
├── Configuration Port: 7001 (Python commandPort)
│   └── Used for bootstrap only - clients disconnect after setup
└── Communication Ports: 50000-60000 range
    ├── Port 50625 → MCP Client 1
    ├── Port 51234 → MCP Client 2
    └── Port 52891 → MCP Client 3
```

### SessionManager Port Tracking

```python
self._sessions: dict[str, MayaClient]          # "host:port" -> client (communication port)
self._config_to_session: dict[str, str]        # "host:port" -> session key (config → comm mapping)
```

**Key insight**: Don't need `_probed_ports` set - use `_config_to_session` to track which configuration ports we've already used to create sessions.

### Port Constants

```python
# src/maya_mcp_server/types.py
COMMUNICATION_PORT_MIN = 50000
COMMUNICATION_PORT_MAX = 60000
```

Filter these out when scanning for configuration ports in `_scan_for_sessions()`.

## 🔧 Bootstrap Process

### Critical Bootstrap Requirements

1. **Function return values**: All helper functions in `maya_mcp_helper.py` MUST return strings (usually JSON)
   - If function returns `None`, `_send_receive()` hangs waiting for response
   - Example: `start_command_port()` returns `json.dumps({"success": True, "port": port})`

2. **Module updates on reconnect**: When `CHECK_BOOTSTRAP` returns `True`:
   ```python
   # Always update module to get latest functions
   cmd = CREATE_MODULE_TEMPLATE.format(name="maya_mcp", code=helper_code, overwrite=True)
   ```

3. **Connect to dedicated port**: After creating commandPort, MUST connect:
   ```python
   new_client = MayaClient(host=self.host, port=new_port, ...)
   await new_client.connect()  # ← Critical! Don't return unconnected client
   ```

4. **Wait for port to listen**: Add delay after creating port:
   ```python
   await asyncio.sleep(0.5)  # Let Maya start listening
   ```

### Bootstrap Flow

```
1. Client → Config Port (7001)
2. Detect port type (Python/MEL/Unknown)
3. Check if maya_mcp module exists
4. Update/create maya_mcp module with latest code
5. Generate random port in 50000-60000
6. Execute: maya_mcp.start_command_port(new_port)
7. Wait 0.5s for port to open
8. Create new MayaClient for dedicated port
9. Connect to dedicated port
10. Disconnect from config port (frees for other clients)
11. Return connected client
```

## 🐛 Common Issues & Solutions

### Issue: "module 'maya_mcp' has no attribute 'start_command_port'"
**Cause**: Maya has cached old version of module without new functions
**Solution**: Always `overwrite=True` when module exists (implemented in bootstrap)

### Issue: Connection refused when connecting to dedicated port
**Cause**: Port not listening yet or function returned None
**Solution**:
1. Ensure helper function returns JSON string
2. Add 0.5s delay after `start_command_port()`
3. Check Maya's command port is actually created

### Issue: SessionManager creates infinite dedicated ports
**Cause**: Scanning communication ports and re-probing them
**Solution**: Filter ports in range 50000-60000 during `_scan_for_sessions()`

### Issue: Sessions stored but not retrievable
**Cause**: Key mismatch - stored with communication port, checking with config port
**Solution**: Use `_config_to_session` mapping to track relationships

## 📁 Key Files

### src/maya_mcp_server/types.py
- Port range constants: `COMMUNICATION_PORT_MIN`, `COMMUNICATION_PORT_MAX`
- Type definitions: `ResultType`, `PortType`, `SessionInfo`, `MayaListeningPort`

### src/maya_mcp_server/client.py
- `bootstrap()`: Creates dedicated port and connects to it
- Port range import and usage in bootstrap
- Module update logic when maya_mcp already exists

### src/maya_mcp_server/session_manager.py
- `_scan_for_sessions()`: Filters communication ports, uses `_config_to_session`
- `_probe_port()`: Connects to config port, gets back client on comm port
- `_prune_dead_sessions()`: Cleans up both `_sessions` and `_config_to_session`

### src/maya_mcp_server/maya_mcp_helper.py
- `start_command_port(port: int) -> str`: Creates dedicated port, returns JSON
- All functions return strings (JSON) for proper `_send_receive()` behavior

### src/maya_mcp_server/bootstrap.py
- Template constants: `START_COMMAND_PORT`, etc.
- Code loading: `get_bootstrap_code()`, `get_helper_module_code()`

### src/maya_mcp_server/utils.py
- `get_maya_process() -> Iterator[psutil.Process]`: Finds all Maya processes
- `get_maya_listening_ports() -> Iterator[MayaListeningPort]`: Gets ports with PIDs
- Uses `Iterator` not `Generator` (Generator only for bidirectional communication)

## 🧪 Testing

### Manual Test Scripts (in project root)

```bash
# Basic bootstrap test
uv run python test_bootstrap_simple.py

# SessionManager with dedicated ports
uv run python test_new_session_design.py

# Concurrent operations
uv run python test_concurrent_clients.py

# Verify no reprobing
uv run python test_no_reprobe.py
```

### Expected Test Results

- **1 session discovered** (from config port 7001)
- **Communication port in 50000-60000 range**
- **No duplicate sessions on rescans**
- **Concurrent operations succeed**

## 📝 Maya Command Port Behavior

### Critical Execution Semantics

1. **Isolated Scope**: Each command runs in fresh local namespace
2. **Statement Return**: `x=1; y=2; x+y` returns `None` (first statement), not `3`
3. **Persistence**: Only `sys.modules` persists between commands
4. **exec() Scope**: Use `exec(code, globals())` to persist definitions
5. **Import Issue**: `import x; x.value` returns `None`, use `__import__('x').value`

### Response Format
- Results returned as UTF-8 with null terminator (`\n\x00`)
- Buffer size: 4096 characters default
- IPv4 only (ignore IPv6 ports)

## 🔐 Implementation Status

### ✅ Completed
- Dedicated commandPort architecture
- Configuration/communication port separation (50000-60000 range)
- Bootstrap with module updates
- Multi-session support with proper port tracking
- SessionManager with config-to-session mapping
- Port scanning with communication port filtering
- Concurrent operation support
- Iterator-based port discovery

### 🚧 Pending
- MEL-to-Python port conversion (exists but untested)
- Real-time streaming via MCP resource push notifications
- Unit tests cleanup (currently broken with pgrep issues)

## 🎯 Future Enhancements

1. **Qt-based command server**: Replace commandPort with QtCommandServer for better control
2. **Remote session support**: Connect to Maya on remote hosts
3. **Session persistence**: Remember sessions across server restarts
4. **MEL support**: Direct MEL execution
5. **Event subscriptions**: Notify clients of Maya events

## 📚 Quick Reference

### Port Discovery (utils.py)
```python
for port_info in get_maya_listening_ports():
    port = port_info["port"]        # Port number
    address = port_info["address"]  # Usually 127.0.0.1
    pid = port_info["process_id"]   # Maya PID
```

### Session Scanning (session_manager.py)
```python
# Skip communication ports
if COMMUNICATION_PORT_MIN <= port <= COMMUNICATION_PORT_MAX:
    continue

# Skip already-probed config ports
if config_key in self._config_to_session:
    continue
```

### Bootstrap (client.py)
```python
# Update module if it exists
if check_result.strip() == "True":
    cmd = CREATE_MODULE_TEMPLATE.format(name="maya_mcp", code=helper_code, overwrite=True)
    await self._send_receive(cmd)

# Create dedicated port
new_port = random.randint(COMMUNICATION_PORT_MIN, COMMUNICATION_PORT_MAX)
result = await self._send_receive(START_COMMAND_PORT.format(port=new_port))
await asyncio.sleep(0.5)

# Connect to it
new_client = MayaClient(host=self.host, port=new_port, ...)
await new_client.connect()
return new_client
```

## 🔍 Debugging Tips

1. **Enable logging**: Tests use `logging.basicConfig(level=logging.INFO)`
2. **Check port states**: Use `lsof -i -P | grep LISTEN` to see all listening ports
3. **Module state**: In Maya Script Editor, check `'maya_mcp' in sys.modules`
4. **Port ranges**: Verify communication ports in 50000-60000, config ports outside
5. **Connection tracking**: Print `manager._sessions.keys()` and `manager._config_to_session.keys()`

## 📖 References

- [FastMCP Documentation](https://gofastmcp.com/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Maya commandPort Docs](https://download.autodesk.com/us/maya/2011help/CommandsPython/commandPort.html)
