from __future__ import annotations

import base64
import copy
import json
import re
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from one_dragon.utils import os_utils
from one_dragon.utils.log_utils import log

from zzz_od.context.zzz_context import ZContext

_LOG_LINE_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s+\[(?P<file>[^\s]+)\s+(?P<line>\d+)\]\s+"
    r"\[(?P<level>[A-Z]+)\]:\s+(?P<message>.*)$"
)


def _status_label(raw_status: Any) -> str:
    value = getattr(raw_status, "value", raw_status)
    mapping = {
        0: "not_run",
        1: "completed",
        2: "failed",
        3: "running",
        "WAIT": "not_run",
        "SUCCESS": "completed",
        "FAIL": "failed",
        "RUNNING": "running",
        "PAUSE": "paused",
        "STOP": "not_run",
    }
    return mapping.get(value, str(value).lower())


def _run_state_value(run_context: Any) -> str:
    return str(getattr(run_context, "_run_state", "")).split(".")[-1]


def _run_count_today(run_record: Any, status: str) -> int:
    for attr in ("daily_run_times", "run_times"):
        value = getattr(run_record, attr, None)
        if value is None:
            continue
        try:
            return int(value)
        except Exception:
            continue
    return 1 if status != "not_run" else 0


def _extra_run_record_fields(run_record: Any) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for attr in ("daily_run_times", "weekly_run_times", "left_times", "run_times"):
        value = getattr(run_record, attr, None)
        if value is not None:
            extras[attr] = value
    return extras


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _deep_update(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(dict(base[key]), value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _log_file_candidates() -> list[Path]:
    work_dir = Path(os_utils.get_work_dir())
    candidates = [
        work_dir / ".log" / "log.txt",
        Path.cwd() / ".log" / "log.txt",
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _read_log_text_sync() -> tuple[Path | None, str]:
    for path in _log_file_candidates():
        if path.exists():
            try:
                return path, path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return path, ""
    return None, ""


def _parse_log_lines(text: str, tokens: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    normalized_tokens = [token.lower() for token in tokens if token]
    if not normalized_tokens:
        return entries

    for raw_line in text.splitlines():
        lowered = raw_line.lower()
        if not any(token in lowered for token in normalized_tokens):
            continue

        match = _LOG_LINE_RE.match(raw_line)
        if match is None:
            entries.append(
                {
                    "timestamp": None,
                    "level": "INFO",
                    "message": raw_line.strip(),
                    "raw": raw_line,
                }
            )
            continue

        entries.append(
            {
                "timestamp": match.group("timestamp"),
                "level": match.group("level"),
                "message": match.group("message"),
                "file": match.group("file"),
                "line": int(match.group("line")),
                "raw": raw_line,
            }
        )
    return entries


def _extract_failure_hints(
    log_entries: list[dict[str, Any]],
    run_record: Any,
) -> dict[str, Any]:
    last_error = None
    last_warning = None
    last_node = getattr(run_record, "last_node_name", None) or getattr(
        run_record, "current_node_name", None
    )
    last_node_status = getattr(run_record, "last_node_status", None)

    for entry in reversed(log_entries):
        message = str(entry.get("message", ""))
        level = str(entry.get("level", ""))
        if last_error is None and level == "ERROR":
            last_error = message
        if last_warning is None and level == "WARNING":
            last_warning = message
        if last_node is None:
            node_match = re.search(
                r"(?:node|节点)\s*[:=]\s*([^\s,;]+)", message, re.IGNORECASE
            )
            if node_match:
                last_node = node_match.group(1)
        if last_node_status is None:
            status_match = re.search(
                r"(SCREEN_UNKNOWN|RETRIES_EXHAUSTED|FAIL|ERROR|TIMEOUT)",
                message,
                re.IGNORECASE,
            )
            if status_match:
                last_node_status = status_match.group(1).upper()

    return {
        "last_node": last_node,
        "last_node_status": last_node_status,
        "last_error": last_error,
        "last_warning": last_warning,
    }


def _encode_png_base64(image: Any) -> str | None:
    if image is None:
        return None

    try:
        import cv2

        ok, buf = cv2.imencode(".png", image)
        if not ok:
            return None
        return base64.b64encode(buf).decode("utf-8")
    except Exception:
        return None


class ZControlService:
    def __init__(self, ctx: ZContext):
        self.ctx = ctx
        self._lock = threading.RLock()

    @property
    def run_context(self) -> Any:
        return self.ctx.run_context

    def _active_instance_idx(self) -> int:
        value = getattr(self.ctx, "current_instance_idx", None)
        if value is not None:
            return _safe_int(value, 0)
        current = getattr(self.ctx.one_dragon_config, "current_active_instance", None)
        if current is not None and getattr(current, "idx", None) is not None:
            return _safe_int(current.idx, 0)
        return 0

    def _current_group_id(self) -> str:
        group_id = getattr(self.run_context, "current_group_id", None)
        return group_id or "one_dragon"

    def _resolve_instance_idx(self, requested: int | None) -> int:
        if requested is not None:
            return int(requested)
        return self._active_instance_idx()

    def _current_run_status(
        self,
        app_id: str,
        instance_idx: int,
    ) -> dict[str, Any] | None:
        current_app_id = getattr(self.run_context, "current_app_id", None)
        current_instance_idx = getattr(self.run_context, "current_instance_idx", None)
        run_state = _run_state_value(self.run_context)

        if current_app_id != app_id:
            return None
        if current_instance_idx is not None and int(current_instance_idx) != int(
            instance_idx
        ):
            return None
        if run_state not in {"RUNNING", "PAUSE"}:
            return None

        return {
            "status": _status_label(run_state),
            "run_state": run_state,
            "is_active": run_state == "RUNNING",
            "is_paused": run_state == "PAUSE",
            "instance_idx": (
                int(current_instance_idx)
                if current_instance_idx is not None
                else int(instance_idx)
            ),
            "group_id": getattr(self.run_context, "current_group_id", None),
        }

    def _app_status_payload(
        self, app_id: str, instance_idx: int, run_record: Any
    ) -> dict[str, Any]:
        persisted_status = _status_label(
            getattr(
                run_record, "run_status_under_now", getattr(run_record, "run_status", 0)
            )
        )
        live_status = self._current_run_status(app_id, instance_idx)

        payload = {
            "status": live_status["status"]
            if live_status is not None
            else persisted_status,
            "last_persisted_status": persisted_status,
            "last_run_time": getattr(run_record, "run_time", "-"),
            "run_count_today": _run_count_today(run_record, persisted_status),
            "is_done": False
            if live_status is not None
            else bool(getattr(run_record, "is_done", False)),
            "is_active": bool(live_status and live_status["is_active"]),
            "is_paused": bool(live_status and live_status["is_paused"]),
            "instance_idx": live_status["instance_idx"]
            if live_status is not None
            else int(instance_idx),
            "group_id": live_status["group_id"]
            if live_status is not None
            else self._current_group_id(),
            "current_run_state": live_status["run_state"]
            if live_status is not None
            else None,
        }
        payload.update(_extra_run_record_fields(run_record))
        return payload

    def _summarize_run_record(self, run_record: Any) -> dict[str, Any]:
        return {
            "status": _status_label(
                getattr(
                    run_record,
                    "run_status_under_now",
                    getattr(run_record, "run_status", None),
                )
            ),
            "run_status": getattr(run_record, "run_status", None),
            "run_status_under_now": getattr(run_record, "run_status_under_now", None),
            "run_time": getattr(run_record, "run_time", None),
            "run_time_float": getattr(run_record, "run_time_float", None),
            "is_done": bool(getattr(run_record, "is_done", False)),
            "dt": getattr(run_record, "dt", None),
        }

    def _app_log_tokens(self, app_id: str) -> list[str]:
        tokens = [app_id]
        try:
            app_name = self.run_context.get_application_name(app_id)
        except Exception:
            app_name = None
        if app_name:
            tokens.append(str(app_name))
        return list(dict.fromkeys(token for token in tokens if token))

    def _ensure_ready_for_application(
        self, timeout: float = 5.0
    ) -> tuple[bool, str | None]:
        if getattr(self.ctx, "ready_for_application", False):
            return True, None

        init_for_application = getattr(self.ctx, "init_for_application", None)
        if init_for_application is None:
            return False, "framework not ready for application dispatch"

        deadline = time.time() + timeout
        last_error: str | None = None
        while time.time() < deadline:
            try:
                init_for_application()
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if getattr(self.ctx, "ready_for_application", False):
                return True, None

            time.sleep(0.2)

        reason = "framework not ready for application dispatch"
        if last_error is not None:
            reason = f"{reason}: {last_error}"
        return False, reason

    def _ensure_foreground_window_access(self) -> tuple[bool, str | None]:
        controller = getattr(self.ctx, "controller", None)
        if controller is None:
            return True, None
        if getattr(controller, "background_mode", False):
            return True, None
        if not getattr(controller, "is_game_window_ready", False):
            return True, None

        game_win = getattr(controller, "game_win", None)
        active = getattr(game_win, "active", None)
        if active is None:
            return True, None

        try:
            is_active = active()
        except Exception as exc:
            return False, f"failed to activate game window: {type(exc).__name__}: {exc}"

        if is_active:
            return True, None

        return (
            False,
            "game window exists but could not be activated; ensure the game and control "
            "server are running at the same privilege level",
        )

    def health(self) -> dict[str, Any]:
        controller = getattr(self.ctx, "controller", None)
        return {
            "ok": True,
            "ready_for_application": bool(
                getattr(self.ctx, "ready_for_application", False)
            ),
            "run_state": _run_state_value(self.run_context),
            "current_app_id": getattr(self.run_context, "current_app_id", None),
            "current_instance_idx": getattr(
                self.run_context, "current_instance_idx", None
            ),
            "game_window_ready": bool(
                getattr(controller, "is_game_window_ready", False)
            ),
        }

    def list_apps(self) -> list[dict[str, Any]]:
        instance_idx = self._active_instance_idx()
        default_group_apps = set(
            getattr(self.run_context, "default_group_apps", []) or []
        )
        apps: list[dict[str, Any]] = []

        for app_id, factory in sorted(
            getattr(self.run_context, "_application_factory_map", {}).items(),
            key=lambda item: item[0],
        ):
            try:
                run_record = self.run_context.get_run_record(app_id, instance_idx)
                payload = self._app_status_payload(app_id, instance_idx, run_record)
                apps.append(
                    {
                        "app_id": app_id,
                        "name": getattr(factory, "app_name", app_id),
                        "description": getattr(factory, "app_name", app_id),
                        "is_done_today": bool(getattr(run_record, "is_done", False)),
                        "status": payload["status"],
                        "last_run_time": payload["last_run_time"],
                        "run_count_today": payload["run_count_today"],
                        "need_notify": bool(getattr(factory, "need_notify", False)),
                        "default_group": bool(
                            getattr(factory, "default_group", False)
                            or app_id in default_group_apps
                        ),
                        "is_active": payload["is_active"],
                        "is_paused": payload["is_paused"],
                    }
                )
            except Exception as exc:
                apps.append(
                    {
                        "app_id": app_id,
                        "name": getattr(factory, "app_name", app_id),
                        "description": getattr(factory, "app_name", app_id),
                        "is_done_today": False,
                        "status": "not_run",
                        "last_run_time": "-",
                        "run_count_today": 0,
                        "need_notify": bool(getattr(factory, "need_notify", False)),
                        "default_group": bool(
                            getattr(factory, "default_group", False)
                            or app_id in default_group_apps
                        ),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        return apps

    def get_daily_summary(self) -> dict[str, Any]:
        apps = self.list_apps()
        completed_count = sum(1 for item in apps if item.get("status") == "completed")
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "apps": apps,
            "completed_count": completed_count,
            "total_count": len(apps),
        }

    def get_app_status(self, app_id: str) -> dict[str, Any]:
        if not self.run_context.is_app_registered(app_id):
            return {"ok": False, "error": "app not registered", "app_id": app_id}

        instance_idx = self._active_instance_idx()
        run_record = self.run_context.get_run_record(app_id, instance_idx)
        payload = self._app_status_payload(app_id, instance_idx, run_record)
        result = {
            "app_id": app_id,
            "name": self.run_context.get_application_name(app_id),
        }
        result.update(payload)
        return result

    def get_game_info(self) -> dict[str, Any]:
        controller = getattr(self.ctx, "controller", None)
        game_window_ready = bool(getattr(controller, "is_game_window_ready", False))
        return {
            "stamina": {"current": None, "max": None},
            "server_time": datetime.now().isoformat(timespec="seconds"),
            "game_window_ready": game_window_ready,
            "current_instance_idx": self._active_instance_idx(),
            "current_app_id": getattr(self.run_context, "current_app_id", None),
            "errors": None,
        }

    def get_screenshot(self) -> dict[str, Any]:
        controller = getattr(self.ctx, "controller", None)
        if controller is None:
            return {"ok": False, "error": "controller unavailable"}
        try:
            _, image = controller.screenshot()
        except Exception as exc:
            return {
                "ok": False,
                "error": f"failed to capture screenshot: {type(exc).__name__}: {exc}",
            }

        if image is None:
            return {"ok": False, "error": "screenshot unavailable"}

        return {
            "ok": True,
            "image_base64": _encode_png_base64(image),
        }

    def start_app(
        self,
        app_id: str,
        config: dict[str, Any] | None = None,
        instance_idx: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if _run_state_value(self.run_context) != "STOP":
                return {"started": False, "reason": "another app is running"}

            ready, ready_error = self._ensure_ready_for_application()
            if not ready:
                return {
                    "started": False,
                    "reason": ready_error
                    or "framework not ready for application dispatch",
                }

            if not self.run_context.is_app_registered(app_id):
                return {"started": False, "reason": f"app {app_id} is not registered"}

            resolved_instance_idx = self._resolve_instance_idx(instance_idx)
            if resolved_instance_idx != self._active_instance_idx():
                self.ctx.switch_instance(resolved_instance_idx)
                init_for_application = getattr(self.ctx, "init_for_application", None)
                if init_for_application is not None:
                    init_for_application()

            foreground_ready, foreground_error = self._ensure_foreground_window_access()
            if not foreground_ready:
                return {"started": False, "reason": foreground_error}

            group_id = self._current_group_id()

            if config:
                try:
                    app_config = self.run_context.get_config(
                        app_id,
                        resolved_instance_idx,
                        group_id,
                    )
                    if hasattr(app_config, "data") and isinstance(
                        app_config.data, dict
                    ):
                        _deep_update(app_config.data, config)
                        app_config.save()
                    else:
                        return {
                            "started": False,
                            "reason": "app config object is not editable",
                        }
                except Exception as exc:
                    return {
                        "started": False,
                        "reason": f"failed to apply config: {type(exc).__name__}: {exc}",
                    }

            started = self.run_context.run_application_async(
                app_id,
                resolved_instance_idx,
                group_id,
            )
            if not started:
                return {"started": False, "reason": "failed to schedule app run"}

            return {
                "started": True,
                "app_id": app_id,
                "instance_idx": resolved_instance_idx,
                "group_id": group_id,
            }

    def stop_app(self) -> dict[str, Any]:
        with self._lock:
            state = _run_state_value(self.run_context)
            if state == "STOP":
                return {"stopped": False, "reason": "no app running"}
            self.run_context.stop_running()
            return {"stopped": True}

    def pause_app(self) -> dict[str, Any]:
        with self._lock:
            if _run_state_value(self.run_context) != "RUNNING":
                return {"paused": False, "reason": "app is not running"}
            self.run_context.switch_context_pause_and_run()
            return {"paused": True}

    def resume_app(self) -> dict[str, Any]:
        with self._lock:
            if _run_state_value(self.run_context) != "PAUSE":
                return {"resumed": False, "reason": "app is not paused"}
            self.run_context.switch_context_pause_and_run()
            return {"resumed": True}

    def list_instances(self) -> list[dict[str, Any]]:
        active_idx = getattr(
            self.ctx.one_dragon_config.current_active_instance, "idx", None
        )
        instances: list[dict[str, Any]] = []
        for instance in getattr(self.ctx.one_dragon_config, "instance_list", []):
            instances.append(
                {
                    "idx": getattr(instance, "idx", None),
                    "name": getattr(instance, "name", ""),
                    "active": bool(getattr(instance, "idx", None) == active_idx),
                }
            )
        return sorted(
            instances,
            key=lambda item: item["idx"] if item["idx"] is not None else -1,
        )

    def switch_instance(self, instance_idx: int) -> dict[str, Any]:
        with self._lock:
            self.ctx.switch_instance(instance_idx)
            init_for_application = getattr(self.ctx, "init_for_application", None)
            init_error = None
            if init_for_application is not None:
                try:
                    init_for_application()
                except Exception as exc:
                    init_error = f"{type(exc).__name__}: {exc}"

            payload = {
                "switched": True,
                "instance_idx": instance_idx,
                "ready_for_application": getattr(
                    self.ctx,
                    "ready_for_application",
                    None,
                ),
            }
            if init_error is not None:
                payload["warning"] = f"post-switch init failed: {init_error}"
            return payload

    def get_app_execution_log(
        self, app_id: str, last_n: int = 50
    ) -> list[dict[str, Any]]:
        _, log_text = _read_log_text_sync()
        entries = _parse_log_lines(log_text, self._app_log_tokens(app_id))
        if last_n > 0:
            entries = entries[-last_n:]
        return entries

    def get_failure_detail(self, app_id: str) -> dict[str, Any]:
        if not self.run_context.is_app_registered(app_id):
            return {
                "found": False,
                "app_id": app_id,
                "status": "error",
                "reason": f"app not registered: {app_id}",
            }

        instance_idx = self._active_instance_idx()
        run_record = self.run_context.get_run_record(app_id, instance_idx)
        if hasattr(run_record, "check_and_update_status"):
            run_record.check_and_update_status()

        log_path, log_text = _read_log_text_sync()
        log_entries = _parse_log_lines(log_text, self._app_log_tokens(app_id))
        hints = _extract_failure_hints(log_entries, run_record)
        screenshot = None
        controller = getattr(self.ctx, "controller", None)
        if controller is not None and getattr(
            controller, "is_game_window_ready", False
        ):
            try:
                _, screenshot = controller.screenshot()
            except Exception:
                screenshot = None

        live_status = self._current_run_status(app_id, instance_idx)
        persisted_status = _status_label(getattr(run_record, "run_status", None))
        run_time_float = getattr(run_record, "run_time_float", None)
        duration_seconds = None
        if run_time_float:
            duration_seconds = max(
                0.0,
                float(datetime.now().timestamp() - float(run_time_float)),
            )

        failure_time = getattr(run_record, "run_time", None)
        result = {
            "found": True,
            "app_id": app_id,
            "app_name": self.run_context.get_application_name(app_id),
            "status": live_status["status"]
            if live_status is not None
            else persisted_status,
            "current_run_state": live_status["run_state"]
            if live_status is not None
            else None,
            "is_active": bool(live_status and live_status["is_active"]),
            "is_paused": bool(live_status and live_status["is_paused"]),
            "instance_idx": (
                live_status["instance_idx"]
                if live_status is not None
                else int(instance_idx)
            ),
            "group_id": (
                live_status["group_id"]
                if live_status is not None
                else self._current_group_id()
            ),
            "last_persisted_status": persisted_status,
            "run_record": self._summarize_run_record(run_record),
            "last_node": hints["last_node"],
            "last_node_status": hints["last_node_status"],
            "screenshot_base64": _encode_png_base64(screenshot),
            "retry_count": getattr(run_record, "retry_count", None),
            "max_retries": getattr(run_record, "max_retries", None),
            "error_log": "\n".join(entry["raw"] for entry in log_entries[-20:]),
            "log_path": str(log_path) if log_path is not None else None,
            "duration_seconds": duration_seconds,
            "failure_time": None if live_status is not None else failure_time,
            "last_failure_time": failure_time if live_status is not None else None,
        }
        if live_status is not None:
            result["note"] = (
                "app is still running; persisted failure fields refer to the "
                "previous completed run"
            )
        if hints["last_error"] is not None and live_status is None:
            result["last_error"] = hints["last_error"]
        elif hints["last_error"] is not None:
            result["last_persisted_error"] = hints["last_error"]
        if hints["last_warning"] is not None and live_status is None:
            result["last_warning"] = hints["last_warning"]
        elif hints["last_warning"] is not None:
            result["last_persisted_warning"] = hints["last_warning"]
        return result


class _ControlRequestHandler(BaseHTTPRequestHandler):
    api: ZControlService

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("control-server %s - %s", self.address_string(), fmt % args)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query)

            if parts == ["health"]:
                self._send_json(self.api.health())
                return
            if parts == ["apps"]:
                self._send_json(self.api.list_apps())
                return
            if parts == ["summary", "daily"]:
                self._send_json(self.api.get_daily_summary())
                return
            if parts == ["game-info"]:
                self._send_json(self.api.get_game_info())
                return
            if parts == ["screenshot"]:
                self._send_json(self.api.get_screenshot())
                return
            if parts == ["instances"]:
                self._send_json(self.api.list_instances())
                return
            if len(parts) == 3 and parts[0] == "apps" and parts[2] == "status":
                self._send_json(self.api.get_app_status(unquote(parts[1])))
                return
            if len(parts) == 3 and parts[0] == "apps" and parts[2] == "execution-log":
                last_n = _safe_int(query.get("last_n", ["50"])[0], 50)
                self._send_json(
                    self.api.get_app_execution_log(unquote(parts[1]), last_n=last_n)
                )
                return
            if len(parts) == 3 and parts[0] == "apps" and parts[2] == "failure-detail":
                self._send_json(self.api.get_failure_detail(unquote(parts[1])))
                return

            self._send_json(
                {"error": "not found", "path": parsed.path},
                status=HTTPStatus.NOT_FOUND,
            )
        except Exception as exc:
            self._send_json(
                {"error": f"{type(exc).__name__}: {exc}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            payload = self._read_json_body()

            if len(parts) == 3 and parts[0] == "apps" and parts[2] == "start":
                self._send_json(
                    self.api.start_app(
                        unquote(parts[1]),
                        config=payload.get("config"),
                        instance_idx=payload.get("instance_idx"),
                    )
                )
                return
            if parts == ["apps", "current", "stop"]:
                self._send_json(self.api.stop_app())
                return
            if parts == ["apps", "current", "pause"]:
                self._send_json(self.api.pause_app())
                return
            if parts == ["apps", "current", "resume"]:
                self._send_json(self.api.resume_app())
                return
            if parts == ["instances", "switch"]:
                self._send_json(
                    self.api.switch_instance(_safe_int(payload.get("instance_idx"), 0))
                )
                return

            self._send_json(
                {"error": "not found", "path": parsed.path},
                status=HTTPStatus.NOT_FOUND,
            )
        except Exception as exc:
            self._send_json(
                {"error": f"{type(exc).__name__}: {exc}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )


def create_control_server(
    ctx: ZContext,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> ThreadingHTTPServer:
    service = ZControlService(ctx)

    class ControlRequestHandler(_ControlRequestHandler):
        api = service

    server = ThreadingHTTPServer((host, port), ControlRequestHandler)
    server.daemon_threads = True
    return server
