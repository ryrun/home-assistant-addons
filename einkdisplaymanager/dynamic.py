"""Persistent dynamic recipes with isolated execution and bounded volatile outputs."""

import asyncio
import base64
import contextlib
import json
import os
import re
import signal
import sys
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
import calendar_snapshot
from media import COLORS, GRAY8, digest, validate_variant
from profiles import PROFILES, view_size

ROOT = Path(__file__).parent
OPTIMIZER_VERSION = "epdoptimize@1.4.1"
MAX_CACHE = 128 * 1024 * 1024
MAX_SOURCE = 65536
DEFAULT_SOURCE = """screen.clear(palette.white);
screen.rectangle({x: 20, y: 20, width: screen.width - 40, height: screen.height - 40,
  stroke: palette.black, strokeWidth: 2});
const greeting = now.hour < 12 ? "Good morning" : now.hour < 18 ? "Good afternoon" : "Good evening";
screen.text(greeting, {x: screen.width / 2, y: screen.height / 2,
  font: "default", fontSize: 48, color: palette.black,
  align: "center", verticalAlign: "middle"});
"""
ENTITY = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def valid_name(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value.strip()) <= 120
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Use a name between 1 and 120 characters.")
    return value.strip()


def recipe(data):
    if not isinstance(data, dict):
        raise TypeError("Invalid target recipe.")
    supported = {
        "profile",
        "orientation",
        "palette",
        "dither",
        "matching",
        "automatic",
        "invert",
        "brightness",
        "contrast",
        "saturation",
        "intent",
    }
    if set(data) - supported:
        raise ValueError("Unknown target setting.")
    profile = PROFILES.get(data.get("profile"))
    if not profile:
        raise ValueError("Choose a supported display model.")
    result = {
        "profile": profile["id"],
        "orientation": profile["native_orientation"],
        "palette": "gray8" if profile.get("format") == "png" else "natural",
        "dither": "none",
        "matching": "rgb",
        "automatic": False,
        "invert": False,
        "brightness": 0,
        "contrast": 0,
        "saturation": 0,
        "intent": "natural",
        **data,
    }
    if result["orientation"] not in ("portrait", "landscape"):
        raise ValueError("Choose portrait or landscape.")
    if result["palette"] not in (
        ("gray8", "grayscale")
        if profile.get("format") == "png"
        else ("natural", "spectra6", "aitjcize", "vivid", "grayscale", "openpaper_l_measured")
    ):
        raise ValueError("Choose a palette supported by the target display.")
    if result["palette"] == "openpaper_l_measured" and profile["id"] != "openpaper_l":
        raise ValueError("The measured 13.3-inch palette is for OpenPaper L only.")
    if result["dither"] not in (
        "none",
        "floyd",
        "atkinson",
        "stucki",
        "jarvis",
        "burkes",
        "sierra3",
        "ordered",
        "blueNoise",
    ):
        raise ValueError("Choose a supported dithering method.")
    if result["matching"] not in ("rgb", "lab") or result["intent"] not in (
        "natural",
        "vivid",
    ):
        raise ValueError("Invalid matching or automatic intent.")
    if any(type(result[k]) is not bool for k in ("automatic", "invert")):
        raise ValueError("Optimization switches must be true or false.")
    if result["invert"] and profile.get("format") != "png":
        raise ValueError("Tone inversion is available for Inkplate grayscale only.")
    if any(
        type(result[k]) is not int or not -100 <= result[k] <= 100
        for k in ("brightness", "contrast", "saturation")
    ):
        raise ValueError("Tone adjustments must be whole numbers between -100 and 100.")
    return result


