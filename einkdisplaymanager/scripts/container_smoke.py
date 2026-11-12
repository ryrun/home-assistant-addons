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
    calendar_commands = await worker(
        {
            "mode": "commands",
            "source": 'const events=ha.calendarEvents("calendar.test");screen.text(events[0].summary+":"+events[0].daysUntil);',
            "input": {
                "width": 800,
                "height": 600,
                "states": {},
                "palette": {},
                "now": {},
                "calendars": {
                    "calendar.test": [{"summary": "Calendar snapshot", "daysUntil": 1}]
                },
            },
        }
    )
    assert calendar_commands["commands"][0]["text"] == "Calendar snapshot:1"
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
    # Fully explicit ink must also render under the native worker restrictions.
    profile = PROFILES["openpaper_l"]
    explicit = await worker(
        {
            "mode": "render",
            "size": [profile["width"], profile["height"]],
            "profile": profile,
            "recipe": recipe(
                {
                    "profile": "openpaper_l",
                    "automatic": True,
                    "matching": "lab",
                    "dither": "floyd",
                }
            ),
            "commands": [
                {"type": "clear", "color": "palette:white"},
                {
                    "type": "text",
                    "text": "Exact ink",
                    "x": 20,
                    "y": 40,
                    "color": "palette:black",
                },
            ],
            "palette": {"white": "#ffffff", "black": "#000000"},
            "images": {},
            "fonts": {},
        }
    )
    validate_variant(base64.b64decode(explicit["output"]), "openpaper_l")
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
