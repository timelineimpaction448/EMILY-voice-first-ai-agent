"""Generic stdio MCP client for servers defined in config/mcp.json."""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from core.config import get_mcp_servers

_MCP_INIT_TIMEOUT_SEC = 60.0
_clients_lock = threading.Lock()
_clients: dict[str, MCPClientManager] = {}


def _resolve_command(configured: str) -> str:
    found = shutil.which(configured)
    if found:
        return found

    home = Path.home()
    candidates = [
        home / ".local" / "bin" / f"{configured}.exe",
        home / ".local" / "bin" / configured,
        home / "AppData" / "Local" / "bin" / f"{configured}.exe",
        home / "AppData" / "Local" / "bin" / configured,
        home / "AppData" / "Roaming" / "uv" / "tools" / configured,
        home / "AppData" / "Roaming" / "uv" / "tools" / f"{configured}.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path.resolve())

    tools_root = home / "AppData" / "Roaming" / "uv" / "tools"
    if tools_root.is_dir():
        for exe in tools_root.rglob(f"{configured}.exe"):
            return str(exe.resolve())
        for exe in tools_root.rglob(configured):
            if exe.is_file():
                return str(exe.resolve())

    return configured


def _build_server_env(server_cfg: dict) -> dict[str, str]:
    env = {k: str(v) for k, v in os.environ.items()}
    if "env" in server_cfg:
        env.update({k: str(v) for k, v in server_cfg["env"].items()})
    if os.name == "nt":
        env.setdefault("HOME", os.environ.get("USERPROFILE", str(Path.home())))
    return env


def _tool_result_to_text(result: Any) -> str:
    if result is None:
        return ""
    if getattr(result, "isError", False):
        parts = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "Error: " + ("\n".join(parts) if parts else "tool returned isError with no message")

    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else "No text content in tool response."


class MCPClientManager:
    """Persistent MCP client session on a dedicated asyncio thread."""

    def __init__(self, server_name: str) -> None:
        self.server_name = server_name
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stack: AsyncExitStack | None = None
        self._session = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()
        self.initialized = False
        self.startup_error: str | None = None

    def is_configured(self) -> bool:
        cfg = get_mcp_servers().get(self.server_name)
        return isinstance(cfg, dict) and bool(str(cfg.get("command", "")).strip())

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_connect())
        except Exception as e:
            self.startup_error = str(e)
            print(f"[MCP:{self.server_name}] Async connect failed: {e}")
        finally:
            self._ready.set()

    async def _async_connect(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_cfg = get_mcp_servers().get(self.server_name, {})
        if not self.is_configured():
            raise RuntimeError(
                f"mcpServers.{self.server_name} is not configured in config/mcp.json"
            )

        cmd = _resolve_command(str(server_cfg.get("command", "")).strip())
        args = [str(a) for a in (server_cfg.get("args") or [])]
        env = _build_server_env(server_cfg)

        print(f"[MCP:{self.server_name}] Launching: {cmd} {' '.join(args)}".strip())
        params = StdioServerParameters(command=cmd, args=args, env=env)

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(self._session.initialize(), timeout=_MCP_INIT_TIMEOUT_SEC)
        self.initialized = True
        print(f"[MCP:{self.server_name}] Initialized")

    def ensure_started(self, player=None, timeout: float = _MCP_INIT_TIMEOUT_SEC + 10) -> bool:
        if not self.is_configured():
            self.startup_error = (
                f"{self.server_name} MCP is not configured in config/mcp.json"
            )
            return False

        if self.initialized:
            return True

        with self._start_lock:
            if self._thread is None:
                self.startup_error = None
                self._ready.clear()
                if player:
                    player.write_log(
                        f"SYS: [MCP:{self.server_name}] Starting server "
                        f"(first run may take up to {int(_MCP_INIT_TIMEOUT_SEC)}s)…"
                    )
                self._thread = threading.Thread(
                    target=self._thread_main,
                    daemon=True,
                    name=f"MCP-{self.server_name}",
                )
                self._thread.start()

        if not self._ready.wait(timeout=timeout):
            self.startup_error = (
                f"MCP server '{self.server_name}' did not become ready within "
                f"{int(timeout)} seconds."
            )
            if player:
                player.write_log(f"SYS: [MCP:{self.server_name}] {self.startup_error}")
            return False

        if not self.initialized:
            err = self.startup_error or f"MCP server '{self.server_name}' failed to initialize."
            if player:
                player.write_log(f"SYS: [MCP:{self.server_name}] {err}")
            return False

        if player:
            player.write_log(f"SYS: [MCP:{self.server_name}] Connected.")
        return True

    def call_tool(
        self, name: str, arguments: dict, timeout: float = 35.0, player=None
    ) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "error": (
                    f"{self.server_name} MCP is not configured. "
                    f"Add mcpServers.{self.server_name} to config/mcp.json to enable it."
                )
            }

        if not self.ensure_started(player):
            return {"error": self.startup_error or "MCP not available"}

        assert self._loop is not None and self._session is not None

        async def _run():
            return await asyncio.wait_for(
                self._session.call_tool(name, arguments),
                timeout=timeout,
            )

        try:
            future = asyncio.run_coroutine_threadsafe(_run(), self._loop)
            result = future.result(timeout=timeout + 10)
            text = _tool_result_to_text(result)
            if text.startswith("Error:"):
                return {"error": text}
            return {"content": [{"type": "text", "text": text}]}
        except Exception as e:
            return {"error": str(e)}


def get_mcp_client(server_name: str) -> MCPClientManager:
    with _clients_lock:
        if server_name not in _clients:
            _clients[server_name] = MCPClientManager(server_name)
        return _clients[server_name]