def definition(data, old=None):
    old = old or {}
    if not isinstance(data, dict) or set(data) - {
        "name",
        "script",
        "interval",
        "timezone",
        "entities",
        "calendars",
        "calendar_days",
        "calendar_start_of_day",
        "modified",
        "targets",
    }:
        raise ValueError("Unknown dynamic image setting.")
    result = {**old, **data}
    result["name"] = valid_name(result.get("name"))
    script = result.get("script", DEFAULT_SOURCE)
    if not isinstance(script, str) or not 1 <= len(script.encode()) <= MAX_SOURCE:
        raise ValueError("Script must contain 1–65536 bytes of JavaScript source.")
    result["script"] = script
    interval = result.get("interval", 300)
    if type(interval) is not int or not 10 <= interval <= 2592000:
        raise ValueError("Generation interval must be 10–2592000 whole seconds.")
    result["interval"] = interval
    zone = result.get("timezone", "UTC")
    if not isinstance(zone, str) or len(zone) > 80:
        raise ValueError("Use an IANA time zone.")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Use an IANA time zone such as Europe/Berlin.") from None
    result["timezone"] = zone
    entities = result.get("entities", [])
    if (
        not isinstance(entities, list)
        or len(entities) > 64
        or any(not isinstance(e, str) or not ENTITY.fullmatch(e) for e in entities)
    ):
        raise ValueError("Use at most 64 valid Home Assistant entity IDs.")
    detected = re.findall(
        r"""ha\.(?:state|number|attribute)\s*\(\s*["']([a-z0-9_]+\.[a-z0-9_]+)["']""",
        script,
    )
    result["entities"] = sorted(
        set(entities + [e for e in detected if ENTITY.fullmatch(e)])
    )
    if len(result["entities"]) > 64:
        raise ValueError("At most 64 Home Assistant entities can be read per image.")
    result.update(calendar_snapshot.settings(result))
    return result


async def worker(payload, timeout=40):
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > 20 * 1024 * 1024:
        raise ValueError(
            "Selected image/font resources exceed the 20 MiB render input budget."
        )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-B",
        "-E",
        "-s",
        str(ROOT / "dynamic_worker.py"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={"LANG": "C.UTF-8"},
        cwd="/",
        start_new_session=True,
        limit=20 * 1024 * 1024,
    )
    try:
        # Read a bounded response rather than communicate(), which buffers without
        # a size limit if a compromised child writes unbounded output.
        async def exchange():
            process.stdin.write(encoded)
            await process.stdin.drain()
            process.stdin.close()
            chunks, size = [], 0
            while block := await process.stdout.read(65536):
                size += len(block)
                if size > 20 * 1024 * 1024:
                    raise ValueError("Render output exceeds its RAM budget.")
                chunks.append(block)
            await process.wait()
            result = json.loads(b"".join(chunks))
            if result.get("error"):
                raise ValueError(result["error"])
            if process.returncode:
                raise ValueError("The isolated render process stopped unexpectedly.")
            return result

        return await asyncio.wait_for(exchange(), timeout)
    except TimeoutError:
        raise ValueError(
            "Rendering exceeded its time limit; the worker was stopped."
        ) from None
    except (json.JSONDecodeError, BrokenPipeError, ConnectionResetError):
        raise ValueError(
            "The isolated render process stopped without a valid result."
        ) from None
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


