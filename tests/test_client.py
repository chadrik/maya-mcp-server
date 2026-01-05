"""Tests for MayaClient and MayaQtClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maya_mcp_server.client import (
    MayaClient,
    MayaExecutionError,
    MayaQtClient,
)
from maya_mcp_server.types import (
    CommandResponse,
    OutputBuffer,
    ResultType,
    SessionInfo,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def maya_client() -> MayaClient:
    """Create a MayaClient instance for testing."""
    client = MayaClient(host="127.0.0.1", port=7001)
    # Simulate connected state with a MagicMock that has sync methods
    client._writer = MagicMock()
    client._writer.is_closing.return_value = False
    client._reader = MagicMock()
    return client


@pytest.fixture
def qt_client() -> MayaQtClient:
    """Create a MayaQtClient instance for testing."""
    client = MayaQtClient(host="127.0.0.1", port=50000)
    # Simulate connected state with a MagicMock that has sync methods
    client._writer = MagicMock()
    client._writer.is_closing.return_value = False
    client._reader = MagicMock()
    return client


# ============================================================================
# BaseMayaClient Tests (via MayaClient)
# ============================================================================


class TestBaseMayaClientProperties:
    """Test BaseMayaClient properties."""

    def test_key(self, maya_client: MayaClient) -> None:
        """Test key property returns host:port."""
        assert maya_client.key == "127.0.0.1:7001"

    def test_is_connected_true(self, maya_client: MayaClient) -> None:
        """Test is_connected returns True when writer is open."""
        maya_client._writer.is_closing.return_value = False
        assert maya_client.is_connected is True

    def test_is_connected_false_no_writer(self) -> None:
        """Test is_connected returns False when no writer."""
        client = MayaClient()
        assert client.is_connected is False

    def test_is_connected_false_writer_closing(self, maya_client: MayaClient) -> None:
        """Test is_connected returns False when writer is closing."""
        maya_client._writer.is_closing.return_value = True
        assert maya_client.is_connected is False


class TestOutputBufferMethods:
    """Test output buffer methods."""

    def test_append_output_stdout(self, maya_client: MayaClient) -> None:
        """Test appending stdout."""
        maya_client.append_output(stdout="hello")
        maya_client.append_output(stdout=" world")
        assert maya_client._stdout_buffer == "hello world"
        assert maya_client._stderr_buffer == ""

    def test_append_output_stderr(self, maya_client: MayaClient) -> None:
        """Test appending stderr."""
        maya_client.append_output(stderr="error1")
        maya_client.append_output(stderr="\nerror2")
        assert maya_client._stderr_buffer == "error1\nerror2"
        assert maya_client._stdout_buffer == ""

    def test_append_output_both(self, maya_client: MayaClient) -> None:
        """Test appending both stdout and stderr."""
        maya_client.append_output(stdout="out", stderr="err")
        assert maya_client._stdout_buffer == "out"
        assert maya_client._stderr_buffer == "err"

    def test_get_accumulated_output_clears_by_default(self, maya_client: MayaClient) -> None:
        """Test get_accumulated_output clears buffers by default."""
        maya_client._stdout_buffer = "stdout content"
        maya_client._stderr_buffer = "stderr content"

        output = maya_client.get_accumulated_output()

        assert isinstance(output, OutputBuffer)
        assert output.stdout == "stdout content"
        assert output.stderr == "stderr content"
        assert maya_client._stdout_buffer == ""
        assert maya_client._stderr_buffer == ""

    def test_get_accumulated_output_no_clear(self, maya_client: MayaClient) -> None:
        """Test get_accumulated_output with clear=False."""
        maya_client._stdout_buffer = "stdout content"
        maya_client._stderr_buffer = "stderr content"

        output = maya_client.get_accumulated_output(clear=False)

        assert output.stdout == "stdout content"
        assert output.stderr == "stderr content"
        assert maya_client._stdout_buffer == "stdout content"
        assert maya_client._stderr_buffer == "stderr content"

    def test_clear_output(self, maya_client: MayaClient) -> None:
        """Test clear_output."""
        maya_client._stdout_buffer = "stdout"
        maya_client._stderr_buffer = "stderr"

        maya_client.clear_output()

        assert maya_client._stdout_buffer == ""
        assert maya_client._stderr_buffer == ""


class TestSessionInfo:
    """Test session_info method."""

    @pytest.mark.asyncio
    async def test_session_info(self, maya_client: MayaClient, mocker) -> None:
        """Test session_info returns SessionInfo dataclass."""
        mock_send_receive = mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(
                result={
                    "pid": 12345,
                    "user": "testuser",
                    "maya_version": "2024",
                    "scene_name": "test.ma",
                    "scene_path": "/path/to/test.ma",
                },
                error=None,
            ),
        )

        info = await maya_client.session_info()

        assert isinstance(info, SessionInfo)
        assert info.host == "127.0.0.1"
        assert info.port == 7001
        assert info.pid == 12345
        assert info.user == "testuser"
        assert info.maya_version == "2024"
        assert info.scene_name == "test.ma"
        assert info.scene_path == "/path/to/test.ma"
        mock_send_receive.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_info_empty_response(self, maya_client: MayaClient, mocker) -> None:
        """Test session_info handles empty response."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result=None, error=None),
        )

        info = await maya_client.session_info()

        assert info.host == "127.0.0.1"
        assert info.port == 7001
        assert info.pid == 0
        assert info.user == ""


