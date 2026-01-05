"""Entry point for maya-mcp-server."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from maya_mcp_server.server import (
    initialize_session_manager,
    mcp,
    shutdown_session_manager,
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MCP server for Autodesk Maya",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--scan-interval",
        type=float,
        default=10.0,
        help="Seconds between session scans",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity (-v for INFO, -vv for DEBUG)",
    )

    parser.add_argument(
        "--client-type",
        choices=["native", "qt"],
        default="qt",
        help="Client type: 'native' uses Maya's commandPort, 'qt' uses custom Qt server",
    )

    return parser.parse_args()


def setup_logging(verbosity: int) -> None:
    """Configure logging based on verbosity level."""
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )


async def run_server(args: argparse.Namespace) -> None:
    """Run the MCP server."""
    # Initialize session manager
    await initialize_session_manager(
        scan_interval=args.scan_interval,
        client_type=args.client_type,
    )

    try:
        # Run the MCP server
        await mcp.run_async()
    finally:
        # Cleanup
        await shutdown_session_manager()


def main() -> None:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)

    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