class DynamicImages:
    def __init__(self, manager):
        self.manager, self.store = manager, manager.store
        self.cache, self.statuses, self.jobs, self.due = OrderedDict(), {}, {}, {}
        self.dirty = set()
        self.lock = asyncio.Semaphore(1)
        self.pending = 0
        self.isolation = None
        self.isolation_error = None
        self.task = self.session = None
        self.stopping = False

    async def start(self):
        try:
            self.isolation = (await worker({"mode": "probe"}, timeout=8))["isolation"]
        except (ValueError, OSError):
            self.isolation_error = (
                "Process isolation verification failed. Dynamic execution is disabled."
            )
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8), trust_env=False
        )
        self.task = asyncio.create_task(self.schedule())

    async def stop(self):
        self.stopping = True
        tasks = [t for t in [self.task, *self.jobs.values()] if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.session:
            await self.session.close()
        self.cache.clear()

    def status(self, identifier):
        return {
            **self.statuses.get(
                identifier,
                {"running": False, "last_success": None, "error": None, "warnings": []},
            ),
            "ready_variants": [
                key for key in self.cache if self.cache[key]["asset_id"] == identifier
            ],
        }

    def public(self):
        return {
            "isolation": self.isolation,
            "error": self.isolation_error,
            "cache_bytes": sum(v["bytes"] for v in self.cache.values()),
            "cache_limit": MAX_CACHE,
            "default_script": DEFAULT_SOURCE,
            "api_version": 1,
        }

    def output(self, identifier):
        try:
            result = self.cache[identifier]
        except KeyError:
            raise ValueError(
                "Dynamic image is not ready yet; retry after rendering."
            ) from None
        self.cache.move_to_end(identifier)
        return result

    def invalidate(self, identifier):
        self.due[identifier] = 0
        if identifier in self.jobs:
            self.dirty.add(identifier)

    def forget(self, identifier):
        for key in list(self.cache):
            if key == identifier or self.cache[key]["asset_id"] == identifier:
                del self.cache[key]
        self.statuses.pop(identifier, None)
        self.due.pop(identifier, None)

    async def snapshot(self, entities):
        try:
            return await asyncio.wait_for(self._snapshot(entities), 10)
        except TimeoutError:
            raise ValueError(
                "Home Assistant snapshot timed out; the last good image is retained."
            ) from None

    async def _snapshot(self, entities):
        if not entities:
            return {}
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token or not self.session:
            raise ValueError(
                "Home Assistant API is unavailable. Sensor rendering requires the installed add-on with API access."
            )
        result = {}
        for entity in entities:
            try:
                async with self.session.get(
                    "http://supervisor/core/api/states/" + entity,
                    headers={"Authorization": "Bearer " + token},
                    allow_redirects=False,
                ) as response:
                    if response.status == 404:
                        result[entity] = {"state": "unavailable", "attributes": {}}
                        continue
                    if response.status != 200:
                        raise ValueError(
                            "Home Assistant sensor snapshot could not be loaded."
                        )
                    chunks, size = [], 0
                    async for block in response.content.iter_chunked(16384):
                        size += len(block)
                        if size > 65536:
                            raise ValueError(
                                "Home Assistant entity data exceeds its size limit."
                            )
                        chunks.append(block)
                    value = json.loads(b"".join(chunks))
                    if (
                        not isinstance(value, dict)
                        or not isinstance(value.get("state"), str)
                        or not isinstance(value.get("attributes"), dict)
                    ):
                        raise ValueError(  # noqa: TRY004 — remote service validation, not a caller type error.
                            "Home Assistant returned an invalid entity snapshot."
                        )
                    result[entity] = {
                        k: value[k]
                        for k in ("state", "attributes", "last_changed", "last_updated")
                        if k in value
                    }
            except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError, UnicodeError, RecursionError):
                raise ValueError(
                    "Home Assistant is unavailable; the last good image is retained."
                ) from None
        if len(json.dumps(result)) > 262144:
            raise ValueError("Selected Home Assistant snapshot exceeds 256 KiB.")
        return result

    async def calendar_snapshot(self, document, now):
        return await calendar_snapshot.snapshot(
            self.session,
            os.environ.get("SUPERVISOR_TOKEN"),
            document,
            now,
        )

    async def generate(self, document, target, states, now, calendars=None):
        started = time.perf_counter()
        if not self.isolation:
            raise ValueError(
                self.isolation_error or "Dynamic image isolation is not ready."
            )
        profile = PROFILES[target["profile"]]
        size = view_size(profile["id"], target["orientation"])
        palette = (
            {
                "black": "#000000",
                "white": "#ffffff",
                **{f"gray{i}": "#" + format(v, "02x") * 3 for i, v in enumerate(GRAY8)},
            }
            if profile.get("format") == "png"
            else {
                name: "#" + "".join(format(c, "02x") for c in COLORS[code])
                for name, code in {
                    "black": 0,
                    "blue": 1,
                    "green": 2,
                    "red": 3,
                    "yellow": 5,
                    "white": 6,
                }.items()
            }
        )
        if target["palette"] == "grayscale":
            palette = {k: v for k, v in palette.items() if k in ("black", "white")}
        clock = datetime.fromtimestamp(now, ZoneInfo(document["timezone"]))
        inputs = {
            "width": size[0],
            "height": size[1],
            "states": states,
            "calendars": calendars or {},
            "palette": {k: "palette:" + k for k in palette},
            "now": {
                "hour": clock.hour,
                "minute": clock.minute,
                "second": clock.second,
                "year": clock.year,
                "month": clock.month,
                "day": clock.day,
                "weekday": clock.isoweekday(),
                "iso": clock.isoformat(),
                "timestamp": now,
            },
        }
        result = await worker(
            {"mode": "commands", "source": document["script"], "input": inputs},
            timeout=6,
        )
        script_done = time.perf_counter()
        images, fonts = {}, {}
        resource_bytes = 0
        for command in result["commands"]:
            kind = command["type"]
            identifier = (
                command.get("id")
                if kind == "image"
                else command.get("font")
                if kind == "text"
                else None
            )
            if not identifier or identifier == "default":
                continue
            collection = images if kind == "image" else fonts
            if identifier in collection:
                continue
            if len(images) + len(fonts) >= 32:
                raise ValueError(
                    "At most 32 image/font resources may be used in one render."
                )
            try:
                item = self.store.get(
                    "asset" if kind == "image" else "font", identifier
                )
                if item.get("dynamic"):
                    continue
                path = self.store.path(item["file"])
                if path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError(
                        "An embedded image/font exceeds the 8 MiB per-resource limit."
                    )
                resource_size = path.stat().st_size
                if resource_bytes + resource_size > 12 * 1024 * 1024:
                    raise ValueError(
                        "Selected image/font resources exceed the 12 MiB combined budget."
                    )
                resource_bytes += resource_size
                collection[identifier] = base64.b64encode(
                    await asyncio.to_thread(path.read_bytes)
                ).decode()
            except (KeyError, OSError):
                continue  # Renderer implements the agreed missing-resource fallbacks.
        resources_done = time.perf_counter()
        result = await worker(
            {
                "mode": "render",
                "commands": result["commands"],
                "size": size,
                "profile": profile,
                "palette": palette,
                "recipe": target,
                "images": images,
                "fonts": fonts,
            }
        )
        output, source = (
            base64.b64decode(result["output"]),
            base64.b64decode(result["source"]),
        )
        await asyncio.to_thread(
            validate_variant, output,
            profile["id"],
            monochrome=profile.get("format") == "png"
            and target["palette"] == "grayscale",
        )
        return {
            "output": output,
            "source": source,
            "mime": result["mime"],
            "hash": digest(output),
            "bytes": len(output) + len(source),
            "warnings": result["warnings"],
            "timings": {
                "total_seconds": time.perf_counter() - started,
                "script_seconds": script_done - started,
                "resources_seconds": resources_done - script_done,
                "render_worker_seconds": time.perf_counter() - resources_done,
                **result.get("timings", {}),
            },
            "optimizer": OPTIMIZER_VERSION,
            "rendered_at": now,
            "asset_id": document["id"],
        }

    async def preview(self, data):
        document = definition({k: v for k, v in data.items() if k != "recipe"})
        target = recipe(data["recipe"])
        if self.pending >= 4:
            raise ValueError(
                "The render queue is full. Wait for an active render to finish."
            )
        self.pending += 1
        try:
            async with self.lock:
                now = time.time()
                snapshot_started = time.perf_counter()
                states = await self.snapshot(document["entities"])
                calendars = await self.calendar_snapshot(document, now)
                snapshot_seconds = time.perf_counter() - snapshot_started
                result = await self.generate(
                    {**document, "id": "preview"},
                    target,
                    states,
                    now,
                    calendars,
                )
                result["timings"]["snapshot_seconds"] = snapshot_seconds
                return result
        finally:
            self.pending -= 1

    def launch(self, identifier):
        if identifier not in self.jobs:
            if len(self.jobs) >= 4:
                raise ValueError(
                    "The render queue is full. Wait for an active render to finish."
                )
            job = asyncio.create_task(self._render(identifier))
            self.jobs[identifier] = job

            def finished(task):
                if self.jobs.get(identifier) is task:
                    self.jobs.pop(identifier, None)
                if not task.cancelled():
                    task.exception()  # Consume scheduled failures; status retains the error.

            job.add_done_callback(finished)
        return self.jobs[identifier]

    async def render(self, identifier):
        return await asyncio.shield(self.launch(identifier))

    async def _render(self, identifier):
        status = self.statuses.setdefault(
            identifier, {"last_success": None, "warnings": []}
        )
        started = time.perf_counter()
        status.update(running=True, error=None, last_attempt=time.time())
        timings = {"targets": []}
        try:
            document = self.store.get("asset", identifier)
            targets = [
                v for v in self.store.all("variant") if v["asset_id"] == identifier
            ]
            if not targets:
                raise ValueError("Create a target variant before rendering.")
            snapshot_started = time.perf_counter()
            now = time.time()
            states = await self.snapshot(document["entities"])
            calendars = await self.calendar_snapshot(document, now)
            timings["snapshot_seconds"] = time.perf_counter() - snapshot_started
            results = {}
            for target in targets:
                queued = time.perf_counter()
                async with self.lock:
                    queue_seconds = time.perf_counter() - queued
                    results[target["id"]] = await self.generate(
                        document, target["recipe"], states, now, calendars
                    )
                    timings["targets"].append(
                        {
                            "id": target["id"],
                            "name": target["name"],
                            "queue_seconds": queue_seconds,
                            **results[target["id"]]["timings"],
                        }
                    )
            if self.store.get("asset", identifier)["modified"] != document["modified"]:
                raise ValueError(
                    "Script changed during rendering; render the saved version again."
                )
            for target in targets:
                if self.store.get("variant", target["id"]) != target:
                    raise ValueError("Target changed during rendering; render again.")
            used = sum(
                v["bytes"] for key, v in self.cache.items() if key not in results
            )
            if used + sum(v["bytes"] for v in results.values()) > MAX_CACHE:
                raise ValueError(
                    "Dynamic RAM cache is full. Remove unused target variants."
                )
            # One atomic replacement on the event-loop thread; no DB/file writes.
            self.cache.update(results)
            status.update(
                last_success=now,
                warnings=list(
                    dict.fromkeys(w for r in results.values() for w in r["warnings"])
                )[:30],
            )
            return self.status(identifier)
        except KeyError:
            status["error"] = "Dynamic image or target no longer exists."
            raise ValueError(status["error"]) from None
        except ValueError as error:
            status["error"] = str(error)
            raise
        except Exception:  # noqa: BLE001 — contain worker/protocol faults without exposing host details.
            status["error"] = "Rendering failed; the last good image is retained."
            raise ValueError(status["error"]) from None
        finally:
            timings["total_seconds"] = time.perf_counter() - started
            status["timings"] = timings
            status["running"] = False
            with contextlib.suppress(KeyError):
                self.due[identifier] = (
                    0
                    if identifier in self.dirty
                    else time.monotonic()
                    + self.store.get("asset", identifier)["interval"]
                )
                self.dirty.discard(identifier)

    async def schedule(self):
        while not self.stopping:
            if self.isolation and not self.jobs and self.pending == 0:
                eligible = [
                    a
                    for a in self.store.all("asset")
                    if a.get("dynamic") and time.monotonic() >= self.due.get(a["id"], 0)
                ]
                if eligible:
                    item = min(eligible, key=lambda a: self.due.get(a["id"], 0))
                    self.due[item["id"]] = time.monotonic() + item["interval"]
                    self.launch(item["id"])
            await asyncio.sleep(1)
