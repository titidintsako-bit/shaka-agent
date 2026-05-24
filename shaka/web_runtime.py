"""Browser and web verification helpers for Shaka."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .automation import TaskStore


class WebVerifier:
    """Verify websites with a lightweight HTTP check and optional Playwright."""

    def __init__(self, base_dir: str, task_store: TaskStore | None = None):
        self.base_dir = Path(base_dir).expanduser()
        self.artifact_dir = self.base_dir / "web-artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.task_store = task_store or TaskStore(base_dir)

    def verify(self, url: str, use_browser: bool = False) -> dict[str, Any]:
        task = self.task_store.create_task(
            title=f"Verify website {url}",
            kind="web",
            payload={"url": url, "use_browser": use_browser},
            status="running",
        )
        result: dict[str, Any] = {
            "url": url,
            "ok": False,
            "status_code": None,
            "errors": [],
            "screenshot": "",
            "response_time_ms": None,
            "task_steps": [],
        }
        try:
            self._record_result_step(result, "http", "Starting HTTP verification.", {"url": url})
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                    result["status_code"] = response.status
                    result["response_time_ms"] = elapsed_ms
                    result["ok"] = 200 <= response.status < 400
                    self._record_result_step(
                        result,
                        "http",
                        "HTTP verification completed.",
                        {"status_code": response.status, "response_time_ms": elapsed_ms},
                    )
            except urllib.error.HTTPError as exc:
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                result["status_code"] = exc.code
                result["response_time_ms"] = elapsed_ms
                result["errors"].append(f"HTTP request returned {exc.code}: {exc.reason}")
                self._record_result_step(
                    result,
                    "http",
                    "HTTP verification returned an error status.",
                    {"status_code": exc.code, "response_time_ms": elapsed_ms},
                )
            except urllib.error.URLError as exc:
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                result["response_time_ms"] = elapsed_ms
                reason = getattr(exc, "reason", exc)
                result["errors"].append(f"HTTP request failed for {url}: {reason}")
                self._record_result_step(
                    result,
                    "http",
                    "HTTP verification failed before a response was received.",
                    {"response_time_ms": elapsed_ms, "error": str(reason)},
                )

            if use_browser:
                self._record_result_step(result, "browser", "Starting browser verification.", {"url": url})
                browser_result = self._playwright_snapshot(url)
                browser_errors = browser_result.pop("errors", [])
                result.update(browser_result)
                result["errors"].extend(browser_errors)
                if result.get("browser") == "unavailable":
                    self._record_result_step(
                        result,
                        "browser",
                        "Browser verification skipped because Playwright is not installed.",
                        {"browser": "unavailable"},
                    )
                else:
                    self._record_result_step(
                        result,
                        "browser",
                        "Browser verification completed.",
                        {"browser": result.get("browser"), "screenshot": result.get("screenshot", "")},
                    )

            summary = "Website verified." if result["ok"] else "Website verification failed."
            for step in result["task_steps"]:
                self.task_store.add_step(task["id"], step["message"], kind=step["kind"], metadata=step["metadata"])
            self.task_store.add_step(task["id"], summary, kind="web", metadata=result)
            self.task_store.update_task(task["id"], status="completed" if result["ok"] else "failed", summary=summary, payload=result)
            return result | {"task_id": task["id"]}
        except Exception as exc:
            self.task_store.update_task(task["id"], status="failed", error=str(exc), summary="Website verification failed.")
            raise

    def screenshot(self, url: str) -> dict[str, Any]:
        task = self.task_store.create_task(
            title=f"Capture screenshot {url}",
            kind="web",
            payload={"url": url},
            status="running",
        )
        try:
            result = self._playwright_snapshot(url)
            if not result.get("screenshot"):
                raise RuntimeError("Playwright is not installed or screenshot capture failed.")
            self.task_store.update_task(task["id"], status="completed", summary="Screenshot captured.", payload=result)
            return result | {"task_id": task["id"]}
        except Exception as exc:
            self.task_store.update_task(task["id"], status="failed", error=str(exc), summary="Screenshot failed.")
            raise

    def _playwright_snapshot(self, url: str) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception:
            return {
                "browser": "unavailable",
                "errors": ["Browser verification requested, but Playwright is not installed. Install it to capture screenshots."],
                "screenshot": "",
            }

        screenshot_path = self.artifact_dir / f"screenshot_{int(time.time())}.png"
        console_errors: list[str] = []
        started = time.perf_counter()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1366, "height": 768})
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.goto(url, wait_until="networkidle", timeout=15000)
                page.screenshot(path=str(screenshot_path), full_page=True)
                browser.close()
        except Exception as exc:
            return {
                "browser": "playwright",
                "browser_time_ms": round((time.perf_counter() - started) * 1000, 2),
                "console_errors": console_errors,
                "errors": [f"Browser verification failed for {url}: {exc}"],
                "screenshot": "",
            }
        return {
            "browser": "playwright",
            "browser_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "console_errors": console_errors,
            "screenshot": str(screenshot_path),
        }

    @staticmethod
    def _record_result_step(result: dict[str, Any], kind: str, message: str, metadata: dict[str, Any]) -> None:
        result.setdefault("task_steps", []).append({"kind": kind, "message": message, "metadata": metadata})


def write_web_result(path: str | Path, result: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(result, indent=2), encoding="utf-8")
