"""Disposable restricted QuickJS / Pillow worker; inputs and outputs are pipes only."""

import base64
import io
import json
import math
import struct
import sys
import time
from pathlib import Path

import quickjs
from PIL import Image, ImageCms, ImageColor, ImageDraw, ImageFont, ImageOps
from sandbox import probe, restrict

ROOT = Path(__file__).parent
API = (ROOT / "web" / "drawing-api.js").read_text()
VENDOR = (ROOT / "web" / "vendor" / "epdoptimize-1.4.1.mjs").read_text()
# The pinned ESM build is evaluated only in the trusted processing context.
# Disable URL resolution there; blue-noise samples are loaded before isolation.
VENDOR = (
    VENDOR[: VENDOR.rfind("export {")]
    .replace(
        'new URL("assets/blue-noise-1200x1600.png", import.meta.url).href',
        '"disabled:"',
    )
    .replace("import.meta.url", '"disabled:"')
    + "\nglobalThis.epd={ditherImage:On,suggest:Ur,natural:Wi,spectra6:Hi,aitjcize:Ki,getPreset:ge};"
)
PANEL_PALETTES = (ROOT / "web" / "panel-palettes.js").read_text().replace("export ", "")
BLUE_NOISE_PNG = (
    ROOT / "web" / "vendor" / "assets" / "blue-noise-1200x1600.png"
).read_bytes()
NEAREST_ADAPTER = (ROOT / "web" / "optimizer-nearest.js").read_text()
PIXEL_ADAPTER = (ROOT / "web" / "optimizer-pixels.js").read_text()
PROCESSING = (ROOT / "web" / "processing.js").read_text().replace("export ", "")
OPTIONS = (
    (ROOT / "web" / "optimizer-options.js")
    .read_text()
    .split("\n", 2)[2]
    .replace("export ", "")
)
OPTIONS = "const getProcessingPreset=epd.getPreset;\n" + OPTIONS
Image.init()  # Load codec modules before filesystem access is disabled.
Image.MAX_IMAGE_PIXELS = 8_000_000
DEFAULT_FONT = ImageFont.load_default(size=16)  # Pillow's bundled Aileron.
SRGB = ImageCms.createProfile("sRGB")
# Force optional native modules to load before seccomp denies opens.
Image.new("RGB", (1, 1)).save(io.BytesIO(), "PNG")


def context(seconds=2, memory=32):
    ctx = quickjs.Context()
    ctx.set_memory_limit(memory * 1024 * 1024)
    ctx.set_max_stack_size(512 * 1024)
    ctx.set_time_limit(seconds)
    return ctx


def commands(payload):
    ctx = context()
    ctx.set("__input", json.dumps(payload["input"], allow_nan=False))
    ctx.set("__source", payload["source"])
    try:
        return json.loads(ctx.eval(API))
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


