# Upstream sources and licenses

The add-on's own Python/JavaScript/CSS implementation is covered by the repository
MIT license. Firmware/Web UI implementation files and calibration profiles are
not copied into this add-on.

## Firmware compatibility baseline

- Repository: https://github.com/paperlesspaper/paperlesspaper-firmware-offline
- Inspected commit: `64d47dfd4c57bb053d36813d212b4fe69aa04e8f` (2026-11-11).
- Web UI/flasher: https://paperlesspaper.github.io/paperlesspaper-firmware-offline/
- Source inspection only; this does not claim hardware compatibility acceptance
  with a device running that commit.
- File signatures, settings schema, palette codes, and image format restrictions
  inform the independently implemented protocol validation/encoder. Copying other
  upstream implementation/profile files requires a separate license review.

## epdoptimize 1.2.0

- Source: https://github.com/paperlesspaper/epdoptimize
- Distribution: https://registry.npmjs.org/epdoptimize/-/epdoptimize-1.2.0.tgz
- License: Apache-2.0, full text at `web/vendor/epdoptimize-LICENSE`.
- Unmodified npm `dist/index.mjs` copied to `web/vendor/epdoptimize-1.2.0.mjs`.
- SHA-256 of the vendored module:
  `f3f39f1a3ce6b2da5160ffad57ec6607b1d36d477590a71f2f942003c04f48ba`.
- The npm tarball contains no separate NOTICE file. Its bundled RgbQuant code is
  MIT-licensed; retain `web/vendor/RgbQuant-LICENSE` alongside the module.
- Library recipe/version is recorded with each saved variant. The vendored
  module makes no runtime CDN request; Node/npm is not needed in the container.

To reproduce the vendor files: use `npm pack epdoptimize@1.2.0`, unpack the tarball,
copy `dist/index.mjs` and `LICENSE` to the paths above, and verify the SHA-256.
Audit bundled dependencies/attributions before upgrading the package.

## RgbQuant.js (bundled by epdoptimize)

- Source: https://github.com/alexharris/RgbQuant.js
- License: MIT, copyright (c) 2017 Leon Sorokin.
- Full license: `web/vendor/RgbQuant-LICENSE`.

## Python runtime dependencies

`requirements.in` pins direct versions. `requirements.txt` pins all transitive
dependencies and permitted artifact hashes. Pillow is HPND-licensed; aiohttp and
its dependencies retain their distribution license notices in the container.
MQTT uses `aiomqtt==2.5.1` (BSD-3-Clause;
https://github.com/empicano/aiomqtt) and locked `paho-mqtt==2.2.0`
(EPL-2.0 OR BSD-3-Clause / Eclipse Distribution License;
https://github.com/eclipse-paho/paho.mqtt.python). Their installed distribution
license files remain in the image. Both MQTT dependencies ship platform-independent
Python wheels; no additional broker or native MQTT build is needed in the container.
Regenerate locks with pip-tools and verify Linux `aarch64`/`amd64` wheels before
release. Test dependencies are separately locked in `requirements-dev.txt`.

## OpenPaper 7 model addition

- Product: https://paperlesspaper.de/en/buy-7-inch-epaper-picture-frame
- Manufacturer model/dimensions: https://docs.paperlesspaper.de/manufacturing/bill-of-materials
- Native raster source: `src/epaper_display.h`, file blob
  `d4b5f35da0871dcc50677489e22bb26e87ba4dac` (checked 2026-11-11).
- Decoder source: `src/main.cpp`, file blob
  `c96c94eab76fa42dd7e1d8ffa9320a5c6a37c6ec`.
- Independently encoded model facts: OpenPaper 7 Spectra 6, 800 × 480 native
  landscape, six device codes, 192,118-byte BMP; OpenPaper L stays 1200 × 1600
  native portrait, 960,118-byte BMP. No firmware/driver implementation is copied.
- Both geometries and pixel rotations have software/browser validation only;
  physical OpenPaper 7 acceptance remains pending.

## Inkplate 6 / ESPHome addition

Researched 2026-11-11. Independently encoded hardware facts: native 800 × 600,
eight grayscale levels including black/white, ESPHome 3-bit grayscale mode with
full refresh. No manufacturer display driver or board pin configuration is copied.

- [Soldered hardware overview](https://docs.soldered.com/inkplate/6/overview/)
- [ESPHome Inkplate](https://esphome.io/components/display/inkplate/)
- [ESPHome Online Image](https://esphome.io/components/image/online_image/)
- [ESPHome HTTP and JSON](https://esphome.io/components/http_request/)
- [ESPHome Deep Sleep](https://esphome.io/components/deep_sleep/)
- [ESPHome 2026.10.2 image client](https://github.com/esphome/esphome/blob/2026.10.2/esphome/components/online_image/online_image.cpp)
- [ESPHome 2026.10.2 Inkplate grayscale mapping](https://github.com/esphome/esphome/blob/2026.10.2/esphome/components/inkplate/inkplate.cpp)

The shipped YAML is our own merge example for a user's existing working board
configuration. It retains OpenPaper-compatible JSON; measured voltage arrives in
a request header and is not a new JSON field. Physical Inkplate acceptance and
full firmware compilation remain distinct from server/browser/YAML validation.
Dynamic scripting remains a plan only; no QuickJS code or dependency is bundled.
