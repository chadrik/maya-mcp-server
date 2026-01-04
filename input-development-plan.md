
# `maya-mcp-server`

Write a Model Context Protocol (MCP) server for Autodesk Maya, a digital content creation application.

The goal of the project is to enable a single MCP server to interact with multiple Maya sessions, so that once a server is started on a user's local machine and registered with a client like Claude Code, it can respond to changes such as new Maya sessions started and shutdown by the user (rather than need to create a separate MCP server for each Maya session).

## Similar tools
Advantages over [MayaMCP](https://github.com/PatrickPalmer/MayaMCP/):
* Supports multiple Maya sessions from a single server
* Clients have full expressive ability of python, rather than being limited to a bespoke set of tools
* Supports streaming output for long-running tasks
* Easily run using `uvx`
* Clients are given control over namespaces, so they can create virtual modules and make functions available to the user
* Highly efficient via async support (e.g. possibility to scale out to render farms)

Advantages over [ChatGPT4Maya](https://github.com/thejoltjoker/ChatGPTforMaya)
* Ability to take advantage of full agentic workflows

## Development Guidelines

* At the heart of the project is the `MayaClient`: An async socket server that can send python code to execute in Maya.  Instantiated with a host and port to connect to, and any other relevant info for the server, such as default timeout.
  * Key methods:
    * async `session_info`: Return a `TypedDict` with basic information about the remote session (current file open, process id, logged-in user)
    * async `_boostrap_session`: Called after a successful connection, this method should use `execute_code` to create functions in the remote session for performing any complex "server-side" business logic, such as the behavior required for `write_module` and `execute_code`.
    * async `write_module`: Dynamically create a module in the remote session and populate it with code (e.g. using `types.ModuleType` and `compile`)
      * Arguments:
        * `name` (str): name of the module.  can be a dotted path to a module under a package, in which case the parent packages will be created if they don't exist
        * `code` (str): source code of the module as a string.
        * `overwrite` (bool): whether to overwrite existing modules, or raise an error
    * async `execute_code`: evaluate code using the python command port and capture the result. To keep variables out of the global namespace, and simplify capturing results, it is recommended to first use `write_module` to create functions and classes, then invoke a function using `execute_code`.
      * Arguments:
        * `code` (str): python code to execute. 
        * `result_type` (enum): "NONE", "JSON", or "RAW".  How to interpret the result of the execution.  If set to anything other than NONE, the `code` to evaluate should be an expression so that the result can be captured.  If JSON, the result will be encoded to json and then decoded on the client side.
      * Results:
        * The result of a remote execution will be a `TypedDict` with the following keys:
          * `result` (optional): captured result, or `None` if `result_type` was NONE.  If `result_type` was JSON, will be decoded json result. 
          * `stdout` (str): captured stdout during execution
          * `stderr` (str): captured stderr during execution
          * `error`:  (optional dict) `TypedDict` with exception info, or None, if no exception
            * `type` (str): full dotted path of the exception type  
            * `message` (str): exception message  
            * `traceback` (str): full traceback
    * async `execute_code_streaming`:  Similar to `execute_code`, but returns an object that allows for streaming `stdout` for long-running execution.  Once complete, the returned object provides access to full `TypedDict` info from `execute_code` (result, stdout, stderr, error).
* The system needs a class to track multiple running Maya sessions, and understand when existing sessions have been closed by the user, or new sessions started.
  * We can do automated session discovery, using the fact that Maya starts a MEL command port by default, unless the user has disabled it in their preferences.  This allows us to look for the default command port (known as "commandportDefault") running on the default port of 50007.  Once connected, our tool can issue commands to start a *python* command port on a known port. 
    * Research what port is used for "commandportDefault" if multiple Maya sessions are started (e.g. should we search port 50007 through 50017 to find other default sessions?)
  * For environments where the default command port is not enabled by default, the MCP server can be started with a custom port range which it will scan.
  * The session manager will have a method that, given a host and port range, will look for open command ports and yield a `MayaClient` for each session. If a connection is successful, determine if the command port is a MEL command port or a Python command port.  If it is a MEL command port, issue commands to start a *python* command port on a known port and produce a `MayaClient` for that port.
* The MCP server will provide the following tools (this architecture is somewhat inspired by the [jupyter-mcp-server](https://jupyter-mcp-server.datalayer.tech/reference/tools)) 
  * `list_sessions`: list active Maya sessions. returns a list of dictionaries for each session (with info dict corresponding to `MayaClient.info`), including host, port, user, and currently open scene name.  To keep the execution of this tool fast, we'll want to do periodic background scans to search for new sessions on localhost, and check for existing sessions that have closed.
  * `use_session`:  activate a session for subsequent code interaction (`write_module` and `execute_code`).  A session is identified using the host and port.
  * `write_module`:  corresponds to `MayaClient.write_module`
  * `execute_code`: corresponds to `MayaClient.execute_code` or `MayaClient.execute_code_streaming`.  Has the same arguments as `execute_code`, but with an additional boolean `stream` option: when true, uses `execute_code_streaming` to yield lines of stdout before returning the final result dictionary.

Other guidelines:
  * Use `fastmcp` python library
  * Write unit tests.
  * Create a pyproject.toml file and use `uv run` for running the command and unit tests. 
  * Use type annotated code.
  * Create a README
  * Take advantage of FastMCP's support for async operations, where possible.

Notes for README:

* To suppress the Maya Security Warning popup, set `os.environ['MAYA_ALLOW_COMMAND_PORT'] = '1'`