def draw(payload):
    validate(payload["commands"])
    width, height = payload["size"]
    if not 1 <= width <= 1600 or not 1 <= height <= 1600:
        raise ValueError("Unsupported canvas dimensions.")
    image = Image.new("RGB", (width, height), "white")
    ink = ImageDraw.Draw(image)
    exact = Image.new("L", image.size, 0)
    exact_mask = Image.new("1", image.size, 0)

    def mark(method, args, colors, **options):
        for surface, coverage in ((exact, False), (exact_mask, True)):
            pen = ImageDraw.Draw(surface)
            pen.fontmode = "1"
            fields = {}
            for field, value in colors.items():
                if value is None:
                    fields[field] = None
                    continue
                explicit = value.startswith("palette:")
                code = 0
                if explicit and not coverage:
                    code = (
                        color(value)[0]
                        if payload["profile"].get("format") == "png"
                        else {
                            "black": 0,
                            "blue": 1,
                            "green": 2,
                            "red": 3,
                            "yellow": 5,
                            "white": 6,
                        }[value[8:]]
                    )
                fields[field] = int(explicit) if coverage else code
            getattr(pen, method)(*args, **fields, **options)

    warnings = []
    font_cache = {}

    def color(value):
        if value is None:
            return None
        if value.startswith("palette:"):
            value = payload["palette"].get(value[8:])
            if value is None:
                raise ValueError("This color is not available in the target palette.")
        try:
            rgb = ImageColor.getrgb(value)
            if len(rgb) != 3:
                raise ValueError("Use opaque RGB colors.")
            return rgb
        except ValueError:
            raise ValueError(
                "Use a named color, #RRGGBB, or a color from palette."
            ) from None

    def font(identifier, size):
        key = (identifier, size)
        if key not in font_cache:
            data = payload.get("fonts", {}).get(identifier)
            if data:
                font_cache[key] = ImageFont.truetype(
                    io.BytesIO(base64.b64decode(data)), size
                )
            else:
                if identifier and identifier != "default":
                    warnings.append(
                        f"Font {identifier} is missing; using the default font."
                    )
                font_cache[key] = ImageFont.load_default(size=size)
        return font_cache[key]

    for c in payload["commands"]:
        kind, x, y = c["type"], c.get("x", 0), c.get("y", 0)
        if kind == "clear":
            ink.rectangle((0, 0, width, height), fill=color(c.get("color", "#ffffff")))
            mark(
                "rectangle",
                [(0, 0, width, height)],
                {"fill": c.get("color", "#ffffff")},
            )
        elif kind == "text":
            align = c.get("align", "left")
            vertical = c.get("verticalAlign", "top")
            if align not in ("left", "center", "right") or vertical not in (
                "top",
                "middle",
                "bottom",
                "baseline",
            ):
                raise ValueError("Invalid text alignment.")
            metrics = c.get("verticalMetrics", "text")
            if metrics not in ("text", "font"):
                raise ValueError("Invalid vertical text metrics; use text or font.")
            selected = font(c.get("font", "default"), round(c.get("fontSize", 24)))
            text = c.get("text", "")
            if "maxWidth" in c:
                words, lines, line = text.split(), [], ""
                for word in words:
                    candidate = (line + " " + word).strip()
                    if (
                        line
                        and ink.textlength(candidate, font=selected) > c["maxWidth"]
                    ):
                        lines.append(line)
                        line = word
                    else:
                        line = candidate
                text = "\n".join(lines + [line])
            if metrics == "font" or vertical == "baseline":
                # A fixed ascent/descent frame, independent of the current glyphs.
                # Baseline anchors avoid Pillow's content-dependent multiline spacing.
                ascent, descent = selected.getmetrics()
                lines = text.split("\n")
                advance = ascent + descent + 4  # Existing default inter-line gap.
                frame_height = len(lines) * (ascent + descent) + (len(lines) - 1) * 4
                baseline = (
                    y
                    if vertical == "baseline"
                    else (
                        y
                        - {"top": 0, "middle": 0.5, "bottom": 1}[vertical]
                        * frame_height
                        + ascent
                    )
                )
                for index, line in enumerate(lines):
                    box = ink.textbbox((0, 0), line, font=selected, anchor="ls")
                    position = (
                        x
                        - {"left": 0, "center": 0.5, "right": 1}[align]
                        * (box[2] - box[0])
                        - box[0],
                        baseline + index * advance,
                    )
                    ink.text(
                        position,
                        line,
                        font=selected,
                        anchor="ls",
                        fill=color(c.get("color", "#000000")),
                    )
                    mark(
                        "text",
                        [position, line],
                        {"fill": c.get("color", "#000000")},
                        font=selected,
                        anchor="ls",
                    )
                continue
            box = ink.multiline_textbbox((0, 0), text, font=selected, align=align)
            text_width, text_height = box[2] - box[0], box[3] - box[1]
            position = (
                x - {"left": 0, "center": 0.5, "right": 1}[align] * text_width - box[0],
                y
                - {"top": 0, "middle": 0.5, "bottom": 1}[vertical] * text_height
                - box[1],
            )
            ink.multiline_text(
                position,
                text,
                font=selected,
                fill=color(c.get("color", "#000000")),
                align=align,
            )
            mark(
                "multiline_text",
                [position, text],
                {"fill": c.get("color", "#000000")},
                font=selected,
                align=align,
            )
        elif kind in ("rectangle", "circle"):
            box = (
                (x, y, x + c.get("width", 100), y + c.get("height", 100))
                if kind == "rectangle"
                else (
                    x - c.get("radius", 20),
                    y - c.get("radius", 20),
                    x + c.get("radius", 20),
                    y + c.get("radius", 20),
                )
            )
            method = ink.rectangle if kind == "rectangle" else ink.ellipse
            method(
                box,
                fill=color(c.get("fill")),
                outline=color(c.get("stroke")),
                width=round(c.get("strokeWidth", 1)),
            )
            mark(
                "rectangle" if kind == "rectangle" else "ellipse",
                [box],
                {"fill": c.get("fill"), "outline": c.get("stroke")},
                width=round(c.get("strokeWidth", 1)),
            )
        elif kind == "line":
            ink.line(
                (c.get("x1", 0), c.get("y1", 0), c.get("x2", 0), c.get("y2", 0)),
                fill=color(c.get("stroke", "#000000")),
                width=round(c.get("strokeWidth", 1)),
            )
            mark(
                "line",
                [(c.get("x1", 0), c.get("y1", 0), c.get("x2", 0), c.get("y2", 0))],
                {"fill": c.get("stroke", "#000000")},
                width=round(c.get("strokeWidth", 1)),
            )
        elif kind == "image":
            source = payload.get("images", {}).get(c.get("id"))
            if source is None:
                warnings.append(
                    f"Image {c.get('id', '')} is missing; nothing was drawn."
                )
                continue
            with Image.open(io.BytesIO(base64.b64decode(source))) as original:
                original = ImageOps.exif_transpose(original)
                alpha = original.convert("RGBA").getchannel("A")
                profile_data = original.info.get("icc_profile")
                if profile_data:
                    original = ImageCms.profileToProfile(
                        original, io.BytesIO(profile_data), SRGB, outputMode="RGB"
                    )
                original = original.convert("RGBA")
                original.putalpha(alpha)
                size = (
                    round(c.get("width", original.width)),
                    round(c.get("height", original.height)),
                )
                if c.get("fit", "contain") not in ("contain", "cover"):
                    raise ValueError("Image fit must be contain or cover.")
                fitted = (
                    ImageOps.fit(original, size, method=Image.Resampling.LANCZOS)
                    if c.get("fit") == "cover"
                    else ImageOps.contain(
                        original, size, method=Image.Resampling.LANCZOS
                    )
                )
                image.paste(
                    fitted,
                    (
                        round(x + (size[0] - fitted.width) / 2),
                        round(y + (size[1] - fitted.height) / 2),
                    ),
                    fitted,
                )
                exact_mask.paste(
                    0,
                    (
                        round(x + (size[0] - fitted.width) / 2),
                        round(y + (size[1] - fitted.height) / 2),
                    ),
                    fitted.getchannel("A"),
                )
    return image, list(dict.fromkeys(warnings))[:30], exact, exact_mask


