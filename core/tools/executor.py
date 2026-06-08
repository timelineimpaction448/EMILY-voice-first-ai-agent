"""Shared tool dispatch for local and realtime voice engines."""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
from typing import TYPE_CHECKING, Callable

from core.llm.types import ToolCall

if TYPE_CHECKING:
    from core.engine import EmilyLive

TOOL_TIMEOUT_SEC = 25.0
WEB_SEARCH_TIMEOUT_SEC = 45.0
FIRECRAWL_SCRAPE_TIMEOUT_SEC = 200.0
FIRECRAWL_SEARCH_TIMEOUT_SEC = 90.0
FIRECRAWL_CRAWL_TIMEOUT_SEC = 180.0
MAX_TOOL_RESULT_CHARS = 8000
FIRECRAWL_MAX_RESULT_CHARS = 24000


class ToolExecutor:
    def __init__(self, host: EmilyLive):
        self._host = host

    @property
    def ui(self):
        return self._host.ui

    @property
    def tool_cancel(self) -> threading.Event:
        return self._host._tool_cancel

    def speak(self, text: str) -> None:
        self._host.speak(text)

    def speak_error(self, tool_name: str, error: str) -> None:
        self._host.speak_error(tool_name, error)

    @staticmethod
    def truncate_result(result: str, max_chars: int | None = None) -> str:
        text = str(result)
        limit = max_chars or MAX_TOOL_RESULT_CHARS
        if len(text) <= limit:
            return text
        return text[:limit] + "\n...[truncated]"

    async def run_blocking(self, fn: Callable, *, timeout: float | None = None):
        loop = asyncio.get_event_loop()
        coro = loop.run_in_executor(None, fn)
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout)

    async def execute(self, tc: ToolCall) -> tuple[str, bool]:
        name = tc.name
        args = dict(tc.arguments or {})
        silent = False

        if self.tool_cancel.is_set():
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return "Stopped by user.", silent

        print(f"[EMILY] {name}  {args}")
        self.ui.set_state("THINKING")
        arg_preview = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])
        if len(args) > 3:
            arg_preview += ", …"
        self.ui.append_thinking_line(f"▸ {name}({arg_preview})")

        if name == "save_memory":
            from memory.memory_manager import update_memory
            category = args.get("category", "notes")
            key = args.get("key", "")
            value = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return "ok", True

        loop = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                from actions.open_app import open_app
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."
            elif name == "weather_report":
                from actions.weather_report import weather_action
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."
            elif name == "browser_control":
                from actions.browser_control import browser_control
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "file_controller":
                from actions.file_controller import file_controller
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "send_message":
                from actions.send_message import send_message
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."
            elif name == "reminder":
                from actions.reminder import reminder
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."
            elif name == "youtube_video":
                from actions.youtube_video import youtube_video
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."
            elif name == "screen_process":
                from actions.screen_processor import screen_process
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None, "player": self.ui, "session_memory": None},
                    daemon=True,
                ).start()
                result = "Vision module activated. Stay silent — vision will speak via TTS."
            elif name == "computer_settings":
                from actions.computer_settings import computer_settings
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."
            elif name == "desktop_control":
                from actions.desktop_control import desktop_control
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "code_helper":
                from actions.code_helper import code_helper
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."
            elif name == "dev_agent":
                from actions.dev_agent import dev_agent
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."
            elif name == "agent_task":
                from agent.task_queue import TaskPriority, get_queue
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result = f"Task started (ID: {task_id})."
            elif name == "web_search":
                from actions.web_search import web_search as web_search_action
                r = await self.run_blocking(
                    lambda: web_search_action(parameters=args, player=self.ui),
                    timeout=WEB_SEARCH_TIMEOUT_SEC,
                )
                result = r or "Done."
            elif name == "file_processor":
                from actions.file_processor import file_processor
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak),
                )
                result = r or "Done."
            elif name == "computer_control":
                from actions.computer_control import computer_control
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "game_updater":
                from actions.game_updater import game_updater
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."
            elif name == "flight_finder":
                from actions.flight_finder import flight_finder
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "massive_stock_quote":
                from actions.massive import massive_stock_quote
                r = await self.run_blocking(lambda: massive_stock_quote(parameters=args, player=self.ui), timeout=TOOL_TIMEOUT_SEC)
                result = r or "No quote returned."
            elif name == "massive_options_chain":
                from actions.massive import massive_options_chain
                r = await self.run_blocking(lambda: massive_options_chain(parameters=args, player=self.ui), timeout=TOOL_TIMEOUT_SEC)
                result = r or "No options data returned."
            elif name == "massive_search_endpoints":
                from actions.massive import massive_search_endpoints
                r = await self.run_blocking(lambda: massive_search_endpoints(parameters=args, player=self.ui), timeout=TOOL_TIMEOUT_SEC)
                result = r or "No search results returned."
            elif name == "massive_call_api":
                from actions.massive import massive_call_api
                r = await self.run_blocking(lambda: massive_call_api(parameters=args, player=self.ui), timeout=TOOL_TIMEOUT_SEC)
                result = r or "No API response returned."
            elif name == "massive_query_data":
                from actions.massive import massive_query_data
                r = await self.run_blocking(lambda: massive_query_data(parameters=args, player=self.ui), timeout=TOOL_TIMEOUT_SEC)
                result = r or "No rows returned."
            elif name == "firecrawl_scrape":
                from actions.firecrawl import firecrawl_scrape
                r = await self.run_blocking(
                    lambda: firecrawl_scrape(parameters=args, player=self.ui),
                    timeout=FIRECRAWL_SCRAPE_TIMEOUT_SEC,
                )
                result = r or "No scrape content returned."
            elif name == "firecrawl_search":
                from actions.firecrawl import firecrawl_search
                r = await self.run_blocking(
                    lambda: firecrawl_search(parameters=args, player=self.ui),
                    timeout=FIRECRAWL_SEARCH_TIMEOUT_SEC,
                )
                result = r or "No search results returned."
            elif name == "firecrawl_map":
                from actions.firecrawl import firecrawl_map
                r = await self.run_blocking(lambda: firecrawl_map(parameters=args, player=self.ui), timeout=TOOL_TIMEOUT_SEC)
                result = r or "No URLs returned."
            elif name == "firecrawl_crawl":
                from actions.firecrawl import firecrawl_crawl
                r = await self.run_blocking(
                    lambda: firecrawl_crawl(parameters=args, player=self.ui),
                    timeout=FIRECRAWL_CRAWL_TIMEOUT_SEC,
                )
                result = r or "No crawl results returned."
            elif name == "shutdown_emily":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                def _shutdown():
                    import os
                    time.sleep(1)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()
            else:
                result = f"Unknown tool: {name}"
        except asyncio.TimeoutError:
            result = f"Tool '{name}' timed out."
            self.speak_error(name, result)
        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        max_chars = FIRECRAWL_MAX_RESULT_CHARS if name.startswith("firecrawl_") else None
        return self.truncate_result(result, max_chars=max_chars), silent
