"""前端冒烟（Playwright）：打开主要页面，断言没有 4xx/5xx 与页面错误。

2026-11-21 审计 P2-7：11-19 那批问题（停止按钮、图标 404、到期文案）
全是截图时才发现的 —— 现有测试只做静态源码检查，没有任何浏览器级验证。

本文件不在默认 `pytest tests/` 里（pyproject 的 testpaths 只含 tests），
需要 playwright 与 chromium：

    pip install playwright && python -m playwright install chromium
    pytest tests_e2e -v

CI 由 .github/workflows/e2e-smoke.yml 运行。
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytest.importorskip("playwright", reason="需要 playwright（见文件头说明）")


def _free_port() -> int:
    """取一个空闲端口，避免与正在运行的实例冲突。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url: str, timeout: float = 60.0) -> None:
    """等到服务可用；超时抛错并带上最后一次失败原因。"""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 — 本机固定地址
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 — 轮询期间任何错误都只是"还没好"
            last = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"服务在 {timeout}s 内未就绪：{last}")


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """用临时 HOME/TRADE_HOME 起一个独立实例，返回 (base_url, token, company_id, customer_id)。"""
    import json
    import urllib.request

    home = tmp_path_factory.mktemp("e2e-home")
    env = {
        **os.environ,
        # 隔离到临时目录：绝不碰用户的 ~/.trade 与桌面
        "HOME": str(home),
        "TRADE_HOME": str(home / ".trade"),
        "HERMES_HOME": str(home / ".hermes"),
        "HERMES_DISABLE_LAZY_INSTALLS": "1",
    }
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(port), "--no-browser", "--no-gateway"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # 边跑边收集服务端输出：启动失败时要把原因带进断言，而不是只报 connection refused
    from collections import deque
    from threading import Thread

    server_log: deque[str] = deque(maxlen=200)

    def _pump():
        assert proc.stdout is not None
        for line in proc.stdout:
            server_log.append(line.rstrip())

    Thread(target=_pump, daemon=True).start()

    base = f"http://127.0.0.1:{port}"
    try:
        try:
            _wait_http(base + "/api/status")
        except RuntimeError as exc:
            tail = "\n".join(list(server_log)[-40:])
            raise RuntimeError(f"{exc}\n--- 服务端输出（末尾 40 行）---\n{tail}") from exc
        # 从页面里取 session token（与真实前端同一方式）
        html = urllib.request.urlopen(base + "/trade", timeout=5).read().decode("utf-8")
        m = re.search(r'let TOKEN = "([^"]+)"', html)
        assert m, "页面里没有 session token"
        token = m.group(1)

        def api(method: str, path: str, body: dict | None = None, cid: int | None = None) -> dict:
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data, method=method)
            req.add_header("X-Hermes-Session-Token", token)
            req.add_header("Content-Type", "application/json")
            if cid is not None:
                req.add_header("X-Company-ID", str(cid))
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode() or "{}")

        company = api("POST", "/api/trade/companies", {"name": "E2E Co", "slug": "e2e-co"})
        cid = company["id"]
        customer = api("POST", "/api/trade/customers", {"name": "E2E Customer"}, cid)
        yield base, token, cid, customer["id"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_main_pages_have_no_4xx_or_page_errors(live_server):
    """首页 → 客户列表 → 客户墙 → 画像 → 验厂：全程无错误响应、无页面异常。"""
    from playwright.sync_api import sync_playwright

    base, token, cid, customer_id = live_server
    console_errors: list[str] = []
    page_errors: list[str] = []
    bad_responses: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        # 进页面之前写状态：跳过新手引导并直接选中测试公司
        context.add_init_script(
            "try { localStorage.setItem('_onboarding_completed', '1');"
            f" sessionStorage.setItem('trade_cid', '{cid}'); }} catch (e) {{}}"
        )
        # 本冒烟只验前端：Hermes 兼容检查在无 Hermes 环境会显示升级面板挡住界面。
        # 桩成 usable，真机/CI 的 Hermes 加载由 hermes-smoke 工作流单独覆盖。
        context.route(
            "**/api/trade/system/hermes-compat",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"usable": true}'
            ),
        )
        # 客户管理/邮箱/文档库在 data-paid 区，试用态会被隐藏。临时实例没有真许可证，
        # 这里把状态桩成已激活，好让冒烟能覆盖这些页面（真机激活行为不变）。
        context.route(
            "**/api/trade/license/status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"status": "active", "days_remaining": 365, "activated": true}',
            ),
        )
        page = context.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        def on_response(resp):
            # 只关心本机 API 与静态资源；favicon 是浏览器自动请求，忽略
            url = resp.url
            if resp.status >= 400 and "favicon" not in url:
                bad_responses.append(f"{resp.status} {url}")

        page.on("response", on_response)

        page.goto(base + "/trade", wait_until="networkidle")
        page.wait_for_selector("#app-rail", timeout=15000)

        # 客户列表
        page.click('[data-view="customers"]')
        page.wait_for_selector(".cust-row", timeout=15000)

        # 客户墙
        page.click(".cust-row")
        page.wait_for_selector("#customer-wall.open", timeout=15000)

        # 画像页（ESC 返回客户墙）
        page.click("#wall-open-profile")
        page.wait_for_selector("#customer-profile.open", timeout=15000)
        page.keyboard.press("Escape")
        # 关闭后元素是 display:none，用 class 判断而不是等"可见"
        page.wait_for_function(
            "!document.getElementById('customer-profile').classList.contains('open')",
            timeout=10000,
        )

        # 验厂计划
        page.click("#wall-visit")
        page.wait_for_selector(".visit-page", timeout=15000)

        browser.close()

    assert not page_errors, "页面脚本异常：\n" + "\n".join(page_errors)
    assert not bad_responses, "出现 4xx/5xx 响应：\n" + "\n".join(bad_responses)
    assert not console_errors, "控制台 error 日志：\n" + "\n".join(console_errors)