def optimize(image, recipe, profile, exact=None, exact_mask=None):
    try:
        return _optimize(image, recipe, profile, exact, exact_mask)
    except quickjs.JSException as error:
        if "InternalError: interrupted" in str(error):
            raise ValueError(
                "Image optimization exceeded its CPU limit. Reduce processing complexity or disable automatic optimization."
            ) from None
        raise


def _quantize(image, recipe, profile):
    gray = profile.get("format") == "png"
    if gray:
        image = image.convert("L").convert("RGB")
    rgba = image.convert("RGBA")
    ctx = context(20, 256)
    ctx.eval(
        VENDOR
        + "\n"
        + NEAREST_ADAPTER
        + "\n"
        + PIXEL_ADAPTER
        + "\n"
        + PROCESSING
        + "\n"
        + OPTIONS
        + "\n"
        + PANEL_PALETTES
    )
    if recipe["dither"] == "blueNoise":
        with Image.open(io.BytesIO(BLUE_NOISE_PNG)) as noise:
            mask = noise.convert("I;16").tobytes()
            ctx.set("__noise", mask.decode("latin1"))
            ctx.set("__noiseWidth", noise.width)
            ctx.set("__noiseHeight", noise.height)
        ctx.eval(
            "var samples=new Uint16Array(__noise.length/2);for(var n=0;n<samples.length;n++)samples[n]=__noise.charCodeAt(n*2)|(__noise.charCodeAt(n*2+1)<<8);O={width:__noiseWidth,height:__noiseHeight,samples,maxValue:65535};__noise=null;"
        )
    ctx.set("__raw", rgba.tobytes().decode("latin1"))
    ctx.set("__recipe", json.dumps(recipe))
    ctx.set("__width", image.width)
    ctx.set("__height", image.height)
    ctx.set("__gray", gray)
    ctx.eval("""
    var recipe=JSON.parse(__recipe), levels=Array.from({length:8},(_,i)=>Math.round(i*255/7));
    var palette=__gray?levels.map((v,i)=>({name:'gray'+i,color:'#'+v.toString(16).padStart(2,'0').repeat(3)})):
      (recipe.palette==='openpaper_l_measured'?measuredOpenPaperLPalette:recipe.palette==='spectra6'?epd.spectra6:recipe.palette==='aitjcize'?epd.aitjcize:epd.natural);
    if(recipe.palette==='grayscale')palette=palette.filter(p=>__gray?['gray0','gray7'].includes(p.name):['black','white'].includes(p.name));
    var pixels=einkPixels.decodeRGBA(__raw,__width,__height);
    __raw=null;
    var canvas={width:__width,height:__height,getContext(){return {getImageData(){return pixels},putImageData(p){pixels=p;}}}};
    var suggestion=recipe.automatic?epd.suggest(pixels,palette,{intent:recipe.intent||'natural'}):null;
    var options=processingOptions(recipe,suggestion).options;options.palette=palette;
    var ready=false,error=null;
    epd.ditherImage(canvas,canvas,options).then(()=>{ready=true},e=>{error=String(e)});
    """)
    while ctx.execute_pending_job():
        pass
    if not ctx.eval("ready"):
        raise ValueError("Image optimization failed.")
    result = ctx.eval("einkPixels.encodeIndices(pixels,palette,__gray,levels)")
    indices = Image.frombytes("L", image.size, bytes.fromhex(result))
    return indices


