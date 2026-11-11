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
Regenerate locks with pip-tools and verify Linux `aarch64`/`amd64` wheels before
release. Test dependencies are separately locked in `requirements-dev.txt`.
