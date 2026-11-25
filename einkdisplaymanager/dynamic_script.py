"""Lightweight QuickJS worker and common isolated pipe protocol."""

import json
import math
import sys
import time
from pathlib import Path

import quickjs
from sandbox import probe, restrict


def context(seconds=2, memory=32):
    ctx = quickjs.Context()
    ctx.set_memory_limit(memory * 1024 * 1024)
    ctx.set_max_stack_size(512 * 1024)
    ctx.set_time_limit(seconds)
    return ctx


def commands(payload, api):
    ctx = context()
    ctx.set("__input", json.dumps(payload["input"], allow_nan=False))
    ctx.set("__source", payload["source"])
    try:
        return json.loads(ctx.eval(api))
    except quickjs.JSException as error:
        if "InternalError: interrupted" in str(error):
            raise ValueError(
                "Script execution exceeded its CPU limit. Check for long or infinite loops."
            ) from None
        raise


def validate(commands):
    if not isinstance(commands, list) or len(commands) > 1000:
        raise ValueError("At most 1000 drawing commands are allowed.")
    fields = {
        "clear": {"color"},
        "text": {
            "text",
            "x",
            "y",
            "font",
            "fontSize",
            "color",
            "align",
            "verticalAlign",
            "verticalMetrics",
            "maxWidth",
        },
        "line": {"x1", "y1", "x2", "y2", "stroke", "strokeWidth"},
        "rectangle": {"x", "y", "width", "height", "fill", "stroke", "strokeWidth"},
        "circle": {"x", "y", "radius", "fill", "stroke", "strokeWidth"},
        "image": {"id", "x", "y", "width", "height", "fit"},
    }
    numeric = {
        "x",
        "y",
        "x1",
        "x2",
        "y1",
        "y2",
        "width",
        "height",
        "radius",
        "strokeWidth",
        "fontSize",
        "maxWidth",
    }
    for c in commands:
        if (
            not isinstance(c, dict)
            or c.get("type") not in fields
            or set(c) - fields[c["type"]] - {"type"}
        ):
            raise ValueError("Unknown drawing command or option.")
        for key, value in c.items():
            if key in numeric:
                if (
                    type(value) not in (float, int)
                    or not math.isfinite(value)
                    or abs(value) > 10000
                ):
                    raise ValueError(
                        "Drawing coordinates must be finite numbers within ±10000."
                    )
                if (
                    key
                    in {
                        "width",
                        "height",
                        "radius",
                        "strokeWidth",
                        "fontSize",
                        "maxWidth",
                    }
                    and not 0 < value <= 4096
                ):
                    raise ValueError("Drawing sizes must be between 0 and 4096 pixels.")
            elif not isinstance(value, str) or len(value) > (
                8192 if key == "text" else 120
            ):
                raise ValueError("Invalid drawing text or option.")


def exchange(handle):
    initialized = time.perf_counter()
    payload = json.loads(sys.stdin.buffer.read(24 * 1024 * 1024))
    input_ready = time.perf_counter()
    isolation = restrict()
    isolated = time.perf_counter()
    result = handle(payload, isolation, isolated)
    if "timings" in result:
        result["timings"].update(
            worker_ready_at=initialized,
            worker_finished_at=time.perf_counter(),
            input_seconds=input_ready - initialized,
            sandbox_seconds=isolated - input_ready,
        )
    sys.stdout.write(json.dumps(result, separators=(",", ":")))


def worker_error(error):
    if isinstance(error, quickjs.JSException):
        # QuickJS errors contain only user-source locations.
        return {"error": str(error)[:1000]}
    # Native host exception text can contain filesystem paths or input data.
    return {"error": str(error)[:300] if isinstance(error, ValueError) else "Isolated render failed."}


def run_worker(handle):
    try:
        exchange(handle)
    except Exception as error:  # noqa: BLE001 — untrusted rendering must not expose host tracebacks.
        sys.stdout.write(json.dumps(worker_error(error)))
        sys.exit(1)


def script_handler(api):
    def handle(payload, isolation, isolated):
        if payload["mode"] == "probe":
            probe()
            return {"isolation": isolation}
        if payload["mode"] != "commands":
            raise ValueError("Unsupported script worker mode.")
        result = commands(payload, api)
        executed = time.perf_counter()
        validate(result["commands"])
        result["timings"] = {
            "quickjs_seconds": executed - isolated,
            "command_validation_seconds": time.perf_counter() - executed,
        }
        return result

    return handle


if __name__ == "__main__":
    api = Path(__file__).with_name("web").joinpath("drawing-api.js").read_text()
    run_worker(script_handler(api))
