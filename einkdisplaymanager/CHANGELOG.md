# Changelog

## 0.6.5

- Fix dashboard and modal overflow caused by long device names, unbroken filenames and variant labels. Preserve access to dialog close buttons and wrap image-picker content.
- Keep navigation within narrow phone screens, place heading actions below their text on mobile, and allow form controls to shrink within their columns.
- Use concise visible resource ID labels while retaining full accessible names and select-to-copy behavior.
- Add a repeatable whole-dashboard layout audit at 320, 390, 768, 1024 and 1440 px in light/dark themes, including all display models, populated logs, saved variants, font uploads, script editors, render timings and image pickers.

## 0.6.4

- Add optional `screen.text()` font-metric alignment with `verticalMetrics: "font"`: stable ascent/descent frames for top/middle/bottom and fixed multiline spacing. Keep content-bounding-box alignment as the default.
- Add `verticalAlign: "baseline"` so y directly specifies the first baseline. Preserve explicit-palette coverage at the same position.
- Display render timing stages as stacked label/value rows without horizontal scrolling. Align font ID fields and Delete buttons consistently on desktop and mobile.
- Verify accented capitals, descenders, multiline text, uploaded/default fonts, legacy placement, and responsive controls.

## 0.6.3

- Measure elapsed render time with a monotonic clock for dynamic images and draft previews.
- Show the last attempt duration in the library and expandable per-target timings for script/startup, resources, drawing, source PNG, optimization/output, render worker/validation, and queue waiting. Show Home Assistant snapshot time separately.
- Retain total duration on failed attempts without replacing the last good image. Keep timing data in RAM only; existing resource limits and render scheduling stay unchanged.

## 0.6.2

- Show selectable readonly ID and device URL fields; hide clipboard buttons on insecure HTTP and retain keyboard copying.
- Load the code editor on demand instead of fetching its bundle in the regular media library.
- Reduce server-side pixel transport and native palette encoding work while preserving output bytes and all resource/isolation limits.
- Count library assignments in one pass and reuse cached hashes for unrotated dynamic image delivery.
- Add insecure-HTTP browser coverage and pixel transport/encoding parity tests.

## 0.6.1

- Fix excessive CPU use in dynamic previews, including Inkplate 6 at 800 × 600: reuse the optimizer’s precomputed RGB/LAB selector instead of rebuilding per-pixel palette objects and recalculating palette LAB values.
- Memoize at most 4096 exact byte-valued colors per palette/matching combination. Keep fractional ordered-dither inputs at their original precision and preserve first-color ties and reference RGB/LAB output.
- Keep script, optimizer, worker CPU/memory and wall-clock budgets unchanged. Report script and image-optimization CPU limits with readable messages instead of an internal QuickJS stack.
- Add reference-parity tests, the exact full-size Inkplate draft-preview regression, and native AMD64/ARM64 container coverage for LAB nearest-color rendering.

## 0.6.0

- Add Images, Dynamic images, and Fonts sections in Media Library with stable resource IDs and Copy ID controls.
- Add a local CodeMirror JavaScript editor with syntax highlighting, draft preview, saved target variants, Render now, status/error feedback, and independent generation intervals.
- Run QuickJS-NG and the trusted renderer in disposable, credential-free workers. Require verified OS restrictions, limit CPU/memory/output, and block filesystem, network, and process access.
- Support text/alignment/wrapping, lines, rectangles, circles, uploaded images and fonts, target dimensions/palettes, local render time, and allowlisted read-only HA snapshots. Enable the Core API permission for the trusted snapshot service only.
- Reuse the existing epdoptimize library on the server for per-target matching and dithering. Preserve explicit palette colors, native BMP/PNG contracts, orientation, and device mounting correction.
- Keep generated compositions, previews, target outputs, and render status in bounded RAM. Preserve the last good output on errors; return HTTP 503 before the first successful render and retain pending playback for retry.
- Preserve fixed device URLs and hash-based ETags/304. Background generation never advances queues or resets delivery health.
- Persist uploaded fonts safely, fall back to a bundled default for missing font IDs, and skip missing images with warnings. Mark metadata version 2 to prevent destructive cleanup by older builds.
- Add real browser, adversarial/runtime, RAM-only persistence and native AMD64/ARM64 Linux-container isolation checks.

## 0.5.4

