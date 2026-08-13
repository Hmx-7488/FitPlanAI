"""Browser smoke test for the chat Agent tool ledger.

Run through the repository webapp-testing server helper while Vite is active.
All API responses are intercepted, so the test never reads or changes local
user data and does not require a model key.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright


BASE_URL = "http://127.0.0.1:3000/chat"
NOW = "2026-08-13T14:30:00"


def _json(route: Route, payload, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
    )


def _api_route(route: Route) -> None:
    request = route.request
    parsed = urlparse(request.url)
    path = parsed.path
    if path == "/api/chat/conversations" and request.method == "GET":
        _json(route, [{
            "id": 7,
            "user_id": 1,
            "title": "计划问答",
            "status": "active",
            "created_at": NOW,
            "updated_at": NOW,
            "last_message": "",
        }])
        return
    if path == "/api/chat/memories" and request.method == "GET":
        _json(route, [])
        return
    if path == "/api/chat/conversations/7" and request.method == "GET":
        _json(route, {
            "id": 7,
            "user_id": 1,
            "title": "计划问答",
            "status": "active",
            "created_at": NOW,
            "updated_at": NOW,
            "last_message": "",
            "messages": [],
        })
        return
    if path == "/api/chat/conversations/7/messages/stream":
        trace = {
            "call_id": "call-plan",
            "tool_name": "get_latest_plan",
            "label": "当前计划",
            "status": "completed",
            "summary": "已读取计划 #11 的营养信息",
            "source_count": 2,
            "duration_ms": 18.4,
            "error_code": "",
            "included_in_answer": True,
            "sources": [
                {
                    "source_type": "plan",
                    "source_id": "11",
                    "title": "当前计划 #11",
                    "url": "https://example.com/plan",
                },
                {
                    "source_type": "plan",
                    "source_id": "unsafe",
                    "title": "异常链接应被禁用",
                    "url": "javascript:alert(1)",
                },
            ],
        }
        message = {
            "id": 99,
            "role": "assistant",
            "content": "你当前的目标是 **1900 千卡**。",
            "citations": [
                {
                    "chunk_id": "nutrition-1",
                    "title": "蛋白质建议",
                    "category": "nutrition",
                    "source_name": "测试资料",
                    "source_url": "javascript:alert(2)",
                    "evidence_level": "B",
                    "score": 0.9,
                }
            ],
            "context": {"tool_calls": [trace]},
            "status": "completed",
            "created_at": NOW,
        }
        blocks = [
            ("meta", {"tool_call_count": 1}),
            ("tool", trace),
            ("delta", {"content": "你当前的目标是 **1900 千卡**。"}),
            ("citations", message["citations"]),
            ("done", message),
        ]
        body = "".join(
            f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            for event, data in blocks
        )
        route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body=body,
        )
        return
    route.fulfill(status=404, body="not mocked")


def _run_view(browser, width: int, height: int, output: Path) -> None:
    page = browser.new_page(viewport={"width": width, "height": height})
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.add_init_script("localStorage.setItem('userId', '1')")
    page.route("**/api/chat/**", _api_route)
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.get_by_placeholder("输入你的饮食、训练或计划问题").fill(
        "我的热量目标是多少？"
    )
    page.get_by_title("发送").click()
    page.get_by_text("Agent 数据查询").wait_for()
    page.get_by_text("已用于回答").wait_for()
    page.get_by_text("1900 千卡").wait_for()

    page.locator(".agent-sources summary").click()
    source_links = page.locator(".agent-sources a")
    assert source_links.count() == 2
    assert source_links.nth(0).get_attribute("href") == "https://example.com/plan"
    assert source_links.nth(1).get_attribute("href") is None
    page.locator(".citations summary").click()
    assert page.locator(".citations a").get_attribute("href") is None

    overflow = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert not overflow, f"horizontal overflow at {width}px"
    assert not console_errors, f"console errors: {console_errors}"
    page.screenshot(path=str(output), full_page=True)
    page.close()


def main() -> None:
    output_dir = Path(tempfile.mkdtemp(prefix="slimagent-m6-ui-"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        _run_view(browser, 1440, 900, output_dir / "desktop.png")
        _run_view(browser, 390, 844, output_dir / "mobile.png")
        browser.close()
    print(f"chat tool UI verified; screenshots={output_dir}")


if __name__ == "__main__":
    main()
