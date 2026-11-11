# Changelog

## 0.3.0

- Add OpenPaper 7 (7.3-inch Spectra 6, native 800 × 480 landscape) alongside OpenPaper L (native 1200 × 1600 portrait).
- Share one model catalog between backend and optimizer; derive native output, viewing dimensions, thumbnails, placeholders, and orientation controls from the selected model.
- Support portrait/landscape composition and exact 180° delivery correction on both models, retaining existing OpenPaper L recipes and outputs.
- Keep variants and pre-dithered original BMPs model-specific, including existing originals without new metadata; compatible JPEG/24-/32-bit BMP originals remain shareable.
- Version management thumbnails by content and mounting so browsers refresh previews after edits; fixed device image URLs stay unchanged.
- Preserve the model when duplicating devices and the target when saving/editing variants; include the correct model in MQTT discovery and firmware setup hints.
- Add model-contract and browser checks for OpenPaper 7 optimization, native encoding, portrait pixel equivalence, edited assignments, fixed-URL delivery, rotation, filtering, and mobile previews.

## 0.2.0

- Add MQTT broker settings with username/password, port, verified TLS, discovery prefix/retention, inline save feedback, and connection status.
- Publish ten Home Assistant entities per frame through one add-on MQTT connection, with stable device IDs, retained state, bridge birth/LWT availability, automatic reconnect, and discovery/state replay after Home Assistant restarts.
- Add an explicitly synthetic Estimated battery sensor: 100% after successful image delivery, 0% after the expected interval plus configurable grace. This is not a charge measurement; WiFi loss can produce the same signal.
- Keep new-frame estimates unknown until a successful fetch or missed deadline; paused, disabled, and empty image lists do not raise overdue alarms. Settings/browser/HEAD requests do not reset the image watchdog; a successful 304 does.
- Publish separate overdue, contact/delivery/expected timestamps, image-fetch status, selected image, enabled image count, interval, and transfer status entities.
- Store MQTT passwords privately without returning them to the UI or publishing them; keep typed form drafts during status polling.
- Persist owned-topic manifests and remove old retained configs/state after deletion, discovery/prefix changes, broker switches, disablement, or an offline restart.
- Add real Mosquitto broker checks for authentication, discovery, reconnect, cleanup, HA birth replay, activity estimation, and secret handling.

## 0.1.7

- Fix automatic preset resolution: load actual preset settings instead of spreading UI menu entries into processing options.
- Preserve the automatic S-curve, saturation, and other channels when a single manual slider is adjusted; keep manual contrast effective alongside the curve.
- Use the calibrated Spectra 6 palette for new recipes and offer Natural/Vivid automatic intent independently of the palette.
- Show the applied automatic image classification, preset, intent, and manual overrides after processing.
- Add six JavaScript regression checks and full-resolution browser comparisons proving that Auto changes delivered BMP pixels.
- Document offline-firmware battery access over BLE, the absence of battery telemetry on its image/settings HTTP requests, and a physical image-quality comparison workflow.

## 0.1.6

- Make Edit → Save changes replace the selected variant while preserving its ID and every device assignment; reject stale edits.
- Write validated replacement files before atomically publishing metadata and affected playback state, and wait for active transfers before replacement.
- Remove the dithering question-mark button and add selection-specific RGB/LAB matching descriptions.
- Keep success/error notices above open native dialogs and readable when scrolled.
- Add optimizer readiness checks, a startup retry, stage-specific progress/errors, timeouts, and cancellation when an editor closes; release decoded source bitmaps earlier.
- Document current upstream firmware's conditional image requests and 304 handling.

## 0.1.5

- Add per-device upside-down mounting correction for fixed-URL delivery, with previews showing the compensated mounted view in portrait or landscape.
- Rotate prepared 4-bit BMP pixel indices without re-dithering; preserve shared originals, variants, recipes, and image-list assignments.
- Support corrected compatible JPEG/BMP originals; JPEG correction requires an additional baseline encoding pass.
- Disable conflicting automatic sensor rotation, revalidate changed delivery bytes, and retain the current image for the first corrected fetch.
- Bound transformed-image caching in RAM and preserve disabled form controls after a failed save.

## 0.1.4

- Send stable ETag and Last-Modified image validators, preventing the offline firmware's empty-validator shortcut from skipping a new download and closing the connection.
- Support Last-Modified-only conditional image requests without freezing the next selected image.
- Show live per-device HTTP transfer stage, server-written bytes, and elapsed time, refreshed without replacing settings forms.
- Keep the latest 100 persistent device events, including settings checks, image transfers, interruptions, cache hits, and manual actions; omit credentials and raw request data.
- Distinguish closed connections, server timeouts, cancellations, unavailable files, and restart-interrupted transfers.
- Disable manual image selection during active transfers and report that HTTP completion does not confirm a physical panel refresh.

## 0.1.3

- Show Saving, success, and error feedback beside device settings; confirmation distinguishes saving in the add-on from application on the frame's next wake-up.
- Add editable image names in the Media Library while retaining original filenames, file contents, variants, and device assignments.
- Use chosen image names in the gallery, search/sort, device image lists, and image picker.

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
