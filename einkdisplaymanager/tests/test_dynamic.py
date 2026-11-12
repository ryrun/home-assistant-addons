import base64
import io
import time

import pytest
from dynamic import DEFAULT_SOURCE, definition, recipe, worker
from media import validate_variant
from PIL import Image
from server import Manager
from test_http import path, upload


async def create(
    admin,
    script='screen.text("Hello",{x:40,y:40,fontSize:32});',
    profile="inkplate_6",
    **settings,
):
    response = await admin.post(
        "/api/dynamic", json={"name": "Sensor canvas", "script": script, **settings}
    )
    assert response.status == 201, await response.text()
    item = await response.json()
    response = await admin.post(
        "/api/dynamic/" + item["id"] + "/targets",
        json={"name": "Display target", "recipe": {"profile": profile}},
    )
    assert response.status == 201, await response.text()
    return item, await response.json()


async def finish(manager, identifier):
    await manager.dynamic.render(identifier)
    return manager.dynamic.status(identifier)


async def test_os_isolation_blocks_native_capabilities():
    result = await worker({"mode": "probe"})
    assert result["isolation"] in ("linux-seccomp", "macos-seatbelt")


@pytest.mark.parametrize(
    "script",
    [
        "while(true){}",
        "function f(){f()}f();",
        'let x=[];while(true)x.push(new Array(100000).fill("x"));',
        'screen.text("x",{x:NaN});',
        "screen.rectangle({width:100000000});",
        'screen.text("x",{__host:"forbidden"});',
        'for(let i=0;i<1001;i++)screen.text("x");',
    ],
)
async def test_untrusted_source_is_bounded_and_validated(script):
    with pytest.raises(ValueError):
        await worker(
            {
                "mode": "commands",
                "source": script,
                "input": {
                    "width": 800,
                    "height": 600,
                    "states": {},
                    "now": {},
                    "palette": {},
                },
            },
            timeout=6,
        )


async def test_javascript_has_only_drawing_snapshot_and_clock_interfaces():
    script = """
    for(const key of ["std","os","fetch","require","process","__import__"]){
      if(typeof globalThis[key]!=="undefined")throw Error("Unexpected host facility");
    }
    const names=["sensor.one","sensor.two"];
    for(let i=0;i<names.length;i++)screen.text(ha.number(names[i],-1),{x:20,y:i*30});
    if(now.hour<12)screen.circle({x:screen.width/2,y:screen.height/2,radius:20,fill:palette.red});
    """
    result = await worker(
        {
            "mode": "commands",
            "source": script,
            "input": {
                "width": 800,
                "height": 480,
                "now": {"hour": 10},
                "palette": {"red": "palette:red"},
                "states": {"sensor.one": {"state": "23.5", "attributes": {}}},
            },
        }
    )
    assert [c.get("text") for c in result["commands"][:2]] == ["23.5", "-1"]
    assert result["commands"][2]["x"] == 400


@pytest.mark.parametrize(
    "profile,orientation",
    [
        ("openpaper_l", "portrait"),
        ("openpaper_7", "portrait"),
        ("inkplate_6", "landscape"),
    ],
)
async def test_target_output_native_geometry_and_no_persistent_render_blobs(
    system, profile, orientation
):
    manager, admin, _frames = system
    item, target = await create(admin, profile=profile)
    if orientation != target["recipe"]["orientation"]:
        response = await admin.put(
            f"/api/dynamic/{item['id']}/targets/{target['id']}",
            json={
                "name": target["name"],
                "modified": target["modified"],
                "recipe": {**target["recipe"], "orientation": orientation},
            },
        )
        assert response.status == 200
        target = await response.json()
    files = list(manager.store.files.iterdir())
    await finish(manager, item["id"])
    cached = manager.dynamic.output(target["id"])
    validate_variant(cached["output"], profile)
    with Image.open(io.BytesIO(cached["source"])) as image:
        expected = (
            (480, 800)
            if profile == "openpaper_7"
            else (800, 600)
            if profile == "inkplate_6"
            else (1200, 1600)
        )
        assert image.size == expected
    assert list(manager.store.files.iterdir()) == files
    stored = manager.store.get("variant", target["id"])
    assert "file" not in stored and "output" not in stored and stored["bytes"] == 0
    # A repeated background render does not save metadata, histories, or hashes.
    before = manager.store.db.total_changes
    first_hash = cached["hash"]
    await finish(manager, item["id"])
    assert manager.dynamic.output(target["id"])["hash"] == first_hash
    assert manager.store.db.total_changes == before


