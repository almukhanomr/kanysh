"""Optional CI browser check of the read-only viewer; no numerical jobs are launched."""

from pathlib import Path

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel="chrome")
    page = browser.new_page(viewport={"width": 1500, "height": 1050}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8765/app/", wait_until="networkidle")
    page.get_by_role("button", name="Open Norne demo", exact=True).click()
    page.frame_locator('iframe[title="Result preview"]').get_by_role("heading", name="scene · r1").wait_for(
        timeout=30000
    )
    assert page.locator("audio").count() == 0
    assert page.get_by_role("button", name="Send", exact=True).count() == 0
    output = Path("docs/ui-viewer.png")
    page.screenshot(path=str(output), full_page=True)
    assert not errors, errors
    print("Read-only viewer/Norne PASS:", output)
    browser.close()