def _open_ui(p, base: str, cid: int, *, reduced_motion: str = "no-preference",
             compat_body: str = '{"usable": true}', extra_routes=()):
    """开页面并桩掉 Hermes 兼容检查 / 许可证（与上面的冒烟一致）。"""
    browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion=reduced_motion)
    context.add_init_script(
        "try { localStorage.setItem('_onboarding_completed', '1');"
        f" sessionStorage.setItem('trade_cid', '{cid}'); }} catch (e) {{}}"
    )
    context.route(
        "**/api/trade/system/hermes-compat",
        lambda route: route.fulfill(status=200, content_type="application/json", body=compat_body),
    )
    context.route(
        "**/api/trade/license/status",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"status": "active", "days_remaining": 365, "activated": true}',
        ),
    )
    for pattern, handler in extra_routes:
        context.route(pattern, handler)
    page = context.new_page()
    # load 而不是 networkidle：升级流的 SSE 会一直挂着，networkidle 永远等不到
    page.goto(base + "/trade", wait_until="load")
    return browser, page


def test_chat_task_panel_and_privacy(live_server):
    """W1/W3：聊天等待用统一组件；task 面板来自真实 job 事件；args 不进界面。"""
    import json

    from playwright.sync_api import sync_playwright

    base, _token, cid, _customer = live_server
    chat = "\n\n".join([
        "event: thinking\ndata: " + json.dumps({"message": "正在分析问题..."}),
        "event: tool_start\ndata: " + json.dumps({
            "tool_call_id": "t1", "name": "file_extract",
            "args": {"secret": "SENSITIVE_ARGS"}}),
        "event: tool_complete\ndata: " + json.dumps({
            "tool_call_id": "t1", "name": "osint_job_start",
            "result_preview": "secret-result"}),
        "event: job_attached\ndata: " + json.dumps({"job_id": 99, "target": "acme.com"}),
        "event: response\ndata: " + json.dumps({"text": "**完成**：已启动背调。", "conversation_id": 1}),
        "event: done\ndata: {}",
    ]) + "\n\n"
    job = "\n\n".join([
        "event: job_start\ndata: " + json.dumps({"target": "acme.com", "budget": 30}),
        "event: source_start\ndata: " + json.dumps({"source": "rdap", "label": "RDAP 域名注册"}),
        "event: source_done\ndata: " + json.dumps({"source": "rdap", "status": "hit", "ms": 1200}),
        "event: verdict\ndata: " + json.dumps({"rating": "低风险", "unverified": []}),
    ]) + "\n\n"

    with sync_playwright() as p:
        browser, page = _open_ui(p, base, cid)
        page.route("**/api/trade/chat/stream*", lambda r: r.fulfill(
            status=200, content_type="text/event-stream", body=chat))
        page.route("**/api/trade/osint/jobs/99/events*", lambda r: r.fulfill(
            status=200, content_type="text/event-stream", body=job))
        page.route("**/api/trade/osint/jobs?limit=*", lambda r: r.fulfill(
            status=200, content_type="application/json", body='{"jobs": []}'))

        page.evaluate(f"currentCompanyId = {cid}; navToView('chat','daily','今日简报');")
        # 等聊天历史加载完成：历史渲染会清空 #chat-messages，太早发送会把面板冲掉
        page.wait_for_timeout(1500)
        page.evaluate(
            "const i=document.querySelector('#msg-input'); i.value='查一下 acme.com'; sendMsg();"
        )
        page.wait_for_selector(".wait-task-msg .sw-task", timeout=15000)
        page.wait_for_timeout(800)
        html = page.content()
        assert "SENSITIVE_ARGS" not in html, "工具参数 args 进入了界面"
        assert "secret-result" not in html, "工具结果预览进入了界面"
        assert "RDAP 域名注册" in html, "task 面板没有真实来源节点"
        assert "低风险" in html, "task 面板没有结论标签"
        assert page.get_attribute(".wait-task-msg .sw-task", "data-render") in ("2d", "three")
        browser.close()


