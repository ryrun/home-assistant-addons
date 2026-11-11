# Changelog

## 0.1.2

- Add per-device mounting orientation and previews derived from native output.
- Show explicit conversion targets and dimensions; prepare variants for a registered device.
- Reopen saved recipes from originals and save new revisions without changing existing assignments.
- Add Stucki, Jarvis, Burkes, Sierra-3, ordered Bayer, and experimental blue-noise style dithering, with question-mark help.
- Offer the optimizer's calibrated Spectra 6 palettes and RGB/perceptual color matching for comparison on the real frame.
- Explain crops, multiple-device variants, physical reset-button refresh, JSON application, and browser-only CORS.
- Return all supported runtime JSON fields and invalidate validators when generated JSON content changes across updates.
- Extend backend/browser checks for orientation, immutable revisions, profile compatibility, all offered methods, and JSON caching.

## 0.1.1

- Prefill a suggested LAN base URL and detect the add-on's mapped host port through limited Supervisor endpoints.
- Explain how to change the exposed port in Home Assistant and keep it consistent with generated URLs.
- Add token-protected CORS/preflight support for the official offline-firmware Web UI; browser image checks do not advance playback.
- Add portrait/landscape composition and preview while retaining native, pre-dithered OpenPaper L output.
- Keep library DOM stable during polling, fix preview layout dimensions, and remove scrolling backdrop blur.
- Extend regression coverage for port discovery, CORS, scrolling, and exact landscape preview/output agreement.

## 0.1.0

- Initial experimental Home Assistant add-on for OpenPaper L offline firmware.
- Shared library with immutable originals, deduplication, and saved 4-bit BMP variants.
- Browser-worker automatic/manual optimization using epdoptimize 1.2.0.
- Independent device lists, settings JSON, fixed image URLs, and original/variant selection.
- Sequential, request-aware playback with optional cycle-boundary shuffle and persistent state.
- HA Ingress management, isolated token-protected LAN delivery, and focused automated/browser checks.
- Real-device, Green, container-build, and backup acceptance remain outstanding.