class TestGetBufferedOutput:
    """Test get_buffered_output method."""

    @pytest.mark.asyncio
    async def test_get_buffered_output(self, maya_client: MayaClient, mocker) -> None:
        """Test get_buffered_output returns OutputBuffer."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(
                result={"stdout": "hello\n", "stderr": "warning\n"},
                error=None,
            ),
        )

        output = await maya_client.get_buffered_output()

        assert isinstance(output, OutputBuffer)
        assert output.stdout == "hello\n"
        assert output.stderr == "warning\n"

    @pytest.mark.asyncio
    async def test_get_buffered_output_empty(self, maya_client: MayaClient, mocker) -> None:
        """Test get_buffered_output handles empty response."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result=None, error=None),
        )

        output = await maya_client.get_buffered_output()

        assert output.stdout == ""
        assert output.stderr == ""


class TestStreamCapture:
    """Test stream capture methods."""

    @pytest.mark.asyncio
    async def test_install_stream_capture(self, maya_client: MayaClient, mocker) -> None:
        """Test install_stream_capture calls _send_receive."""
        mock_send_receive = mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result={"success": True}, error=None),
        )

        await maya_client.install_stream_capture()

        mock_send_receive.assert_called_once_with(maya_client.INSTALL_STREAM_CAPTURE)

    @pytest.mark.asyncio
    async def test_uninstall_stream_capture(self, maya_client: MayaClient, mocker) -> None:
        """Test uninstall_stream_capture calls _send_receive."""
        mock_send_receive = mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result={"success": True}, error=None),
        )

        await maya_client.uninstall_stream_capture()

        mock_send_receive.assert_called_once_with(maya_client.UNINSTALL_STREAM_CAPTURE)