async def test_missing_images_and_fonts_warn_and_render_continues(system):
    manager, admin, _frames = system
    item, target = await create(
        admin,
        script="""
      screen.image("missing-image",{x:0,y:0,width:100,height:100});
      screen.text("Fallback",{x:20,y:20,font:"missing-font",fontSize:30});
    """,
    )
    status = await finish(manager, item["id"])
    assert len(status["warnings"]) == 2
    assert any("default font" in w for w in status["warnings"])
    validate_variant(manager.dynamic.output(target["id"])["output"], "inkplate_6")


async def test_last_good_retained_on_script_error_and_restart_is_not_ready(
    system, tmp_path
):
    manager, admin, _frames = system
    item, target = await create(admin)
    await finish(manager, item["id"])
    cached = manager.dynamic.output(target["id"])
    response = await admin.put(
        "/api/dynamic/" + item["id"],
        json={
            "modified": item["modified"],
            "script": 'throw new Error("Fix this script");',
        },
    )
    assert response.status == 200
    with pytest.raises(ValueError, match="Fix this script"):
        await finish(manager, item["id"])
    assert manager.dynamic.output(target["id"])["hash"] == cached["hash"]
    assert manager.dynamic.status(item["id"])["last_success"] == cached["rendered_at"]
    # Metadata survives, generated bytes deliberately do not.
    restored = Manager(manager.store.root, dev=True)
    assert restored.store.get("variant", target["id"])["id"] == target["id"]
    assert not restored.dynamic.cache
    restored.store.close()


async def test_dynamic_queue_503_retry_hash_based_304_and_original_rejection(system):
    manager, admin, frames = system
    item, target = await create(admin)
    manager.dynamic.due[item["id"]] = time.monotonic() + 1000
    response = await admin.post(
        "/api/devices", json={"name": "Dynamic frame", "profile": "inkplate_6"}
    )
    device = await response.json()
    response = await admin.put(
        "/api/devices/" + device["id"],
        json={"entries": [{"asset_id": item["id"], "mode": "original"}]},
    )
    assert response.status == 400
    response = await admin.put(
        "/api/devices/" + device["id"],
        json={
            "interval": 60,
            "entries": [
                {"asset_id": item["id"], "mode": "variant", "variant_id": target["id"]}
            ],
        },
    )
    assert response.status == 200
    image_url = path(device["urls"]["image"])
    response = await frames.get(image_url)
    assert response.status == 503 and response.headers["Retry-After"] == "60"
    saved = manager.store.get("device", device["id"])
    assert saved["state"]["pending"] and saved["state"]["last_served_at"] is None
    assert not manager.diagnostics.running(device["id"])
    await finish(manager, item["id"])
    response = await frames.get(image_url)
    validate_variant(await response.read(), "inkplate_6")
    etag = response.headers["ETag"]
    assert (await frames.get(image_url, headers={"If-None-Match": etag})).status == 304
    # A changed render is available at the same URL, without consuming a queue step.
    response = await admin.put(
        "/api/dynamic/" + item["id"],
        json={"modified": item["modified"], "script": 'screen.clear("#000000");'},
    )
    assert response.status == 200
    await finish(manager, item["id"])
    response = await frames.get(image_url, headers={"If-None-Match": etag})
    assert response.status == 200 and response.headers["ETag"] != etag
    assert manager.store.get("device", device["id"])["state"]["cycle"] == 1


