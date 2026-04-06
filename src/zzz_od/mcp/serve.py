from __future__ import annotations

import argparse

from one_dragon.utils.log_utils import log

from zzz_od.context.zzz_context import ZContext
from zzz_od.mcp.server import create_mcp_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OneDragon MCP server")
    parser.add_argument(
        "--transport",
        type=str,
        default="sse",
        choices=["stdio", "sse"],
        help="MCP transport",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8399)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ctx = ZContext()
    ctx.init()

    controller = getattr(ctx, "controller", None)
    if controller is not None:
        try:
            controller.init_before_context_run()
        except Exception as exc:
            log.warning("mcp server initial window bind failed: %s", exc)

    mcp = create_mcp_server(ctx, host=args.host, port=args.port)
    try:
        if args.transport == "stdio":
            log.info("Starting OneDragon MCP server with stdio transport")
            mcp.run(transport="stdio")
        else:
            log.info("Starting OneDragon MCP server on %s:%s", args.host, args.port)
            mcp.run(transport="sse")
    finally:
        ctx.after_app_shutdown()


if __name__ == "__main__":
    main()
