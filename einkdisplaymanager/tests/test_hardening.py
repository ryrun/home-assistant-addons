"""Resource boundary and immutable delivery-cache regressions."""

import json

import pytest
from test_http import device, path, upload


async def test_metadata_limit_applies_to_length_and_chunked_requests(system):
    manager, admin, _frames = system
    body = json.dumps({"name": "x" * (512 * 1024)}).encode()
    response = await admin.post(
        "/api/devices", data=body, headers={"Content-Type": "application/json"}
    )
    assert response.status == 413

    async def blocks():
        for offset in range(0, len(body), 16384):
            yield body[offset : offset + 16384]

    response = await admin.post(
        "/api/devices", data=blocks(), headers={"Content-Type": "application/json"}
    )
    assert response.status == 413
    assert not manager.store.all("device")
    # Even pathological escaping of a valid 64 KiB script fits the metadata cap.
    source = "/*" + "\x01" * 65532 + "*/"
    response = await admin.post(
        "/api/dynamic",
        data=json.dumps({"name": "Escaped source", "script": source}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status == 201


@pytest.mark.parametrize(
    "body",
    [
        '{"interval":NaN}',
        '{"interval":Infinity}',
        '{"interval":-Infinity}',
        '{"nested":' + "[" * 10000 + "0" + "]" * 10000 + "}",
    ],
)
async def test_nonfinite_and_deep_json_are_rejected_before_validation(system, body):
    _manager, admin, _frames = system
    response = await admin.post(
        "/api/devices", data=body, headers={"Content-Type": "application/json"}
    )
    assert response.status == 400
    assert (await response.json())["error"]


async def test_font_body_has_its_own_limit_before_worker_allocation(system):
    manager, admin, _frames = system
    response = await admin.post(
        "/api/fonts", data=b"\x00\x01\x00\x00" + b"x" * (4 * 1024 * 1024)
    )
    assert response.status == 413
    assert not manager.store.all("font")


async def test_native_delivery_reuses_bytes_but_missing_file_still_retries(
    system, monkeypatch
):
    from pathlib import Path

    manager, admin, frames = system
    asset = await upload(admin)
    d = await device(admin, [asset])
    stored = manager.store.get("asset", asset)
    target = manager.store.path(stored["file"])
    original = Path.read_bytes
    reads = []

    def counted(p):
        if p == target:
            reads.append(p)
        return original(p)

    monkeypatch.setattr(Path, "read_bytes", counted)
    first = await frames.get(path(d["urls"]["image"]))
    data = await first.read()
    second = await frames.get(
        path(d["urls"]["image"]), headers={"If-None-Match": first.headers["ETag"]}
    )
    assert second.status == 304
    assert len(reads) == 1 and data
    target.unlink()
    third = await frames.get(path(d["urls"]["image"]))
    assert third.status == 503  # Warm cache cannot hide lost persistent media.


async def test_delivery_cache_remains_bounded(system, monkeypatch):
    from pathlib import Path

    manager, _admin, _frames = system
    file = manager.store.files / "cache-fixture.original"
    file.write_bytes(b"x")
    original = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda p: b"x" * (5 * 1024 * 1024) if p == file else original(p),
    )
    for index in range(12):
        await manager.delivery(
            {
                "id": str(index),
                "file": file.name,
                "hash": str(index),
                "mime": "image/jpeg",
            }
        )
    assert len(manager.delivery_cache) <= 8
    assert manager.delivery_cache_bytes <= 32 * 1024 * 1024
    assert manager.delivery_cache_bytes == sum(
        len(v[0]) for v in manager.delivery_cache.values()
    )


async def test_deep_remote_sensor_json_fails_as_a_snapshot_error(system, monkeypatch):
    from test_calendar import Response, Session

    manager, _admin, _frames = system
    original = manager.dynamic.session
    manager.dynamic.session = Session(
        {"sensor.test": Response(b"[" * 10000 + b"0" + b"]" * 10000)}
    )
    monkeypatch.setenv("SUPERVISOR_TOKEN", "parent-only-token")
    try:
        with pytest.raises(ValueError, match="Home Assistant is unavailable"):
            await manager.dynamic.snapshot(["sensor.test"])
    finally:
        manager.dynamic.session = original
