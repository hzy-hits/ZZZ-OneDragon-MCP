from __future__ import annotations

import argparse

from one_dragon.devtools import python_launcher
from one_dragon.launcher.exe_launcher import ExeLauncher
from one_dragon.version import __version__


class ZMcpServerLauncher(ExeLauncher):
    """绝区零 MCP 服务启动器"""

    def __init__(self) -> None:
        ExeLauncher.__init__(self, "绝区零 MCP 服务 启动器", __version__)

    def add_custom_arguments(self, parser: argparse.ArgumentParser) -> None:
        ExeLauncher.add_custom_arguments(self, parser)
        parser.add_argument(
            "--transport",
            type=str,
            default="sse",
            choices=["stdio", "sse"],
        )
        parser.add_argument("--host", type=str, default="0.0.0.0")
        parser.add_argument("--port", type=int, default=8399)

    def build_launch_args(self, args) -> list[str]:
        return [
            "--transport",
            args.transport,
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]

    def _run_server(self, launch_args: list[str]) -> None:
        python_launcher.run_python(
            ["zzz_od", "mcp", "serve.py"],
            no_windows=False,
            args=launch_args,
            piped=True,
        )

    def run_onedragon_mode(self, launch_args: list[str]) -> None:
        self._run_server(launch_args)

    def run_gui_mode(self) -> None:
        self._run_server(self.build_launch_args(self.args))


if __name__ == "__main__":
    launcher = ZMcpServerLauncher()
    launcher.run()