async def test_dynamic_snapshot_failure_keeps_output_and_inputs_are_allowlisted(
    system, monkeypatch
):
    manager, admin, _frames = system
    item, target = await create(admin)
    await finish(manager, item["id"])
    cached = manager.dynamic.output(target["id"])
    await admin.put(
        "/api/dynamic/" + item["id"],
        json={
            "modified": item["modified"],
            "script": 'screen.text(ha.state("sensor.kitchen"),{x:20,y:20});',
        },
    )
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with pytest.raises(ValueError, match="Home Assistant API is unavailable"):
        await finish(manager, item["id"])
    assert manager.dynamic.output(target["id"])["hash"] == cached["hash"]
    assert manager.store.get("asset", item["id"])["entities"] == ["sensor.kitchen"]


async def test_font_storage_cleanup_and_embedded_asset_ids(system):
    manager, admin, _frames = system
    # Pillow ships a real TrueType fallback, so tests need no redistributable fixture.
    from PIL import ImageFont

    font = ImageFont.load_default(size=20)
    data = font.font_bytes
    response = await admin.post(
        "/api/fonts", data=data, headers={"X-File-Name": "Test-font.ttf"}
    )
    assert response.status == 201, await response.text()
    registered = await response.json()
    asset = await upload(admin)
    item, _target = await create(
        admin,
        script=f'screen.image("{asset}",{{x:10,y:10,width:100,height:100}});screen.text("Font",{{x:20,y:200,font:"{registered["id"]}"}});',
    )
    await finish(manager, item["id"])
    assert not manager.dynamic.status(item["id"])["warnings"]
    font_file = manager.store.path(manager.store.get("font", registered["id"])["file"])
    manager.store.cleanup()
    assert font_file.exists()
    assert (await admin.delete("/api/fonts/" + registered["id"])).status == 200
    assert (await admin.delete("/api/media/asset/" + asset)).status == 200
    assert not font_file.exists()
    await finish(manager, item["id"])
    assert len(manager.dynamic.status(item["id"])["warnings"]) == 2


def test_definition_and_recipe_validation():
    assert definition({"name": "Example", "script": DEFAULT_SOURCE})["interval"] == 300
    for change in (
        {"interval": True},
        {"script": ""},
        {"script": "x" * 65537},
        {"timezone": "../UTC"},
        {"entities": ["sensor/x"]},
    ):
        with pytest.raises(ValueError):
            definition({"name": "Example", **change})
    for settings in (
        {"profile": "missing"},
        {"profile": "inkplate_6", "palette": "spectra6"},
        {"profile": "openpaper_l", "invert": True},
    ):
        with pytest.raises(ValueError):
            recipe(settings)


@pytest.mark.parametrize(
    "profile,color,rgb,expected",
    [
        ("openpaper_7", "red", "#ff0000", (255, 0, 0)),
        ("inkplate_6", "gray4", "#929292", (146, 146, 146)),
    ],
)
async def test_explicit_palette_colors_survive_tone_optimization(
    profile, color, rgb, expected
):
    from profiles import PROFILES

    settings = recipe(
        {"profile": profile, "automatic": True, "brightness": 100, "saturation": -100}
    )
    result = await worker(
        {
            "mode": "render",
            "size": [20, 20],
            "profile": PROFILES[profile],
            "recipe": settings,
            "palette": {color: rgb},
            "fonts": {},
            "images": {},
            "commands": [
                {"type": "clear", "color": "#808080"},
                {
                    "type": "rectangle",
                    "x": 2,
                    "y": 2,
                    "width": 10,
                    "height": 10,
                    "fill": "palette:" + color,
                },
            ],
        }
    )
    output = Image.open(io.BytesIO(base64.b64decode(result["output"]))).convert("RGB")
    assert output.getpixel((5, 5)) == expected