class TestExecuteCode:
    """Test execute_code method."""

    @pytest.mark.asyncio
    async def test_execute_code_none_result_type(self, maya_client: MayaClient, mocker) -> None:
        """Test execute_code with NONE result type."""
        mock_send_receive = mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result=None, error=None),
        )

        result = await maya_client.execute_code("print('hello')", result_type=ResultType.NONE)

        assert result.result is None
        assert result.error is None
        mock_send_receive.assert_called_once_with(
            maya_client.EXECUTE_TEMPLATE,
            {"code": "print('hello')", "result_type": "NONE"},
            raise_on_error=False,
        )

    @pytest.mark.asyncio
    async def test_execute_code_raw_result_type(self, maya_client: MayaClient, mocker) -> None:
        """Test execute_code with RAW result type."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result=42, error=None),
        )

        result = await maya_client.execute_code("21 * 2", result_type=ResultType.RAW)

        assert result.result == 42
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_code_json_result_type_decodes(
        self, maya_client: MayaClient, mocker
    ) -> None:
        """Test execute_code with JSON result type decodes JSON."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(
                result='["item1", "item2"]',
                error=None,
            ),
        )

        result = await maya_client.execute_code("get_list()", result_type=ResultType.JSON)

        assert result.result == ["item1", "item2"]
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_code_json_invalid_keeps_string(
        self, maya_client: MayaClient, mocker
    ) -> None:
        """Test execute_code with JSON result type keeps invalid JSON as string."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result="not valid json", error=None),
        )

        result = await maya_client.execute_code("get_str()", result_type=ResultType.JSON)

        assert result.result == "not valid json"

    @pytest.mark.asyncio
    async def test_execute_code_with_error(self, maya_client: MayaClient, mocker) -> None:
        """Test execute_code returns error in response."""
        error_info = {
            "type": "builtins.NameError",
            "message": "name 'undefined' is not defined",
            "traceback": "Traceback...",
        }
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result=None, error=error_info),
        )

        result = await maya_client.execute_code("undefined")

        assert result.result is None
        assert result.error == error_info


# ============================================================================
# MayaClient-specific Tests
# ============================================================================


class TestMayaClientWriteModule:
    """Test MayaClient write_module method."""

    @pytest.mark.asyncio
    async def test_write_module(self, maya_client: MayaClient, mocker) -> None:
        """Test write_module returns success message."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(
                result={"message": "Module 'mymodule' created"},
                error=None,
            ),
        )

        result = await maya_client.write_module("mymodule", "x = 1")

        assert result == "Module 'mymodule' created"

    @pytest.mark.asyncio
    async def test_write_module_default_message(self, maya_client: MayaClient, mocker) -> None:
        """Test write_module returns default message on empty response."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result=None, error=None),
        )

        result = await maya_client.write_module("mymodule", "x = 1")

        assert result == "Module 'mymodule' created"


class TestMayaClientPing:
    """Test MayaClient ping method."""

    @pytest.mark.asyncio
    async def test_ping_success(self, maya_client: MayaClient, mocker) -> None:
        """Test ping returns True when Maya responds correctly."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result="2", error=None),
        )

        result = await maya_client.ping()

        assert result is True

    @pytest.mark.asyncio
    async def test_ping_wrong_response(self, maya_client: MayaClient, mocker) -> None:
        """Test ping returns False when Maya responds incorrectly."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result="wrong", error=None),
        )

        result = await maya_client.ping()

        assert result is False

    @pytest.mark.asyncio
    async def test_ping_exception(self, maya_client: MayaClient, mocker) -> None:
        """Test ping returns False on exception."""
        mocker.patch.object(
            maya_client,
            "_send_receive",
            new_callable=AsyncMock,
            side_effect=MayaExecutionError("Connection lost"),
        )

        result = await maya_client.ping()

        assert result is False


# ============================================================================
# MayaQtClient-specific Tests
# ============================================================================


class TestMayaQtClientWriteModule:
    """Test MayaQtClient write_module method."""

    @pytest.mark.asyncio
    async def test_write_module(self, qt_client: MayaQtClient, mocker) -> None:
        """Test write_module returns success message."""
        mocker.patch.object(
            qt_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(
                result={"message": "Module 'mymodule' created"},
                error=None,
            ),
        )

        result = await qt_client.write_module("mymodule", "x = 1", overwrite=True)

        assert result == "Module 'mymodule' created"


class TestMayaQtClientPing:
    """Test MayaQtClient ping method."""

    @pytest.mark.asyncio
    async def test_ping_success(self, qt_client: MayaQtClient, mocker) -> None:
        """Test ping returns True when server responds with pong."""
        mocker.patch.object(
            qt_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result="pong", error=None),
        )

        result = await qt_client.ping()

        assert result is True

    @pytest.mark.asyncio
    async def test_ping_wrong_response(self, qt_client: MayaQtClient, mocker) -> None:
        """Test ping returns False on wrong response."""
        mocker.patch.object(
            qt_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(result="wrong", error=None),
        )

        result = await qt_client.ping()

        assert result is False

    @pytest.mark.asyncio
    async def test_ping_exception(self, qt_client: MayaQtClient, mocker) -> None:
        """Test ping returns False on exception."""
        mocker.patch.object(
            qt_client,
            "_send_receive",
            new_callable=AsyncMock,
            side_effect=MayaExecutionError("Connection lost"),
        )

        result = await qt_client.ping()

        assert result is False


# ============================================================================
# MayaQtClient session_info and execute_code (ensure they work same as base)
# ============================================================================


class TestMayaQtClientSessionInfo:
    """Test MayaQtClient session_info method."""

    @pytest.mark.asyncio
    async def test_session_info(self, qt_client: MayaQtClient, mocker) -> None:
        """Test session_info returns SessionInfo dataclass."""
        mocker.patch.object(
            qt_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(
                result={
                    "pid": 99999,
                    "user": "qtuser",
                    "maya_version": "2025",
                    "scene_name": "qt_scene.ma",
                    "scene_path": "/qt/path/scene.ma",
                },
                error=None,
            ),
        )

        info = await qt_client.session_info()

        assert isinstance(info, SessionInfo)
        assert info.host == "127.0.0.1"
        assert info.port == 50000
        assert info.pid == 99999
        assert info.user == "qtuser"
        assert info.maya_version == "2025"


class TestMayaQtClientExecuteCode:
    """Test MayaQtClient execute_code method."""

    @pytest.mark.asyncio
    async def test_execute_code_json(self, qt_client: MayaQtClient, mocker) -> None:
        """Test execute_code with JSON result type."""
        mock_send_receive = mocker.patch.object(
            qt_client,
            "_send_receive",
            new_callable=AsyncMock,
            return_value=CommandResponse(
                result='{"key": "value"}',
                error=None,
            ),
        )

        result = await qt_client.execute_code("get_dict()", result_type=ResultType.JSON)

        assert result.result == {"key": "value"}
        mock_send_receive.assert_called_once_with(
            qt_client.EXECUTE_TEMPLATE,
            {"code": "get_dict()", "result_type": "JSON"},
            raise_on_error=False,
        )
