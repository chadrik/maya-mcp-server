"""Tests for MayaClient."""

from __future__ import annotations

import pytest

from maya_mcp_server.client import MayaClient, MayaConnectionError
from maya_mcp_server.types import PortType, ResultType
from tests.mocks.maya_mock import MockMayaServer

#
# class TestMayaClientConnection:
#     """Tests for MayaClient connection handling."""
#
#     async def test_connect_success(self, mock_maya_server: MockMayaServer, mock_port: int) -> None:
#         """Test successful connection to Maya."""
#         client = MayaClient(port=mock_port)
#         await client.connect()
#         assert client.is_connected
#         await client.disconnect()
#
#     async def test_connect_failure(self) -> None:
#         """Test connection failure to non-existent server."""
#         client = MayaClient(port=59999, timeout=1.0)
#         with pytest.raises(MayaConnectionError):
#             await client.connect()
#
#     async def test_context_manager(self, mock_maya_server: MockMayaServer, mock_port: int) -> None:
#         """Test async context manager."""
#         async with MayaClient(port=mock_port) as client:
#             assert client.is_connected
#         assert not client.is_connected
#
#     async def test_disconnect_idempotent(
#         self, mock_maya_server: MockMayaServer, mock_port: int
#     ) -> None:
#         """Test that disconnect can be called multiple times."""
#         client = MayaClient(port=mock_port)
#         await client.connect()
#         await client.disconnect()
#         await client.disconnect()  # Should not raise
#
#
# class TestMayaClientPortDetection:
#     """Tests for port type detection."""
#
#     async def test_detect_python_port(
#         self, mock_maya_server: MockMayaServer, mock_port: int
#     ) -> None:
#         """Test detection of Python command port."""
#         async with MayaClient(port=mock_port) as client:
#             port_type = await client._detect_port_type()
#             assert port_type == PortType.PYTHON
#
#     async def test_detect_mel_port(self, mock_port: int) -> None:
#         """Test detection of MEL command port."""
#         async with MockMayaServer(port=mock_port, source_type="mel") as server:
#             async with MayaClient(port=mock_port) as client:
#                 port_type = await client._detect_port_type()
#                 # MEL port won't return "2" for "1+1"
#                 assert port_type == PortType.MEL
#
#
# class TestMayaClientExecution:
#     """Tests for code execution."""
#
#     async def test_ping(self, mock_maya_server: MockMayaServer, mock_port: int) -> None:
#         """Test ping functionality."""
#         async with MayaClient(port=mock_port) as client:
#             assert await client.ping()
#
#     async def test_bootstrap(self, mock_maya_server: MockMayaServer, mock_port: int) -> None:
#         """Test session bootstrap."""
#         async with MayaClient(port=mock_port) as client:
#             await client.bootstrap()
#             assert client._bootstrapped
#
#     async def test_session_info(self, mock_maya_server: MockMayaServer, mock_port: int) -> None:
#         """Test getting session info."""
#         async with MayaClient(port=mock_port) as client:
#             info = await client.session_info()
#             assert "pid" in info
#             assert "user" in info
#             assert "maya_version" in info
#             assert info["host"] == "127.0.0.1"
#             assert info["port"] == mock_port
#
#     async def test_execute_code_none(
#         self, mock_maya_server: MockMayaServer, mock_port: int
#     ) -> None:
#         """Test executing code without capturing result."""
#         async with MayaClient(port=mock_port) as client:
#             await client.bootstrap()
#             result = await client.execute_code("x = 1", ResultType.NONE)
#             assert result["error"] is None
#             assert result["result"] is None
#
#     async def test_execute_code_json(
#         self, mock_maya_server: MockMayaServer, mock_port: int
#     ) -> None:
#         """Test executing code with JSON result."""
#         async with MayaClient(port=mock_port) as client:
#             await client.bootstrap()
#             result = await client.execute_code("[1, 2, 3]", ResultType.JSON)
#             assert result["error"] is None
#             # Note: mock returns None, real Maya would return [1, 2, 3]
#
#     async def test_write_module(self, mock_maya_server: MockMayaServer, mock_port: int) -> None:
#         """Test creating a virtual module."""
#         async with MayaClient(port=mock_port) as client:
#             await client.bootstrap()
#             result = await client.write_module(
#                 "test_module",
#                 "def hello(): return 'world'",
#             )
#             assert "successfully" in result.lower() or "created" in result.lower()
#
#
# class TestMayaClientStreamCapture:
#     """Tests for stream capture."""
#
#     async def test_install_stream_capture(
#         self, mock_maya_server: MockMayaServer, mock_port: int
#     ) -> None:
#         """Test installing stream capture."""
#         async with MayaClient(port=mock_port) as client:
#             await client.bootstrap()
#             await client.install_stream_capture()
#             # Should not raise
#
#     async def test_uninstall_stream_capture(
#         self, mock_maya_server: MockMayaServer, mock_port: int
#     ) -> None:
#         """Test uninstalling stream capture."""
#         async with MayaClient(port=mock_port) as client:
#             await client.bootstrap()
#             await client.install_stream_capture()
#             await client.uninstall_stream_capture()
#             # Should not raise
#
#     async def test_get_buffered_output(
#         self, mock_maya_server: MockMayaServer, mock_port: int
#     ) -> None:
#         """Test getting buffered output."""
#         async with MayaClient(port=mock_port) as client:
#             await client.bootstrap()
#             output = await client.get_buffered_output()
#             assert "stdout" in output
#             assert "stderr" in output