def test_reduced_motion_uses_static_frame(live_server):
    """reduced-motion 下只显示静态帧，文字照常更新。"""
    from playwright.sync_api import sync_playwright

    base, _token, cid, _customer = live_server
    with sync_playwright() as p:
        browser, page = _open_ui(p, base, cid, reduced_motion="reduce")
        page.wait_for_function("typeof TradeWait !== 'undefined'", timeout=15000)
        page.evaluate(
            "() => { const h=document.createElement('div'); h.id='t';"
            " h.style.cssText='width:700px'; document.body.appendChild(h);"
            " window.__w = TradeWait.mount(h, {mode:'chat'});"
            " window.__w.push({type:'thinking', message:'正在分析问题...'}); }"
        )
        page.wait_for_timeout(300)
        assert page.evaluate("window.__w.animating") is False
        assert page.evaluate("document.querySelector('#t .sw-chat').classList.contains('is-static')")
        assert "ANALYZING" in page.inner_text("#t .sw-phrase")
        browser.close()


def test_task_panel_recovers_after_history_rerender(live_server):
    """刷新/历史重渲染清空消息区后，运行中的背调面板要能按 seq 重建。"""
    import json

    from playwright.sync_api import sync_playwright

    base, _token, cid, _customer = live_server
    jobs = json.dumps({"jobs": [{
        "id": 77, "company_id": cid, "target": "recover.com", "target_type": "",
        "status": "running", "created_at": "", "updated_at": "",
    }]})
    events = "\n\n".join([
        "id: 1\nevent: job_start\ndata: " + json.dumps({"target": "recover.com", "budget": 30}),
        "id: 2\nevent: source_start\ndata: " + json.dumps({"source": "rdap", "label": "RDAP 域名注册"}),
    ]) + "\n\n"

    with sync_playwright() as p:
        browser, page = _open_ui(p, base, cid)
        page.route("**/api/trade/osint/jobs?limit=*", lambda r: r.fulfill(
            status=200, content_type="application/json", body=jobs))
        page.route("**/api/trade/osint/jobs/77/events*", lambda r: r.fulfill(
            status=200, content_type="text/event-stream", body=events))
        page.evaluate(f"currentCompanyId = {cid}; navToView('chat','daily','今日简报');")
        page.wait_for_selector("#chat-messages", timeout=15000)
        page.wait_for_timeout(1200)   # 等历史渲染完成
        page.evaluate("async () => { await loadOsintJobs(false); }")
        page.wait_for_selector(".wait-task-msg .sw-task", timeout=15000)
        # 模拟聊天历史异步渲染：消息区被清空
        page.evaluate("document.querySelector('#chat-messages').innerHTML = '';")
        page.evaluate("async () => { await loadOsintJobs(true); }")
        page.wait_for_selector(".wait-task-msg .sw-task", timeout=10000)
        assert "RDAP 域名注册" in page.inner_text(".wait-task-msg .sw-log")
        browser.close()


def test_hermes_upgrade_uses_task_panel_and_filters_paths(live_server):
    """W10：Hermes 升级用 task 面板；读数行来自日志且过滤绝对路径/长 token。"""
    import json

    from playwright.sync_api import sync_playwright

    base, _token, cid, _customer = live_server
    compat = json.dumps({
        "usable": False, "fix": "upgrade_hermes", "steps": [],
        "upgrade": {"status": "upgrading", "message": "", "running": True},
    })
    stream = "\n\n".join([
        "data: " + json.dumps({"type": "log", "line": "cloning /Users/someone/.hermes/hermes-agent"}),
        "data: " + json.dumps({"type": "log", "line": "token " + "a" * 40}),
        "data: " + json.dumps({"type": "state", "status": "upgrading",
                               "message": "", "running": True, "cursor": 3}),
    ]) + "\n\n"

    with sync_playwright() as p:
        browser, page = _open_ui(p, base, cid, compat_body=compat, extra_routes=[
            ("**/api/trade/system/hermes-upgrade/stream*", lambda r: r.fulfill(
                status=200, content_type="text/event-stream", body=stream)),
        ])
        page.wait_for_selector("#hermes-upgrade-wait .sw-task", timeout=15000)
        page.wait_for_timeout(1200)
        text = page.inner_text("#hermes-upgrade-wait")
        assert "UPGRADE" in text
        assert "/Users/" not in text, "升级读数是日志原文，路径没有过滤"
        assert "a" * 40 not in text, "升级读数是日志原文，长 token 没有过滤"
        browser.close()
