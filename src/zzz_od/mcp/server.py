from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from zzz_od.context.zzz_context import ZContext
from zzz_od.control.server import ZControlService


def create_mcp_server(
    ctx: ZContext,
    host: str = "0.0.0.0",
    port: int = 8399,
) -> FastMCP:
    """Create a native MCP surface over the OneDragon runtime."""
    api = ZControlService(ctx)
    mcp = FastMCP(
        "zzz-onedragon",
        host=host,
        port=port,
        instructions=(
            "OneDragon MCP server for Zenless Zone Zero automation.\n\n"
            "This server exposes stable automation tools directly from the "
            "official OneDragon runtime: app discovery, app dispatch, account "
            "instance switching, game status inspection, logs, screenshots, and "
            "failure diagnostics.\n\n"
            "Use app-level orchestration first:\n"
            "1. list_available_apps()\n"
            "2. get_game_info()\n"
            "3. start_app(app_id)\n"
            "4. monitor via get_app_status() / get_app_execution_log()\n"
            "5. on failure use get_failure_detail()\n"
            "6. switch_instance() when needed"
        ),
    )

    @mcp.tool()
    def health() -> dict[str, Any]:
        """Get basic server and runtime health information."""
        return api.health()

    @mcp.tool()
    def list_available_apps() -> list[dict[str, Any]]:
        """List registered automation apps and their current status."""
        return api.list_apps()

    @mcp.tool()
    def get_daily_summary() -> dict[str, Any]:
        """Get today's completion summary for all apps."""
        return api.get_daily_summary()

    @mcp.tool()
    def get_app_status(app_id: str) -> dict[str, Any]:
        """Get current live and persisted status for one app."""
        return api.get_app_status(app_id)

    @mcp.tool()
    def get_game_info() -> dict[str, Any]:
        """Get current game-window state and basic runtime information."""
        return api.get_game_info()

    @mcp.tool()
    def get_screenshot() -> str | dict[str, Any]:
        """Get the current game screenshot as a base64 PNG string."""
        payload = api.get_screenshot()
        if payload.get("ok", False):
            return payload.get("image_base64")
        return payload

    @mcp.tool()
    def get_current_screen(screen_name_list: list[str] | None = None) -> dict[str, Any]:
        """Recognize the current screen from the latest screenshot."""
        return api.get_current_screen(screen_name_list=screen_name_list)

    @mcp.tool()
    def list_available_actions(
        screen_name_list: list[str] | None = None,
        only_with_goto: bool = True,
    ) -> dict[str, Any]:
        """List visible actions on the current screen, already filtered for the agent."""
        return api.list_available_actions(
            screen_name_list=screen_name_list,
            only_with_goto=only_with_goto,
        )

    @mcp.tool()
    def list_screen_areas(
        screen_name: str,
        only_with_goto: bool = False,
    ) -> dict[str, Any]:
        """List configured areas for one screen, including rects and goto targets."""
        return api.list_screen_areas(
            screen_name=screen_name,
            only_with_goto=only_with_goto,
        )

    @mcp.tool()
    def find_screen_area(screen_name: str, area_name: str) -> dict[str, Any]:
        """Check whether one configured area is currently visible on screen."""
        return api.find_screen_area(screen_name=screen_name, area_name=area_name)

    @mcp.tool()
    def click_screen_area(screen_name: str, area_name: str) -> dict[str, Any]:
        """Find and click one configured area on screen."""
        return api.click_screen_area(screen_name=screen_name, area_name=area_name)

    @mcp.tool()
    def execute_action(action_id: str) -> dict[str, Any]:
        """Execute one visible action returned by list_available_actions()."""
        return api.execute_action(action_id=action_id)

    @mcp.tool()
    def wait_for_screen(
        screen_name_list: list[str],
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """Wait until one of the target screens is recognized."""
        return api.wait_for_screen(
            screen_name_list=screen_name_list,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    @mcp.tool()
    def start_app(
        app_id: str,
        config: dict[str, Any] | None = None,
        instance_idx: int | None = None,
    ) -> dict[str, Any]:
        """Start an automation app asynchronously."""
        return api.start_app(app_id, config=config, instance_idx=instance_idx)

    @mcp.tool()
    def stop_app() -> dict[str, Any]:
        """Stop the currently running app."""
        return api.stop_app()

    @mcp.tool()
    def pause_app() -> dict[str, Any]:
        """Pause the currently running app."""
        return api.pause_app()

    @mcp.tool()
    def resume_app() -> dict[str, Any]:
        """Resume the currently paused app."""
        return api.resume_app()

    @mcp.tool()
    def list_instances() -> list[dict[str, Any]]:
        """List configured account instances."""
        return api.list_instances()

    @mcp.tool()
    def switch_instance(instance_idx: int) -> dict[str, Any]:
        """Switch the active account instance."""
        return api.switch_instance(instance_idx)

    @mcp.tool()
    def get_app_execution_log(app_id: str, last_n: int = 50) -> list[dict[str, Any]]:
        """Get recent log entries related to an app."""
        return api.get_app_execution_log(app_id, last_n=last_n)

    @mcp.tool()
    def get_failure_detail(app_id: str) -> dict[str, Any]:
        """Get detailed failure diagnostics for an app."""
        return api.get_failure_detail(app_id)

    return mcp
