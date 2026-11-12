"""Audit dashboard layouts with long content and real data at responsive widths.

Use --report to collect screenshots/findings before fixing; default asserts no
page/dialog overflow. Generated files and the temporary server stay outside data.
"""

import asyncio
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from aiohttp.test_utils import TestServer
from PIL import Image, ImageFont
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_smoke import sample_image
from server import Manager


async def main():
    report = "--report" in sys.argv
    artifacts = Path(
        os.environ.get(
            "EINK_ARTIFACTS", str(Path(tempfile.gettempdir()) / "eink-layout-audit")
        )
    )
    artifacts.mkdir(parents=True, exist_ok=True)
    findings, errors = [], []
    views = 0
    with tempfile.TemporaryDirectory(prefix="eink-layout-") as data:
        manager = Manager(data, dev=True)
        admin_app, frame_app = manager.apps()
        async with TestServer(admin_app) as admin, TestServer(frame_app):
            origin = str(admin.make_url("/")).rstrip("/")
            async with async_playwright() as playwright:
                engine = os.environ.get("EINK_BROWSER", "chromium")
                browser = await getattr(playwright, engine).launch()
                page = await browser.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                state = await (await page.request.get(origin + "/api/state")).json()
                headers = {"X-Eink-CSRF": state["csrf"]}

                async def post(path, body):
                    response = await page.request.post(
                        origin + "/api/" + path, data=body, headers=headers
                    )
                    assert response.ok, await response.text()
                    return await response.json()

                assets = []
                second = io.BytesIO()
                Image.open(io.BytesIO(sample_image())).resize((720, 959)).save(
                    second, "JPEG"
                )
                for name in [
                    "A very long mountain image name with spaces and details.jpg",
                    "UnbrokenImageName" * 6 + ".jpg",
                ]:
                    response = await page.request.post(
                        origin + "/api/assets",
                        data=sample_image() if not assets else second.getvalue(),
                        headers={**headers, "X-File-Name": name},
                    )
                    assert response.ok, await response.text()
                    assets.append(await response.json())
                for name in [
                    "SofiaSansExtraCondensed-ExtraLight.ttf",
                    "Roboto-Regular.ttf",
                    "materialdesignicons-webfont.ttf",
                ]:
                    response = await page.request.post(
                        origin + "/api/fonts",
                        data=ImageFont.load_default(size=20).font_bytes,
                        headers={**headers, "X-File-Name": name},
                    )
                    assert response.ok, await response.text()
                dynamic = await post(
                    "dynamic",
                    {
                        "name": "Dynamic dashboard with an exceptionally long descriptive name",
                        "interval": 2592000,
                    },
                )
                target = await post(
                    "dynamic/" + dynamic["id"] + "/targets",
                    {
                        "name": "Saved target with a long descriptive name",
                        "recipe": {"profile": "inkplate_6"},
                    },
                )
                await manager.dynamic.render(dynamic["id"])
                response = await page.request.post(
                    origin + "/api/assets/" + assets[0]["id"] + "/variants",
                    data=manager.dynamic.cache[target["id"]]["output"],
                    headers={
                        **headers,
                        "X-Recipe": json.dumps(
                            {"profile": "inkplate_6", "orientation": "landscape"}
                        ),
                        "X-Variant-Name": "UnbrokenVariantName" * 5,
                    },
                )
                assert response.ok, await response.text()
                static_variant = await response.json()
                devices = []
                for profile in ["openpaper_l", "openpaper_7", "inkplate_6"]:
                    device = await post(
                        "devices",
                        {
                            "name": ("LivingRoomDisplayWithoutSpaces" * 4)[:120],
                            "profile": profile,
                        },
                    )
                    response = await page.request.put(
                        origin + "/api/devices/" + device["id"],
                        data={
                            "entries": [
                                {
                                    "asset_id": assets[0]["id"],
                                    "mode": "variant"
                                    if profile == "inkplate_6"
                                    else "original",
                                    "variant_id": static_variant["id"]
                                    if profile == "inkplate_6"
                                    else None,
                                }
                            ]
                        },
                        headers=headers,
                    )
                    assert response.ok, await response.text()
                    devices.append(await response.json())
                    if profile == "openpaper_l":
                        stored = manager.store.get('device', device['id'])
                        stored['battery'] = {'enabled': True, 'chemistry': 'custom', 'series_cells': 4,
                                             'empty_voltage': 1.2, 'full_voltage': 1.6}
                        manager.store.save('device', stored)
                        now = time.time()
                        for day in range(11):
                            manager.battery_forecast.record(stored, 5800 - day * 40, now - (10 - day) * 86400)
                        assert manager.battery_status(stored)['forecast']

                    manager.diagnostics.event(
                        device["id"],
                        "image_interrupted",
                        "Image transfer interrupted; the selected image will be retried.",
                        error_code="connection_reset",
                        http_status=200,
                        bytes_written=123456,
                        total_bytes=960118,
                    )

                async def audit(label):
                    nonlocal views
                    views += 1
                    await page.wait_for_timeout(70)
                    issues = await page.evaluate("""() => {
                      const dialog=document.querySelector('dialog[open]'),root=dialog||document.documentElement;
                      const bounds=dialog?dialog.getBoundingClientRect():{left:0,right:innerWidth};
                      const visible=el=>el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
                      const found=[];
                      if(!dialog&&document.documentElement.scrollWidth>innerWidth+1)found.push('page overflow '+document.documentElement.scrollWidth+'/'+innerWidth);
                      for(const el of (dialog||document.querySelector('main')).querySelectorAll('h1,h2,h3,.panel,.toolbar,.font-row,.font-controls,.library-tabs,.dialog-head,.dialog-body,.controls,.picker-card,.timing-target,.page-head,.form-grid,nav')){
                        if(!visible(el))continue;
                        const r=el.getBoundingClientRect();
                        if(r.left<bounds.left-2||r.right>bounds.right+2)found.push(el.tagName+'.'+el.className+' outside viewport '+Math.round(r.right));
                        if(el.scrollWidth>el.clientWidth+2&&!['auto','scroll','hidden'].includes(getComputedStyle(el).overflowX))found.push(el.tagName+'.'+el.className+' content overflow '+el.scrollWidth+'/'+el.clientWidth);
                      }
                      const nav=document.querySelector('aside nav');
                      if(!dialog&&nav.getBoundingClientRect().right>innerWidth)found.push('navigation overflow');
                      return [...new Set(found)];
                    }""")
                    if issues:
                        findings.append({"view": label, "issues": issues})
                    (artifacts / "findings.json").write_text(
                        json.dumps({"findings": findings, "errors": errors}, indent=2)
                    )
                    # Retain each view, including both color schemes and all breakpoints.
                    if issues or os.environ.get("EINK_SCREENSHOTS", "all") == "all":
                        await page.screenshot(
                            path=str(artifacts / (label + ".png")), full_page=True
                        )

                for color in ["light", "dark"]:
                    await page.emulate_media(color_scheme=color)
                    for width, height in [
                        (320, 740),
                        (390, 844),
                        (768, 1024),
                        (1024, 768),
                        (1440, 1000),
                    ]:
                        await page.set_viewport_size({"width": width, "height": height})
                        prefix = f"{engine}-{color}-{width}"

                        async def route(fragment):
                            await page.goto(origin + "/#" + fragment)
                            await page.locator("#content h1").wait_for()

                        for fragment in [
                            "library",
                            "library/fonts",
                            "library/dynamic",
                            "devices",
                            "settings",
                        ]:
                            await route(fragment)
                            await audit(prefix + "-" + fragment.replace("/", "-"))
                        await route("library")
                        await page.locator("[data-edit]").first.click()
                        await page.locator("dialog[open]").wait_for()
                        await audit(prefix + "-image-editor")
                        await page.get_by_role("button", name="Close dialog").click()
                        await route("library/dynamic")
                        await page.locator("[data-dynamic]").first.click()
                        await page.locator(".cm-editor").wait_for()
                        await page.locator("dialog details").evaluate_all(
                            "(nodes)=>nodes.forEach(el=>el.open=true)"
                        )
                        await audit(prefix + "-script-editor")
                        await page.get_by_role("button", name="Close dialog").click()
                        await route("devices")
                        await page.locator("#add-device").click()
                        await audit(prefix + "-add-device")
                        await page.get_by_role("button", name="Close dialog").click()
                        for device in devices:
                            await route("devices/" + device["id"])
                            await page.locator("#device-form").wait_for()
                            await page.locator("main details").evaluate_all(
                                "(nodes)=>nodes.forEach(el=>el.open=true)"
                            )
                            await audit(prefix + "-" + device["profile"])
                        await page.locator("#add-images").click()
                        await audit(prefix + "-image-picker")
                        await page.get_by_role("button", name="Close dialog").click()
                await browser.close()
    (artifacts / "findings.json").write_text(
        json.dumps({"findings": findings, "errors": errors}, indent=2)
    )
    print(
        json.dumps(
            {"browser": engine, "views": views, "findings": findings, "errors": errors}
        ),
        flush=True,
    )
    if not report:
        assert not findings, f"Layout issues: {artifacts}/findings.json"
        assert not errors, errors


if __name__ == "__main__":
    asyncio.run(main())