def _optimize(image, recipe, profile, exact=None, exact_mask=None):
    gray = profile.get("format") == "png"
    if (
        exact is not None
        and exact_mask is not None
        and exact_mask.mode == "1"
        and exact_mask.getextrema()[0]
    ):
        # Every pixel is explicit ink. The previous pipeline overwrote every
        # optimizer pixel with these exact codes, regardless of recipe settings.
        indices = exact.copy()
    else:
        indices = _quantize(image, recipe, profile)
        if exact is not None:
            indices.paste(exact, (0, 0), exact_mask)
    if gray and recipe["invert"]:
        indices = ImageOps.invert(indices)
    if recipe["orientation"] != profile["native_orientation"]:
        indices = indices.transpose(Image.Transpose.ROTATE_90)
    output = io.BytesIO()
    if gray:
        indices.save(output, "PNG")
    else:
        width, height = indices.size
        header = bytearray(118)
        header[:2] = b"BM"
        struct.pack_into("<I", header, 2, 118 + width * height // 2)
        struct.pack_into("<I", header, 10, 118)
        struct.pack_into(
            "<IiiHHIIiiII",
            header,
            14,
            40,
            width,
            -height,
            1,
            4,
            0,
            width * height // 2,
            2835,
            2835,
            16,
            16,
        )
        for code, rgb in {
            0: (0, 0, 0),
            1: (0, 0, 255),
            2: (0, 255, 0),
            3: (255, 0, 0),
            5: (255, 255, 0),
            6: (255, 255, 255),
        }.items():
            header[54 + code * 4 : 58 + code * 4] = bytes((*reversed(rgb), 0))
        data = indices.tobytes()
        output.write(header)
        output.write(bytes((a << 4) | b for a, b in zip(data[::2], data[1::2])))
    return output.getvalue(), "image/png" if gray else "image/bmp"


def main():
    payload = json.loads(sys.stdin.buffer.read(24 * 1024 * 1024))
    isolation = restrict()
    if payload["mode"] == "probe":
        probe()
        result = {"isolation": isolation}
    elif payload["mode"] == "commands":
        result = commands(payload)
        validate(result["commands"])
    elif payload["mode"] == "font":
        font = ImageFont.truetype(io.BytesIO(base64.b64decode(payload["data"])), 32)
        result = {"valid": bool(font.getbbox("Font validation"))}
    else:
        started = time.perf_counter()
        image, warnings, exact, exact_mask = draw(payload)
        drawn = time.perf_counter()
        source = io.BytesIO()
        image.save(source, "PNG")
        encoded = time.perf_counter()
        data, mime = optimize(
            image, payload["recipe"], payload["profile"], exact, exact_mask
        )
        result = {
            "source": base64.b64encode(source.getvalue()).decode(),
            "output": base64.b64encode(data).decode(),
            "mime": mime,
            "warnings": warnings,
            "isolation": isolation,
            "timings": {
                "drawing_seconds": drawn - started,
                "source_encoding_seconds": encoded - drawn,
                "optimization_seconds": time.perf_counter() - encoded,
            },
        }
    sys.stdout.write(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except quickjs.JSException as error:
        # QuickJS errors contain only user-source locations, not Python paths.
        sys.stdout.write(json.dumps({"error": str(error)[:1000]}))
    except Exception as error:  # noqa: BLE001 — untrusted rendering must not expose host tracebacks.
        # Native host exception text can contain filesystem paths or input data.
        sys.stdout.write(
            json.dumps(
                {
                    "error": str(error)[:300]
                    if isinstance(error, ValueError)
                    else "Isolated render failed."
                }
            )
        )
        sys.exit(1)
