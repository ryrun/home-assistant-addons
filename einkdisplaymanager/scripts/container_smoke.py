"""Run inside the actual unprivileged Linux image on both supported architectures."""

import asyncio
import sys

sys.path.insert(0, "/app")
from dynamic import recipe, worker
from media import validate_variant
from profiles import PROFILES


async def main():
    result = await worker({"mode": "probe"})
    assert result["isolation"] == "linux-seccomp", result
    script = 'screen.text("FÜNF gyp",{x:20,y:30,verticalAlign:"middle",verticalMetrics:"font"});screen.text("ZEHN",{x:20,y:70,verticalAlign:"baseline"});screen.circle({x:100,y:100,radius:20,fill:palette.black});'
    commands = await worker(
        {
            "mode": "commands",
            "source": script,
            "input": {
                "width": 800,
                "height": 600,
                "states": {},
                "palette": {"black": "palette:black"},
                "now": {},
            },
        }
    )
    for profile in ("openpaper_l", "openpaper_7", "inkplate_6"):
        p = PROFILES[profile]
        target = recipe({"profile": profile})
        import base64

        result = await worker(
            {
                "mode": "render",
                "commands": commands["commands"],
                "size": [p["width"], p["height"]],
                "profile": p,
                "recipe": target,
                "palette": {"black": "#000000"},
                "images": {},
                "fonts": {},
            }
        )
        validate_variant(base64.b64decode(result["output"]), profile)
    # Regression: nearest-color LAB on a full 800×600 Inkplate preview used to
    # recompute palette LAB for every pixel and exhaust the optimizer CPU budget.
    target = recipe({"profile": "inkplate_6", "matching": "lab", "dither": "none"})
    result = await worker(
        {
            "mode": "render",
            "commands": commands["commands"],
            "size": [800, 600],
            "profile": PROFILES["inkplate_6"],
            "recipe": target,
            "palette": {"black": "#000000"},
            "images": {},
            "fonts": {},
        }
    )
    validate_variant(base64.b64decode(result["output"]), "inkplate_6")
    print(
        "Verified Linux seccomp, bounded JavaScript, and native output for all display profiles."
    )


asyncio.run(main())
