"""Run inside the actual unprivileged Linux image on both supported architectures."""

import asyncio
import base64
import io
import sys

from PIL import Image, ImageCms

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
        target = recipe(
            {
                "profile": profile,
                **(
                    {
                        "palette": "openpaper_l_measured",
                        "matching": "lab",
                        "dither": "floyd",
                    }
                    if profile == "openpaper_l"
                    else {}
                ),
            }
        )
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
    # The new 16-bit blue-noise asset is decoded without network/filesystem access.
    p = PROFILES["inkplate_6"]
    noise = await worker(
        {
            "mode": "render",
            "size": [800, 600],
            "profile": p,
            "recipe": recipe({"profile": "inkplate_6", "dither": "blueNoise"}),
            "commands": [{"type": "clear", "color": "#b0b0b0"}],
            "palette": {},
            "images": {},
            "fonts": {},
        }
    )
    validate_variant(base64.b64decode(noise["output"]), "inkplate_6")
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
    # Exercise the custom PNG encoder under the same restrictions as real renders.
    custom = {"id": "custom_smoke", "width": 1280, "height": 600, "format": "png",
              "native_orientation": "landscape", "custom": True}
    for colors in ([], ["#123456", "#ffffff"]):
        profile = {**custom, "rgb_colors": colors, "dither": "floyd" if colors else "none"}
        widget = await worker({
            "mode": "render", "size": [1280, 600], "profile": profile, "recipe": {},
            "commands": [{"type": "clear", "color": "palette:background"}],
            "palette": {"background": "#123456"}, "images": {}, "fonts": {},
        })
        assert widget["mime"] == "image/png"
        validate_variant(base64.b64decode(widget["output"]), profile)
    # Keep JPEG/PNG EXIF, ICC conversion and BMP usable with bounded codec setup.
    source_images = {}
    image_commands = []
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    exif = Image.Exif()
    exif[274] = 6  # Rotate portrait input into a landscape strip.
    for index, fmt in enumerate(("JPEG", "PNG", "BMP")):
        picture = Image.new("RGB", (8, 16), "white")
        picture.paste("black", (0, 0, 8, 8))
        options = {"exif": exif, "icc_profile": icc} if fmt != "BMP" else {}
        with io.BytesIO() as encoded:
            picture.save(encoded, fmt, **options)
            source_images[fmt] = base64.b64encode(encoded.getvalue()).decode()
        image_commands.append({"type": "image", "id": fmt, "x": 16 * index, "y": 0})
    embedded = await worker({
        "mode": "render", "size": [64, 64], "profile": {**custom, "rgb_colors": [], "dither": "none"},
        "recipe": {}, "commands": image_commands, "palette": {}, "images": source_images, "fonts": {},
    })
    with Image.open(io.BytesIO(base64.b64decode(embedded["output"]))) as image:
        for left in (0, 16):
            assert image.getpixel((left + 2, 4))[0] >= 245
            assert image.getpixel((left + 13, 4))[0] <= 10
        assert image.getpixel((34, 4)) == (0, 0, 0)
        assert image.getpixel((34, 12)) == (255, 255, 255)
    print(
        "Verified Linux seccomp, bounded JavaScript, and native output for all display profiles."
    )


asyncio.run(main())
