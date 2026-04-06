# OneDragon MCP Server

这个 fork 提供了一个原生 MCP 服务入口，用来把 OneDragon 直接暴露给外部 agent。

## 当前提供的工具

- `list_available_apps`
- `get_daily_summary`
- `get_app_status`
- `get_game_info`
- `get_screenshot`
- `start_app`
- `stop_app`
- `pause_app`
- `resume_app`
- `list_instances`
- `switch_instance`
- `get_app_execution_log`
- `get_failure_detail`

## Windows 使用方式

### 1. 继续使用 Launcher 图形界面

Launcher 图形界面仍然负责：

- 初始化运行环境
- 游戏路径和账号实例配置
- 代码同步
- 自动更新开关
- 分支切换

MCP 服务不是替代 GUI，而是额外提供一个可被 agent 调用的入口。

### 2. 启动 MCP 服务

开发环境下可直接运行：

```powershell
uv run src/zzz_od/mcp/serve.py --transport sse --port 8399
```

Windows 启动器入口：

```powershell
uv run src/zzz_od/win_exe/mcp_server.py --port 8399
```

启动后 MCP 地址默认为：

```text
http://127.0.0.1:8399/sse
```

## 分支建议

- `main`: 跟踪上游官方
- `dev`: 集成 MCP / agent-control 改动
- `stable`: Windows 日常使用推荐分支

推荐做法：

- 开发机可以切 `dev`
- 实际运行游戏的机器建议关掉自动更新，或只跟 `stable`

## Launcher 代码同步说明

Launcher 自动更新使用的是 `config/project.yml` 中配置的仓库地址，以及环境配置里的 `git_branch`。

这个 fork 已将仓库地址改为：

- `git@github.com:hzy-hits/ZZZ-OneDragon-MCP.git`

因此只要 Windows 上同步到这个 fork，并把分支设成 `dev` 或 `stable`，后续自动更新就会跟你们自己的仓库走，不会再回拉官方仓库。