- Add a global Activity battery decline period in seconds (0–2592000; default 0) after the existing image-fetch grace period. Support five-minute (300) and 24-hour (86400) declines.
- Reduce the simulated activity battery linearly from 100% to 0%; keep at least 1% until the period finishes and raise Image update overdue only at 0%. Show late during the decline.
- Recalculate existing estimates from their original deadlines when settings change, including raising previously empty indicators and clearing delayed alarms. Preserve timing across restarts.
- Apply watchdog-only setting changes without reconnecting MQTT or publishing artificial offline/online availability changes. Publish decline start, duration, and alarm timestamps as diagnostic attributes.
- Keep saved MQTT/watchdog values visible when navigating away from Settings and returning, without reloading the page.
- Keep new-frame estimates unknown until a successful image fetch or the full alarm deadline; inactive frames remain unknown. Successful HTTP 200/304 image delivery restores 100%; settings-only requests and voltage estimates remain independent.

## 0.5.3

- Group related select options with native optgroup labels: display models and registered devices, device families, palettes, dithering methods, original images and saved variants, and battery chemistries. Omit empty groups and preserve option values and defaults.
- Refresh Current playback queue during automatic device status polling, including cycle-boundary changes, while preserving settings drafts and the expanded queue panel.
- Explain that additions and base-order changes take effect at the next cycle; removals and disabled entries take effect immediately.
- Add regression coverage for expanding a running two-image queue to nine entries, reordering, shuffle, persisted state, and live browser updates.

## 0.5.2

- Remove pointer-hover switching from the original/variant comparison; Split, Original, and Variant buttons and keyboard controls select the view explicitly.
- Add Black and white alongside eight grayscale levels when preparing Inkplate 6 variants, with the existing dithering choices and automatic tone optimization.
- Add optional Invert tones for Inkplate variants, reversing final gray/black/white pixel values without another dithering pass.
- Save and restore palette/inversion recipes during editing and retain variant IDs and device assignments on overwrite.
- Validate black-and-white PNGs as opaque black/white pixels and keep output at native 800 × 600, including portrait composition and mounting correction.
- Clarify ESPHome greyscale: false setup and persistent variant storage. Original delivery continues to use eight grayscale levels.

## 0.5.1

- Fix next-connection and image-watchdog forecasts when a transfer crosses an anchor boundary: retain the sleep duration actually supplied in settings JSON instead of jumping to a later schedule slot.
- Preserve the known image deadline while a desired interval change has not yet reached the frame; a settings-only fetch still cannot reset image health.
- Return a validation error for oversized Inkplate PNG headers and extremely large battery voltage values instead of an internal server error.
- Fix sparse second-based anchor grids with narrow quiet windows so the next-slot search cannot make valid device/API reads fail.
- Enforce calendar-form anchor dates so values accepted by the API remain editable in HTML date inputs.
- Scope flasher and HTTPS-verification instructions to OpenPaper, provide a separate Inkplate setup link, and correct JSON/PNG/charging documentation.
- Add regression coverage and document final review evidence and outstanding hardware acceptance.

## 0.5.0

- Add optional per-device wall-clock anchors, IANA time zones, reference dates, and daily quiet hours, including overnight windows and daylight-saving changes.
- Calculate remaining sleep through the existing OpenPaper-compatible JSON timeout; return fresh JSON for active schedules so a cached countdown cannot be reused.
- Keep playback, expected image deadlines, and the MQTT watchdog aligned with permitted slots; skip missed slots without skipping playlist entries.
- Show last contact and next expected connection on device cards and publish a separate next-connection MQTT sensor.
- Replace fixed-height frame previews with complete images at the device aspect ratio. Compare matching original compositions and variants as diagonal halves, with hover, keyboard, and touch controls.
- Refine device forms, spacing, mobile controls, and image-list wrapping.
- Add optional model-independent battery profiles with series cell count, chemistry label, and calibrated empty/full per-cell voltages. Publish a separate estimated-charge sensor without changing the existing synthetic activity indicator or charger settings.
- Accept authenticated millivolt telemetry for every device model; current OpenPaper firmware still needs upstream support to send it.
- Pin timezone data for consistent scheduling on both container architectures.

## 0.4.0

- Add Inkplate 6 / ESPHome with native 800 × 600 PNG output, eight grayscale levels, portrait/landscape composition, model-specific variants, and exact 180° delivery correction.
- Fit normal JPEG/PNG/BMP originals into the Inkplate viewing area and quantize to grayscale; preserve sources and cache conversions within the existing bounded RAM budget.
- Include an ESPHome example for OpenPaper-compatible settings JSON, timed image fetching/deep sleep, and optional measured battery-voltage request headers.
- Show measured voltage and its timestamp in device status and publish separate MQTT sensors; retain the explicitly synthetic battery watchdog.
- Disable OpenPaper-only charging/motion/rotation controls for Inkplate and provide relevant setup help.
- Filter already assigned motifs from each device’s image picker, removing them immediately after adding and explaining empty results.
- Use a neutral MQTT broker example address consistent with the LAN example.
- Record dynamic-image scripting, independent refresh intervals, HA snapshots, fonts, RAM caching, and security requirements as future work in plan.md.

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
