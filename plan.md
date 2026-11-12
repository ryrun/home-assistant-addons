# Trakt MCP project and acceptance plan

Goal: a personal, read-only movie and series Trakt MCP server as a standalone Home Assistant add-on.
Codex/Zed handles analysis and recommendations. Existing add-ons remain unchanged.
Status: experimental version 0.3.7.

Setup uses the existing Home Assistant interface through configuration and logs,
or alternatively MCP tools. Home Assistant displays process status and logs.
A read-only statistics page is embedded through HA Ingress. There is no chatbot
or separate publicly exposed dashboard.

## Implemented and locally verified

- [x] Review the current official Trakt specification and Home Assistant configuration
- [x] Official Python MCP SDK 2.3.0, Streamable HTTP, and bearer authentication
- [x] Test MCP connection setup and repeated calls with the SDK client
- [x] Device flow through HA configuration/logs and MCP tools
- [x] Private persistent token file, atomic writes, and serialized refresh
- [x] Aggregated watched history, ratings, watchlist, search, and details
- [x] Series metadata, seasons/episodes, watched progress, up-next, scheduled episodes,
  personal ratings/favorites/watchlist, and filtered personal recommendations
- [x] Dated individual history, own lists and notes, hidden/dropped items, UTC calendars,
  collection, paused playback, and explicitly VIP-dependent precomputed statistics
- [x] Explicit genre preferences, streaming country, and favorite streaming sources
  from allowlisted Trakt settings without unrelated account data
- [x] Pagination using actual response headers and support for unpaginated endpoints
- [x] Popular, trending, and related candidates with filters and complete fresh exclusions
- [x] Movie credits including directors, related movies, and person filmographies
- [x] Explicit favorites and personal Trakt recommendations with fresh exclusions
- [x] Community and external movie ratings via Trakt only; direct third-party API integrations removed
- [x] Bounded persistent public SQLite cache with per-source TTLs, corruption recovery, status, and manual clearing
- [x] Account-bound RAM snapshots with activity validation, memory/age budgets, and safe invalidation
- [x] Compact preference tools and bounded credits
- [x] Optional CIDR filtering, opt-in MCP authorization tools, and runtime privilege drop
- [x] Bounded upstream responses, corrected OAuth errors and queued-request cooldowns
- [x] Synthetic 10,000-movie benchmark and local test/smoke helpers
- [x] Bounded GET retries, rate-limit cooldown, and API concurrency limits
- [x] Status tool, logs without arguments/results, and health check
- [x] Ingress-only statistics monitor with bounded metrics, no credentials/film data, and local assets
- [x] Browser checks at desktop/mobile widths and real TCP dual-listener/shutdown smoke test
- [x] Add-on configuration, container files, startup script, and watchdog
- [x] Pinned dependencies with hashes and a pinned multiarch base-image digest
- [x] Automated tests and installation/setup documentation

## External acceptance before 1.0.0

- [ ] Build and run images for linux/arm64 and linux/amd64
- [ ] Install the add-on from the published GitHub repository on Home Assistant Green
- [ ] Authorize a real Trakt account through HA configuration and logs
- [ ] Compare real data and pagination with a larger account
- [ ] Verify token refresh, restart persistence, Supervisor watchdog, and reauthorization
- [ ] Verify bearer headers, tool forwarding, and repeated calls in Zed with Codex
- [ ] Verify actual HA Ingress routing, access controls, sidebar, and statistics on Green
- [ ] Assess recommendation quality using real ratings, favorites, and watchlist data
- [ ] Prepare release 1.0.0 only after acceptance tests pass

Docker and Home Assistant Green are unavailable in the local development
environment. No real Trakt credentials have been provided, and no changes have
been published. The definition of done for version 1 has therefore not been met.

Future work: additional read-only metadata and multiple accounts. Write tools remain excluded.

---

# E-Ink Display Manager — development and acceptance plan

Status: experimental implementation **0.6.0**; locally tested, with Green,
container-build, physical-device, and Supervisor backup acceptance still pending.
Project directory: `einkdisplaymanager/`.

This section adapts the supplied **OpenPaper Manager for Home Assistant — Development
Plan** to the decisions agreed during planning. The product is a standalone Home
Assistant **add-on**, with a management interface through HA Ingress, rather than
a custom integration. The existing Trakt plan above remains independent.
All maintained plan text, UI labels, messages, documentation, and code comments
for this add-on must be in **English**, consistent with the other add-ons.

## 1. Scope and agreed product behavior

- Run locally on Home Assistant Green without the manufacturer's cloud.
- Manage multiple frames with **OpenPaper L** (13.3-inch, native 1200 × 1600 portrait)
  and **OpenPaper 7** (7.3-inch, native 800 × 480 landscape), both Spectra 6.
  Add **Inkplate 6** (ESPHome, native 800 × 600 landscape, eight grayscale levels)
  for normal uploaded images. The owner has an L and an Inkplate 6; Seven has
  software validation only. Physical Inkplate acceptance remains pending.
- Keep native dimensions, mounting, palette, and encoder behavior in explicit
  model profiles shared by the backend and browser.
- Provide a shared **Media Library** for originals and explicitly saved variants.
- Provide **Devices**, where each registered frame has its own settings, ordered
  image list, playback state, stable image URL, and stable settings JSON URL.
- Let each device image-list entry select either an optimized variant or the
  original source, subject to model-specific compatibility. OpenPaper sends compatible
  originals unchanged; Inkplate explicitly fits and quantizes the delivery copy.
- Play entries in order. Optionally shuffle the next queue **after a complete
  cycle**, before selecting its first entry. Never choose randomly per request.
- Advance only on an eligible image request after the configured interval.
  Sleeping or temporarily disconnected frames must not cause background skipping.
- Persist originals, saved variants, settings, credentials, and playback progress
  across add-on restarts, Home Assistant restarts, and backup/restore.

V1 excludes manufacturer-cloud accounts, automatic firmware flashing, remote
wake-up of sleeping frames, arbitrary dashboard screenshots, and a general photo
editor. A custom integration and reusable shared playlists remain outside the
current scope. Optional wall-clock anchors and quiet hours are implemented since 0.5.0. Optional MQTT discovery is implemented
since 0.2.0; an add-on does not automatically provide HA entities on its own.

## 2. Interface and user workflow

### Media Library

- Responsive multi-column gallery with thumbnails, title/filename, dimensions,
  source format, variants, and device usage counts; usable on desktop and mobile.
- Multi-file upload with progress, validation failures, and duplicate feedback.
- Search, sort, select, and perform clearly scoped bulk operations.
- Store one immutable original per SHA-256 content hash. Identical filenames do
  not imply identical assets and must never silently overwrite an existing asset.
- Open an asset to compare its original, optimized output, and approximate display
  simulation. Label simulated physical colors as an approximation.
- Offer **Optimize**, automatic optimization, brightness, contrast, saturation,
  color/palette presets, dithering, rotation, contain/cover, and crop/focal point.
- Save changes to a variant under the same ID, retaining its device assignments.
  Create separate named variants for independent outputs; keep originals unchanged.
- Show which devices and image-list entries reference each original or variant.
- Require confirmation for deletion. Block deletion of referenced originals or
  variants until the user explicitly removes/replaces those references.

### Devices

- Add, rename, configure, disable, duplicate configuration, and remove a device.
- Select OpenPaper L, OpenPaper 7, or Inkplate 6; keep existing model identities fixed.
- Fill its image list from the Media Library without copying originals. Hide
  already assigned motifs in this device’s picker, including alternate variants.
- Each entry shows its selected source/variant, output mode, enabled state, and
  position. Offer drag-and-drop and accessible move-up/move-down controls.
- Show the manually arranged order separately from the effective playback queue
  when shuffle-after-cycle is enabled.
- Show the selected image, last successfully served image, list position, cycle,
  last image/settings request, latest error, and next eligible change time.
- Mark the active selection in the device image list. Do not claim it is physically
  displayed: completed HTTP delivery is not a display acknowledgement.
- Provide pause/resume, next, previous, and choose-image actions. These change the
  server-side selection; the frame receives it on its next fetch.
- Expose desired interval, shuffle-after-cycle, firmware-supported device settings,
  and copyable image/settings URLs. Distinguish desired settings from confirmed
  application on the device, which may be unknown.
- Device removal must not remove shared originals or saved variants.

### Settings and diagnostics

Show LAN base URL/port, endpoint and credential management, storage usage,
conversion jobs/failures, firmware profile/version, and sanitized request history.
Do not expose a separate playlist-management area as a prerequisite for adding
images to a device; image lists belong directly to devices in v1.

## 3. Image delivery modes and optimization

| Per-entry mode | Served bytes | Processing responsibility |
|---|---|---|
| OpenPaper variant | Saved, validated model-native 4-bit BMP (L 1200 × 1600; Seven 800 × 480) with the correct device color codes | Add-on prepares output; frame does not re-dither this compatible output |
| OpenPaper original | Original uploaded file, byte-for-byte, if supported | Firmware decodes, fits, and dithers as required by that input format |
| Inkplate variant | Validated 800 × 600 PNG in eight gray levels or black and white, optionally inverted | Add-on prepares crop/tones/dither; ESPHome decodes and draws without resizing |
| Inkplate original source | Explicitly fitted/quantized PNG delivery copy | Add-on fits the original into the chosen mounting; stored source stays unchanged |

For OpenPaper, selecting an original must not force the user to optimize it first. Conversely,
upload support and original-delivery support are different: JPEG and PNG may both
be accepted by the library, but **PNG cannot be passed through to this firmware**.
Explain incompatibility at assignment time and offer creation of a compatible
variant; never silently convert while calling the result an unmodified original.
An already compatible original 4-bit BMP may also bypass on-device dithering.

According to the OpenPaper upstream firmware documentation, JPEG and uncompressed 24-/32-bit
BMP are dithered on-device. A 4-bit BMP at another size is also converted. Progressive
JPEG is decoded at reduced resolution, optimized Huffman tables may be rejected,
and compressed/8-bit BMP is unsupported. Validate these cases and show actionable
feedback. Original mode retains original metadata, including EXIF orientation;
do not promise the firmware reproduces a browser's orientation/color handling.

The upstream Web UI already implements the desired optimization workflow:

- `GeneratePicture.js` imports **epdoptimize** for dithering, palettes, processing
  presets, and automatic suggestions. `web/package.json` currently declares
  `epdoptimize` with range `^1.2.0`; pin the resolved version used by our build.
- It offers manual adjustments and profile-aware automatic tone/color processing,
  including brightness, contrast, saturation, and display color simulation.
- Its `app.js` builds a 4-bit BMP with the proper header, palette, and pixel payload.
  HTTP BMP output is not the headerless raw pixel payload used for BLE uploads.
- Device pixel codes are black `0`, blue `1`, green `2`, red `3`, yellow `5`, and
  white `6`. Match encoding, nibble order, row orientation, and palette handling
  to the pinned firmware and compare with Web UI exports on real hardware.

Evaluate reuse of epdoptimize and the Web UI's approach rather than inventing a
different default optimization pipeline. Before copying code or profiles, verify
their actual licenses, library/dependency licenses, attribution, and redistribution
terms; a package metadata license is not proof that every upstream file is covered.
Record incorporated components in `THIRD_PARTY_NOTICES.md` and an add-on source notice.

The conversion architecture remains a technical spike: compare browser Web Worker
processing with an add-on worker that can reproduce stored recipes. Choose one
authoritative full-resolution output; previews must reflect its settings. Never
dither an already reduced preview and treat it as the final full-resolution file.

Preserve originals; apply EXIF orientation, deliberate color-space handling,
transparency background, resize/crop, then color optimization/dithering when creating
a variant. Strip unnecessary metadata from generated delivery files. Record all
parameters, device profile, algorithm/dependency versions, and output hash.
Do not reprocess files during a frame's fetch. Bound worker concurrency, decoded
pixel counts, memory, queue length, and disk use for Home Assistant Green.
Saved variants are durable user assets; only unreferenced generated caches and
temporary files may be garbage-collected automatically.

## 4. Playback state and request semantics

- Start with the first enabled entry in the manually arranged order.
- Keep an independent cursor, effective queue, cycle number, pause state, selected
  representation, and persisted deadline for every device, even with shared media.
- After a successful initial delivery, keep that selection stable for the interval.
  On the first eligible fetch after the deadline, select **one** next entry; do not
  catch up through every elapsed interval after an outage.
- Reset the next deadline relative to this delivery, not to a stale wall-clock
  schedule. Retries and concurrent requests within the interval reuse the selection.
- Serialize device selection changes and persist them transactionally. Keep a
  pending selection stable after interrupted transfers; do not consume another
  entry just because a retry arrived. Finalize the pending delivery once the
  server can determine completion; no physical render guarantee is possible.
- Image previews, library downloads, settings JSON, HEAD, and invalid requests must
  never advance device playback. Serve previews through management routes.
- Select the due representation before evaluating its cache validators: an old
  `If-None-Match` must not keep a different next image stuck at `304` forever.
  A `304` for unchanged output must not independently trigger another advancement.
- Define identical-byte entries as separate list entries; represent them with
  distinct entry IDs. Test cache behavior without confusing content identity
  with queue position or claiming a new physical refresh occurred.
- Pausing retains the current selection. Manual next/previous/choose reset the
  deadline and must not cause an immediate automatic second step on the next fetch.
- Sequential mode repeats the same order at the cycle boundary. Shuffle mode
  completes the initial ordered queue, then generates a new queue containing every
  enabled entry exactly once. Do not mutate the manual base order.
- Avoid repeating the preceding last image as the new first image when another
  distinct eligible image exists. Cover zero, one, and two-entry lists explicitly.
- Empty lists use a pre-generated, profile-compatible placeholder. If conversion
  is unfinished or fails, retain the last valid output and show the failure.
- List edits must preserve the current image where possible. Exact rules for
  additions, manual reorder, disabling the current entry, and history navigation
  during a shuffled cycle are documented in `einkdisplaymanager/DOCS.md` (section 11).

## 5. Firmware contract and fixed device URLs

Each device receives stable URLs on a dedicated add-on **LAN device listener**.
Illustrative paths, not implemented routes or a committed port:

```text
http://<ha-lan-host>:<device-port>/d/<id>/image?k=<device-token>
http://<ha-lan-host>:<device-port>/d/<id>/settings.json?k=<device-token>
```

The **image URL remains fixed** as the image, variant, or output format changes.
No filename extension is needed. The firmware identifies JPEG (`FF D8`) and BMP
(`BM`) from file bytes in `src/main.cpp`, not from the URL extension. Send the
matching `Content-Type`, accurate length, and content-specific `ETag`; update
validators when actual served bytes change. Keep settings `Last-Modified` stable
until their effective content changes in default interval mode. Optional schedules
return a changing timeout countdown with no-store and unconditional JSON 200; image
validators remain content-based. Request timestamps are not added as JSON fields.

Firmware URLs are limited to **128 characters**. Validate both complete generated
URLs, including scheme, hostname, port, path, encoded IDs, and credentials. Use
short paths/IDs without weakening token entropy. Do not derive frame URLs from
the Ingress prefix, browser hostname, or an external HA URL. Allow an explicit
stable LAN base URL; verify DNS/IP reachability from the frame's network.

The frame loads remote settings before its image on each wake-up. Provide only
supported settings, not the manager's image list/shuffle metadata:

| JSON field | Meaning / documented constraint |
|---|---|
| `downloadUrl` | Fixed image endpoint for this device |
| `timeout` | Desired interval or remaining sleep to the next permitted target, 60–2592000 seconds |
| `motionWakeup` | Optional movement-triggered wake-up |
| `autoRotation` | Optional sensor-based rotation; coordinate with generated image orientation |
| `chargerMode` | NiMH charging setting; never enable automatically or infer battery chemistry |
| `httpAuthUser`, `httpAuthPassword` | Optional Basic Auth for image fetches; not a general settings-endpoint auth guarantee |

Firmware also supports `X-OpenPaper-Sleep-Seconds` on image responses, but only in
the range **60–86400**, unlike the longer JSON timeout range. Establish precedence
and persistence on hardware before using this header; do not silently clamp a
multi-day user interval to one day. Device poll time and server selection deadline
must remain consistent, including early movement-triggered requests.

The documentation permits HTTP and HTTPS but says HTTPS certificates are **not
verified** by this firmware. Do not claim authenticated TLS protection. Firmware
error retries and low-battery update suppression affect contact timing; “not
recently seen” is more accurate than claiming a sleeping frame is offline.

Onboarding uses the upstream Web UI to install/configure offline firmware, WiFi,
and the device's settings URL. Explain certificate backup before firmware changes
and that BLE-upload mode has no timed wake-up until URL-download mode is restored.
The add-on does not need to implement a flasher or modify the firmware for v1.

## 6. Add-on architecture and security

- Package under `einkdisplaymanager/` with add-on configuration/schema, container
  build, startup, health check/watchdog, English README/DOCS/CHANGELOG, backend,
  frontend assets, and focused tests. Target `aarch64` and `amd64`; Green is the
  primary acceptance platform. Pin runtime dependencies and base images.
- Serve the management UI and write API only through HA Ingress. Use relative
  asset/API URLs and validate trusted Ingress provenance. Restrict the panel to
  administrators initially; never trust spoofable user/proxy headers from the LAN.
- Use a separate device listener exposing only authenticated device image/settings
  GET/HEAD routes. It must expose no upload, browse-library, delete, or admin routes.
  Firmware fetches cannot depend on a browser's HA login or Ingress session.
- Use strong random, revocable credentials per frame and constant-time verification;
  prefer token hashes at rest. Plan token issuance/rotation so generated settings
  can include a valid image URL without pretending a hash can recover its token.
  If recovery requires storing a secret, document and protect that storage explicitly.
- Confirm token-in-URL operation for both endpoints on hardware; Basic Auth for
  image downloads alone does not protect the settings JSON. Avoid including WiFi
  passwords or unrelated credentials in device JSON.
- Apply a configurable LAN allowlist using the actual trusted client address. A
  private IP or `.local` hostname does not itself enforce local-only access.
  Document firewall/VLAN reachability and prevent reverse-proxy bypasses.
- Protect state-changing management requests against CSRF and validate origin and
  request schemas. Device GETs may perform only the documented authenticated
  playback bookkeeping; they cannot edit configuration or invoke management actions.
- Enforce upload byte/pixel/type limits using decoded data, defend against image
  decompression bombs, sanitize filenames, prevent path traversal, escape UI text,
  and bound HTTP bodies, request concurrency, and diagnostic retention.
- Redact URL tokens, credentials, and sensitive query strings from logs/diagnostics.
  Explain that HTTP and screenshots/history/proxy logs can expose capability URLs.
- Use local frontend assets and no runtime cloud/CDN dependency. Request no host
  networking, privileged mode, hardware access, or HA API permissions without need.

## 7. Persistence, ownership, and lifecycle

Proposed metadata storage: SQLite with migrations and transactional per-device
updates; originals and generated files live separately under persistent `/data`.
Validate this choice during the spike. Do not use HA `.storage` as if this were a
custom integration, and do not store image blobs in HA state attributes.

| Record | Essential data |
|---|---|
| Media asset | Immutable ID, SHA-256, original path/type/dimensions, title, creation time |
| Saved variant | Immutable ID, asset ID, recipe, profile/converter version, output path/hash, status |
| Device | ID, name, type/profile, firmware version, desired settings, interval, shuffle/pause |
| Device image-list entry | Stable entry ID, device ID, asset ID, original/variant mode, variant ID, order, enabled |
| Playback state | Device ID, queue of entry IDs, cursor, cycle, selected/pending representation, deadline, delivery status |
| Device access | Device ID, credential verification/issuance data, rotation metadata |
| Request diagnostics | Bounded image/settings timestamps, response status, error, last completed representation |

Publish files atomically after validation; recover from failed uploads, full disk,
interrupted conversion, and power loss. Keep selected outputs available until a
replacement is ready. Coordinate deletion with references and in-flight transfers.
Include metadata, originals, saved variants, and credentials in add-on backups;
test consistent SQLite/file snapshots and restore. Document whether credentials
are preserved or deliberately rotated and how frames reconnect afterward.

## 8. Delivery milestones

### Phase 0 — firmware and platform acceptance

Source inspection and local implementation are complete enough for an experimental
build; the hardware/platform exit criteria below are still required before release.

- [ ] Pin an upstream firmware revision and record the tested device version.
- [ ] Use the real OpenPaper L to fetch settings and a manually selected image
  from a protected LAN endpoint, including extensionless URLs and the 128-character limit.
- [ ] Verify unmodified supported originals versus Web-UI-compatible 4-bit BMP,
  JPEG restrictions, palette codes, orientation, validators, and interval precedence.
- [ ] Verify Ingress isolation, device listener routing, add-on data/backup paths,
  target architecture builds, and Green resource budgets.
- [x] Resolve optimizer reuse/licensing and authoritative conversion runtime.

Exit: real hardware fetches correct output/settings without manufacturer cloud;
license and platform feasibility are established.

### Phase 1 — library and one device

- [x] Add-on packaging, schema-versioned persistence, Ingress UI, and endpoint isolation
  implemented; actual container/Ingress acceptance remains in Phase 0/4.
- [x] Shared upload library, thumbnails, deduplication, editable saved variants with stable assignments,
  optimization controls/preview, and per-entry original/variant selection.
- [x] Register an OpenPaper L profile, configure JSON, populate its image list,
  and expose fixed URLs with manual next/previous and served-image status; tested
  using HTTP clients and Chromium, not a physical frame.

Exit: upload, optionally optimize, assign, and display both supported delivery modes.

### Phase 2 — deterministic playback

- [x] Sequential order, enable/disable, reorder, pause/resume, and cycle-boundary shuffle.
- [x] Request-aware deadlines, pending-transfer retries, concurrency, cache validation,
  and persisted queue state with clear behavior for edits and manual actions.

Exit: no unintended multi-step advancement from retries, restarts, or long absences.

### Phase 3 — multiple devices and usability

- [x] Independent device settings, lists, queues, credentials, and diagnostics.
- [x] Shared asset/variant usage, safe deletion, search/filter, bulk operations,
  responsive gallery, accessible controls, and configuration duplication.

Exit: device independence is verified; a second device can be simulated when only
one real L is available, and simulated coverage is not described as hardware acceptance.

### Phase 4 — hardening and release

- [ ] Network/authentication checks, bounded resource use, failure recovery,
  backup/restore/migrations, English onboarding, and third-party notices.
- [ ] Build/install on Green, exercise actual Ingress routing, and compare output
  quality and battery-related polling behavior on the available OpenPaper L.
- [ ] Publish through the add-on repository only after acceptance; no HACS packaging.

## 9. Acceptance checklist

This checklist includes physical/platform outcomes. Locally passing tests do not
close hardware-dependent items. See implementation evidence in section 11.

- [x] Original bytes remain unchanged; saved edits never mutate existing assignments.
- [x] Duplicate uploads share one original; devices share references, not copied files.
- [ ] Original mode accepts only tested firmware-compatible inputs and explains failures.
- [ ] Optimized BMP has exact dimensions/pixel codes and avoids another dithering pass.
- [ ] The fixed, extensionless image URL survives image and JPEG/BMP format changes;
  correct headers/validators prevent stale content and unnecessary display refreshes.
- [x] Every device has independent settings JSON, image list, token, and queue.
- [ ] `A, B, C` runs in order; shuffle occurs only after completion, with no avoidable
  boundary repeat. Empty, single-entry, duplicate-content, and two-entry cases work.
- [x] Repeated/concurrent GETs, HEAD, previews, JSON requests, aborted transfers,
  conditional requests, and restarts do not accidentally consume multiple entries.
- [ ] A long-sleeping frame receives the next entry, without missed-interval catch-up.
- [ ] Manual actions, mid-cycle edits, pause/resume, deletion, and failed conversions
  have documented behavior and retain a valid output where possible.
- [x] Invalid tokens/non-allowlisted clients fail; the device port cannot reach admin
  routes, and direct or spoofed requests cannot bypass Ingress restrictions.
- [ ] Both endpoint URLs fit the firmware limit and remain reachable from the frame VLAN.
- [ ] Saved variants, originals, credentials, and progress survive restart and restore.
- [ ] Upload limits, corrupt images, disk-full errors, and bounded workers keep Green usable.
- [x] UI distinguishes selected, served, and physically displayed (unknown without ACK).
- [x] Maintained UI strings, errors, documentation, and plan additions are in English.

## 10. Sources and research baseline

Required upstream references:

- [OpenPaper offline firmware — GitHub](https://github.com/paperlesspaper/paperlesspaper-firmware-offline)
- [OpenPaper offline firmware — Web UI and flasher](https://paperlesspaper.github.io/paperlesspaper-firmware-offline/)

Implementation references inspected on 2026-11-11 (upstream `main` is mutable;
pin a commit during Phase 0 and recheck against the installed firmware):

- [Firmware README: formats, HTTP, remote JSON, onboarding and certificates](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/README.md)
- [Image optimization, profiles, simulation, and raw output generation](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/web/src/GeneratePicture.js)
- [Web UI BMP encoder and optimization controls](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/web/src/app.js)
- [Web UI dependencies, including epdoptimize](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/web/package.json)
- [Firmware decoding and file-signature detection](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/src/main.cpp)
- [Home Assistant: Ingress interface and trust boundary](https://contributors.home-assistant.io/apps/guides/ingress/)
- [Home Assistant: add-on/app configuration](https://contributors.home-assistant.io/apps/reference/configuration/)

Documentation/source inspection is not hardware verification. The flasher page
itself was not accessible through the web reader; its behavior was researched
through the linked upstream README and Web UI source.

## 11. Implementation decisions and current validation

The product decisions were confirmed using the grill-me discussion. Technical
choices made for the initial implementation are recorded here and in the English
`einkdisplaymanager/DOCS.md`:

1. **Optimizer:** unmodified, vendored `epdoptimize@1.2.0` (Apache-2.0), including
   the bundled RgbQuant MIT notice. Browser workers process full-resolution output;
   that exact output is validated/stored by the backend. No firmware/Web UI source
   or calibration profile was copied. Provenance is in `einkdisplaymanager/UPSTREAM.md`.
2. **Editing:** before the first delivery, new entries join the initial ordered
   queue. During playback, additions/reorder apply next cycle, invalid entries are
   removed immediately, and removing the current entry selects the first remaining
   entry. Previous stops at the current queue's start. Explicit manual choices may
   deliberately repeat/skip entries in that cycle.
3. **HTTP/security:** internal Ingress port 8099; mapped device port 8098; explicit
   configurable LAN origin; independent 192-bit device tokens. Tokens are stored
   recoverably in private persistent data to generate settings URLs, rather than
   claiming hash-only recovery. Image and settings endpoints share each device's
   credential. JSON timeout is used; sleep-header precedence remains a hardware
   follow-up and the add-on does not currently emit that header.
4. **State:** pending selection is persisted before sending bytes, finalized on
   server-observed completion, and retried after interruption. Per-device locks
   serialize selection. Exactly-once physical display remains unprovable without ACK.
5. **Storage/resources:** SQLite schema version 1, immutable files under `/data`,
   20 MiB uploads, 32 MP decoded images, two image-validation workers, four concurrent
   device transfers with a 60-second delivery timeout, and a configurable disk
   budget. Cold backups are requested to stop the service during Supervisor backups.

Local evidence: **32 passing Python tests** cover image/profile validation, HTTP/auth,
queues, persistence, retries, concurrency, and device independence. Chromium smoke
checks exercise upload, full-resolution optimization, saved variants, device setup,
settings, original/BMP delivery through one URL, and desktop/mobile layouts.
The manual contrast, rotated crop, grayscale, and Atkinson worker path is also
exercised, including validation of the saved BMP's actual black/white pixel codes.
Hash-verified runtime wheels were downloaded successfully for Python 3.13 on both
Linux ARM64 and AMD64 using the pinned Debian image's supported manylinux baseline.
Run instructions are in the add-on docs. Source compatibility baseline:
`64d47dfd4c57bb053d36813d212b4fe69aa04e8f` of the offline firmware.

Still required externally: Linux container builds, actual HA Ingress installation,
Green memory/CPU behavior, Supervisor backup/restore, and physical OpenPaper L
image/caching/interval acceptance. The implementation is experimental. Version
0.1.0 was pushed to the repository; the 0.1.1 follow-up adds LAN/port suggestions,
flasher CORS, a stable editor layout, and landscape composition with native BMP
delivery. Version 0.1.2 adds mounting-aware device previews, explicit conversion
targets, editable recipes saved as new revisions, dithering/palette choices with
help, physical refresh instructions, and content-based settings validators.
Version 0.1.3 adds inline device-save feedback and editable image display names,
retaining original filenames and existing device/variant references.
Version 0.1.4 addresses the firmware's empty Last-Modified comparison, adds stable
image cache validators, live HTTP progress, and the latest 100 durable events per
device. A real stalled-transfer browser test verifies progress without discarding
unsaved settings. TCP completion still cannot confirm decoding or panel refresh.
No stable release or physical-device validation is implied.

Version 0.1.5 adds per-device 180° delivery correction for upside-down mounting,
independent of portrait/landscape composition. Configure it once and apply it to
subsequent deliveries without editing shared variants. Native 4-bit BMP pixels
are rotated exactly without re-dithering; compatible JPEG originals require
another baseline encoding pass. Previews show the compensated mounted view.
Sensor rotation is disabled while correction is enabled, validators follow actual
delivery bytes, and the first corrected request retains the current image.
Transformed-image caching is RAM-only and bounded to eight entries / 32 MiB.
Automated coverage includes exact pixels, original formats, shared-media
immutability, device independence, conditional fetches, and browser form behavior.

Version 0.1.6 makes Edit overwrite a variant under the same ID, retaining every
device assignment. Validated replacement files precede an atomic metadata/playback
commit; active deliveries finish first, stale editors are rejected, and the current
changed image remains selected for its next delivery. Content files stay immutable;
shared files remain referenced. This supersedes the previous UI's new-revision-only
editing behavior. Inline selection help replaces the dithering question-mark button
and also explains RGB/LAB matching. Notifications remain visible over native dialogs.
Worker startup now uses readiness, one retry, bounded waits, stage-specific progress
and errors, and cancellation on editor close. Automated checks cover invalid worker
starts, image decode failures, retained assignments, storage/validation failure,
concurrent transfers, and modal notification visibility. Current upstream firmware
supports image and JSON 304 handling; installed builds still require version checks.

Version 0.1.7 corrects automatic optimization preset lookup and preserves automatic
curves/channels when an individual manual adjustment is made. New recipes start
with the calibrated Spectra 6 palette; Natural/Vivid intent is independent of that
palette. Applied automatic settings are shown and stored, with real full-resolution
Auto on/off pixel comparisons and six JavaScript regression tests. Saved variants
require deliberate recomputation/save to adopt changes. Physical color quality is
still evaluated on the actual panel under controlled lighting, not inferred from
native RGB previews or different bitmap hashes. Current upstream 1.4.1 identifies
additional gamut-aware diffusion changes; vendored 1.2.0 stays pinned in this fix.
Battery research: offline firmware reports millivolts, USB, and charging over BLE
system info, but not on normal HTTP image/settings fetches. Future automatic battery
reporting requires firmware telemetry (e.g. request headers); store voltage and
measurement time and avoid unsupported chemistry-independent percentages.

Version 0.2.0 adds optional MQTT broker credentials/port/TLS settings and one
add-on connection publishing Home Assistant discovery/state for each registered
frame. Ten entities cover the explicit Estimated battery activity proxy (100/0%),
image overdue problem, fetch state, contact/delivery/expected timestamps, selected
image, enabled image count, interval, and transfer status. A successful image GET
or 304 restores 100%; interval plus configurable grace (default 120 s) without
successful image delivery yields 0%. New/inactive/paused/empty-list rules prevent
claiming measured charge. Settings/browser/HEAD traffic cannot restore the estimate.
The bridge has stable identifiers, retained state, discovery retention/prefix,
birth/LWT, HA birth replay, bounded reconnect, and durable owned-topic cleanup
including offline deletion and previous broker cleanup. MQTT passwords remain in
private persistent data and never enter public APIs or MQTT payloads. Real local
Mosquitto tests include authentication and reconnect/cleanup; browser checks cover
secret handling, retained form drafts, responsive UI, and activity display. Physical
Home Assistant integration acceptance remains pending. Actual measured battery
voltage reporting still requires the separately proposed firmware HTTP telemetry.

Version 0.3.0 adds OpenPaper 7 (7.3-inch Spectra 6) with native 800 × 480 landscape
transport alongside L's 1200 × 1600 portrait contract. A shared explicit catalog
feeds backend validation, browser output, model labels, orientation dimensions,
preview sizing, blank images, and MQTT metadata. Seven portrait composition is
480 × 800 and rotates into native raster without re-dithering. Per-device 180°
correction preserves exact 4-bit pixel indices on both models. Model-specific
variants/prepared originals cannot cross-assign, including legacy validated BMP
metadata; general compatible originals can be shared. Device duplication retains
its model; editing a Seven variant retains assignments and target settings.
Software validation now covers both native formats, defaults, previews, JSON,
original compatibility, MQTT model names, and the full Seven browser workflow.
Sources are recorded in UPSTREAM.md; physical Seven acceptance remains pending.

Management thumbnail URLs include content/mounting revisions to refresh stale
browser images after edits. Device image/settings URLs remain fixed.


Version 0.4.0 adds Inkplate 6 for uploaded images: full-resolution eight-level PNG
variants, target-aware editor and previews, portrait/landscape composition, exact
180° correction, and original-mode server fit/quantization. Originals stay immutable;
conversion cache shares the existing 8-entry / 32 MiB RAM bound. The ESPHome merge
example retains the existing board configuration and uses the OpenPaper JSON
schema (`downloadUrl`, `timeout` in seconds), then fetches PNG and sleeps. A voltage
request header on authenticated device GETs records measured millivolts and time,
with device UI and separate MQTT voltage/timestamp sensors. This does not infer
charge or reset the activity watchdog. OpenPaper-only hardware options are disabled
for Inkplate. The image picker hides all already assigned asset IDs for that device,
including disabled entries and alternate variants, immediately after each addition.
Other devices retain independent choices; removal makes the motif available again.

## 12. Dynamic images — agreed design and implemented MVP (0.6.0)

This section records the design confirmed on 2026-11-12 and implemented in 0.6.0.
The implementation adds QuickJS-NG, font uploads, read-only HA snapshots, the editor,
and RAM-only target outputs. Earlier static-only releases did not enable HA API
access or install a script runtime. Physical Green/Supervisor and panel acceptance
remain separate from automated Linux container and browser verification.

### Confirmed first-version scope (2026-11-12)

- Keep the UI in English. Separate **Images**, **Dynamic images**, and **Fonts**
  within Media Library. Author scripts in the add-on with syntax highlighting,
  saving, preview, useful validation/runtime errors, and a **Render now** action.
- Use **JavaScript interpreted by QuickJS**. Jinja2 layout templates were compared
  and not selected: direct drawing commands are preferred. QuickJS-NG 0.18.0.1 is
  the implemented runtime, with verified isolation on AMD64/ARM64 Linux containers
  and macOS development.
- Provide text, lines, rectangles, circles, and images from the existing library.
  Expose the target variant's pixel dimensions as `screen.width` and
  `screen.height`; run composition for each required model/orientation target.
  The display profile defines its actual palette, not just a color count. Support
  target-specific color, grayscale, and monochrome preparation without resizing
  an already dithered output. Use opaque RGB strings for conversion or `palette.black` and other available
  named entries for exact ink; exact selections survive automatic optimization.
- Reuse existing uploaded-image IDs; expose stable image and font IDs with
  **Copy ID** controls. Renaming retains IDs. `screen.image(imageId, options)`
  references an uploaded original for composition before target optimization.
  A missing image ID draws nothing and produces a nonfatal editor warning; do
  not block deletion just because a script references that uploaded image.
- Upload fonts through Media Library and address them by stable ID in text
  options. Persist uploaded font files. A missing font ID uses a bundled default
  font and a nonfatal editor warning rather than failing the render. Validate
  uploads and the default font's license; scripts never receive filesystem paths.
- Read HA values with helpers such as `ha.state(entityId)` and
  `ha.number(entityId)` from a preloaded read-only snapshot. Supply render-time
  clock data in the configured time zone for conditions such as morning/evening
  greetings. No live networking or HA credentials are exposed to user code.
- Give each dynamic item its own generation interval, independent of device
  fetch intervals. **Render now** uses the same isolated pipeline and resource
  budgets as scheduled renders. Saved recipes define its target variants.
- Persist source code, names, intervals, recipes, uploaded originals, and fonts.
  Keep generated compositions, encoded variants, previews, and delivery
  transformations in bounded **RAM-only** caches. Reuse/replace cache entries;
  do not create persistent render histories, image files, or per-render database
  blobs. Background rendering must not introduce continuous metadata writes.
- Keep the last successfully rendered output on script failure or unavailable
  HA data. Show the error and last-success timestamp separately from device
  transfer status. Restart loses generated images and schedules regeneration.
  Until a target has a successful output, return a temporary **HTTP 503** for its
  image request; never replace the physical display with a placeholder/error
  image. Preserve the pending queue entry so the frame can retry it.
- Execute without script-accessible file, process, or network facilities, with
  enforced resource limits and demonstrable OS isolation. The existing security
  requirements and physical/platform acceptance gates below remain mandatory.

### Product behavior and independent refresh intervals

- A **Dynamic image** is a first-class Media Library item beside uploaded images.
  Users write and edit its script directly in the add-on UI, save it, preview it,
  see validation/runtime errors, and assign it through ordinary device image lists.
  No manual file editing or visual layout builder is required.
- Each dynamic image has its **own generation interval**, independent of all device
  fetch intervals. For example, render a sensor image every minute while an Inkplate
  fetches every 15 minutes and an OpenPaper fetches hourly. Device GETs consume the
  latest completed cache; they do not trigger rendering or a fresh HA request.
- A bounded background scheduler reads selected HA entities, executes the script,
  renders/optimizes the image, then atomically replaces its RAM cache. Coalesce
  overlapping runs per item; skip missed ticks instead of starting a catch-up storm.
- Generated rasters and encoded outputs live **in RAM only**, with byte/count and
  concurrency budgets. Persist scripts, names, refresh intervals, target recipes,
  selected entity IDs, asset/font registrations, and version metadata. Do not store
  generated image blobs in HA states or write a file on every render.
- Use explicit model/orientation targets. Share compatible cached targets among
  devices, rather than duplicating a render for every device. Include script,
  snapshot, target, font/asset versions, and optimizer configuration in cache keys.
  Invalidate changes without ever resizing an already dithered output.
- Ordinary fixed device image URLs, ordered lists, shuffle-after-cycle, pause,
  mounted previews, 180° correction, authenticated access, and HTTP completion
  tracking continue to work. Background rendering does not advance playlists,
  count as a device contact, or reset the image-delivery watchdog.
- ETags represent **actual delivered bytes**, not render timestamps. An unchanged
  raster can keep its validator and return 304 to a client retaining the matching
  body. Dynamic frame-fetch timing remains independent of the generation schedule.
- Keep the last good output when HA is unavailable, a sensor is unknown, a script
  times out, or rendering fails. Show render/snapshot times and stale/error status
  separately from frame-transfer errors. Return temporary HTTP 503 when there is
  no previous good output. Restart regenerates outputs because the cache is
  intentionally volatile; it must not send empty files or a replacement error image.

### Script language and drawing API

- Selected language: **JavaScript interpreted by QuickJS**; the implementation
  uses the embedded QuickJS-NG 0.18.0.1 Python wrapper.
  No direct Python execution, arbitrary shell commands, or on-device business logic.
  Normal arithmetic, strings, arrays, conditions, loops, and helper functions allow
  programmable layouts without assembling widgets by hand.
- Expose a small documented drawing API such as `screen.text`, `screen.line`,
  `screen.rectangle`, `screen.circle`, and `screen.image`, with explicit positions, alignment,
  colors, and registered font IDs. Provide dimensions and a fixed render-time value
  as input. Define supported syntax/API versions before storing production scripts.
- Read-only helpers such as `ha.state(entityId)` and `ha.number(entityId)` operate
  solely on a **preloaded JSON snapshot** of explicitly selected entities. Include
  unavailable/unknown behavior, typed fallbacks, selected attributes, timestamps,
  units, and staleness. No synchronous network calls from a script.
- A script returns bounded JSON drawing commands. Validate the complete command
  schema, own properties, types, finite coordinates, colors, string lengths, command
  count, and registered references before trusted Pillow rendering. Reject unknown
  fields/prototypes rather than merging arbitrary user objects into host options.
  Never pass Python objects, credentials, file handles, or unrestricted callbacks
  into the JS context. The renderer is trusted code, not another user interpreter.
- Use real font rendering and text measurement, including glyph fallback, wrapping,
  clipping, Unicode, alignment, and predictable missing-glyph handling. Upload fonts
  through Media Library and register them by stable ID; no manual shared-directory
  setup is required. Bound file sizes/counts, reject path traversal, and handle
  font licensing. Scripts never choose file paths. Font changes invalidate relevant
  render caches. Missing font IDs use a bundled default font with a warning.
- Static-image optimization runs in a browser worker. Dynamic rendering uses
  Pillow and the same vendored epdoptimize 1.2.0 in a separate trusted QuickJS
  context with an in-memory ImageData/canvas adapter. It requires no open browser.
  Native model/geometry and exact palette tests pass; Green resource use and
  physical Spectra 6/grayscale image quality remain acceptance checks. Avoid an
  unwanted second dithering pass on the frame.

### Home Assistant data and credential boundary

- Version 0.6.0 sets `homeassistant_api: true` for its trusted snapshot service;
  `hassio_api` stays false. Prior releases had both permissions disabled. Supervisor
  network defaults used for the LAN suggestion do not imply HA entity access.
- Candidate transport: authenticated Core proxy `http://supervisor/core/api`, reading
  `/api/states/<entity_id>` (or a bounded read-only subscription/cache after validation).
  The Supervisor token must remain only in the trusted parent data-fetching service.
- Home Assistant API access via this token has broad administrator-level power;
  an application-side read-only entity allowlist is **not a platform-enforced narrow
  token scope**. No script gets a token, API client, service-call method, event writer,
  MQTT client, or live connection. Do not expose HA commands through the drawing API.
- Cache and batch selected sensor reads, bound timeouts/response sizes, and avoid
  querying every HA entity for every image. Share snapshots where useful. Handle
  HA restart, unavailable entities, no permission, and network loss explicitly.

### Security requirements and feasibility gates

- The embedded QuickJS core has no inherent shell/system API. `std`, `os`, file,
  process, and network helpers belong to optional host bindings/CLI libraries.
  Do **not** run the `qjs` command-line environment, register `quickjs-libc`, expose
  `std`/`os`, add `fetch`/sockets/files, install a module loader, or bridge Python
  object attributes. No external imports, package installation, or arbitrary URLs.
- Removing global names alone is not a security sandbox. Core JS built-ins still
  exist; the decisive boundary is no privileged host capability plus enforced
  limits and OS isolation. Prototype tricks must never recover a hidden host object.
- Execute in an isolated worker process with enforceable CPU/wall-clock, memory,
  stack, string/array/output, drawing, and image-dimension limits. Kill and recreate
  a worker on timeout or crash. Bound queue length and workers to keep Green usable.
- Establish a demonstrable OS boundary: no HA/MQTT credentials or inherited secret
  environment, no network access, no writable application/storage paths, and access
  only to explicitly allowed read-only inputs if any. Verify which unprivileged
  user/seccomp/process controls actually work inside the HA add-on container. A
  same-user child process alone does not protect secrets from a native engine bug.
  Do not enable script execution until this isolation is demonstrated.
- Accept source text only, never user-supplied QuickJS bytecode. A native runtime
  vulnerability remains possible; do not claim the solution is hack-proof. Pin the
  runtime, track upstream fixes, and include adversarial resource/escape tests.
- Research baseline: the original `PetterS/quickjs` Python wrapper was archived in
  January 2026. The implementation selects `genotrance/quickjs-ng` 0.18.0.1, with
  hash-locked dependencies and successful AMD64/ARM64 container builds. The
  QuickJS-NG security policy does not promise private
  security reports/CVEs; untrusted bytecode hardening is outside its support scope.
- Errors must be useful in the editor but contain no raw tokens, environment,
  filesystem paths, sensor snapshots beyond the authorized values, or stack dumps
  leaking host details. Protect script edits via the existing admin Ingress/CSRF
  boundary; rendering does not add another LAN management API.

### Device protocol decision

- Retain the **OpenPaper-compatible Settings JSON**, then fetch its `downloadUrl`.
  `timeout` controls the next device fetch/sleep interval in seconds. The dynamic
  image generation interval is an add-on scheduler setting and is not sent as the
  device sleep interval. No custom interval response header is needed.
- Inkplate/ESPHome uses standard `http_request` JSON parsing and `online_image` PNG
  downloads. Telemetry travels **device → server in request headers**, e.g.
  `X-Display-Battery-Millivolts`, while JSON is server → device configuration.
  Voltage/time are separate from the synthetic 100/0% activity sensor. Do not
  derive a generic battery percentage without chemistry/load/calibration evidence.
- The static support implements this Inkplate request header already. The current
  OpenPaper offline firmware sends no battery telemetry on normal HTTP GETs; it
  exposes voltage/USB/charging over BLE setup information. HTTP reporting for those
  frames still requires an upstream/custom firmware change. The feature request
  text was prepared for the owner; posting was not performed by the add-on.
- Research alternative: ESPHome `online_image` supports templated outgoing headers,
  but does not expose arbitrary collected response headers in normal YAML. The
  generic `http_request` supports `collect_headers` but does not hand a decoded image
  directly to `online_image`. A one-transfer image-plus-sleep-header design would
  therefore need an external component. The agreed JSON design avoids that need.
- Deep sleep clears ordinary RAM. A client may use 304 only when it retains the
  corresponding JSON/image body; do not persist validators alone across reboots.
  Keep local bounded interval defaults and preserve the physical image on errors.

### Proposed implementation and acceptance sequence

- [x] Implement bounded read-only snapshot fetching with no token/client exposure;
      test selected Core API requests and script snapshot helpers.
- [ ] Verify Core proxy access on the actual installed Home Assistant system.
- [x] Prove QuickJS-NG embedding, limits, and default-deny OS isolation inside the
      actual unprivileged Linux image on AMD64 and ARM64 (native CI builds).
- [ ] Verify the deployed container under the user's Supervisor configuration.
- [x] Implement versioned drawing commands, font registration, trusted renderer,
      target-specific output, and server optimization with bounded resources.
- [x] Add Dynamic image editor, validation, preview, errors, selected entity list,
      own refresh interval, and persisted configuration through existing Ingress.
- [x] Add RAM scheduler/cache with atomic swap, last-good output, restart/first-render
      behavior, deduplication, invalidation, and separate render/device diagnostics.
- [x] Integrate dynamic items into existing device lists without changing fixed URLs
      or causing sensor renders to advance playback or reset watchdog health.
- [ ] Test infinite loops/recursion, huge allocations/outputs, malformed commands,
      prototype manipulation, attempted module/file/network/process access, worker
      crashes, unavailable HA, stale snapshots, font faults, concurrent fetches,
      304 behavior, restart, and RAM pressure on Green.
- [ ] Verify real OpenPaper L and Inkplate 6 image quality, grayscale levels,
      independently timed updates, cold boots, deep sleep, telemetry, and battery
      consumption. Simulation does not replace hardware/platform acceptance.

Research sources checked 2026-11-11:

- [QuickJS-NG standard library — optional CLI/host bindings](https://quickjs-ng.github.io/quickjs/stdlib/)
- [QuickJS-NG embedding and limits](https://quickjs-ng.github.io/quickjs/developer-guide/intro/)
- [QuickJS-NG security policy](https://github.com/quickjs-ng/quickjs/security)
- [Maintained Python QuickJS-NG wrapper](https://github.com/genotrance/quickjs-ng)
- [Home Assistant API proxy and permissions](https://developers.home-assistant.io/docs/apps/communication/)
- [Home Assistant REST states API](https://developers.home-assistant.io/docs/api/rest/)
- [Inkplate 6 hardware](https://docs.soldered.com/inkplate/6/overview/)
- [ESPHome image download](https://esphome.io/components/image/online_image/)
- [ESPHome HTTP headers and JSON](https://esphome.io/components/http_request/)
- [ESPHome deep sleep](https://esphome.io/components/deep_sleep/)

Static Inkplate local evidence: 72 passing Python tests and 14 passing JavaScript
tests; real Chromium worker/UI tests include an eight-level ramp, portrait PNG
pixel equivalence, edited assignments, measured-voltage display, fixed-URL
correction, per-device motif filtering, and mobile layout. Live stalled-transfer
verification still passes. Physical Inkplate/Green acceptance and a complete
ESPHome firmware build are pending.


## 13. Optional device scheduling, comparison, and battery profiles (0.5.0)

Implemented independently of the planned dynamic-image renderer:

- Per-device interval plus optional local anchor time, reference date, and IANA
  zone. Daily 03:00 stays at local 03:00 through DST; six-hour slots are 03/09/15/21.
  Uneven and multi-day intervals retain a continuous grid. Missing local slots are
  skipped and repeated autumn slots use their first occurrence. Pinned timezone
  data is included in both architecture builds.
- Independent daily quiet hours, including overnight. Anchored slots in quiet
  hours are skipped; relative targets are moved to the end of the window. Invalid
  grids that suppress every anchor are rejected. Automatic playback does not
  advance during quiet hours or catch up by consuming skipped entries. First setup,
  pending retries, and explicit manual selections can still deliver output.
- Existing JSON schema with a dynamic timeout, bounded by the firmware's 60-second
  minimum and 30-day maximum. Schedule-enabled JSON is always fresh 200/no-store,
  including conditional requests; default interval JSON retains its 304 behavior.
  Image ETags remain unchanged. No new response sleep header is introduced.
- Separate stored expected contact and successful-image target timestamps. Cards
  show last contact/next expected connection; the MQTT image watchdog uses the next
  permitted image target plus grace, and JSON-only contacts do not restore it.
  Settings affect a sleeping frame at its next JSON check, not immediately. Timed
  physical refresh has firmware/transfer/panel latency and needs real acceptance.
- Complete, aspect-correct device previews without artificial cropping. Original
  composition follows the saved rotation/crop/focus and mounting before color
  optimization. The diagonal Original/Variant comparison supports temporary hover
  expansion, explicit buttons, keyboard, and touch. UI spacing, form groups, mobile
  wrapping, and forecast timestamps were reviewed together.
- Optional generic battery configuration: cells in series, descriptive chemistry,
  and user-calibrated empty/full voltage per cell. Divide reported total pack volts
  by series count, interpolate linearly, and clamp to 0–100%. No reading means
  unknown; old readings retain their timestamp. Chemistry alone does not select a
  calibrated discharge curve. This is an approximate voltage estimate, especially
  limited for flat NiMH/LiFePO4 curves, and never changes charging.
- Keep measured voltage, voltage-derived charge, and the synthetic 100/0% activity
  signal distinct in the UI and MQTT. Profiles work for all current/future devices;
  receive authenticated generic/OpenPaper millivolt headers for any model. Current
  OpenPaper firmware still does not send them; the Inkplate example does.

Local coverage: 120 Python tests, including schedule/DST/health/JSON/voltage tests
and source-composition checks for all three models and both mountings; browser
checks exercise hover/keyboard/touch, dimensions, form drafts/errors, forecasts,
and responsive layouts. No physical timing, charge-curve, Green installation, or
container-build acceptance is implied. The dynamic-image plan in section 12 stays
future work and must inherit these device schedules without coupling its own
generation intervals to device polls.


## 14. Final code and documentation review (0.5.1)

- Fixed a reproducible anchor-boundary forecast error: JSON issued shortly before
  a slot may tell a frame to sleep 60 seconds, while the HTTP image transfer ends
  just after the slot. Keep that issued sleep for the next-connection prediction
  and image watchdog instead of recomputing a six-hour future slot. The playlist
  deadline remains separate; settings-only contacts cannot restore image health.
  Persist the last supplied timeout and retain known expectations until an image
  completes. Desired settings do not prove the frame has applied them.
- Sparse second-based anchor grids with narrow quiet windows use a bounded
  phase lookup instead of exhausting an iterative search and blocking device/API
  reads. The 64-entry clock-phase cache is bounded to about 5.3 MiB worst-case.
- Oversized PNG headers now produce validation errors without storing a variant;
  extremely large numeric battery endpoints no longer overflow float validation.
  Calendar-form anchor dates stay compatible with the UI date input.
- Documentation and global setup help now distinguish OpenPaper flasher/TLS
  behavior from ESPHome, explicitly describe validated PNG output and false-by-
  default charging, and clarify timing predictions versus physical refreshes.
- Local evidence: 127 Python tests, 14 JavaScript tests, real Chromium workflows,
  and interrupted-transfer verification. Independent schedule comparisons cover
  343 valid combinations around European and half-hour DST transitions.
- Full ESPHome firmware compilation and physical frame/Green/container acceptance
  remain outstanding. The temporary ESPHome package download timed out during
  review; no firmware build success is claimed. Dynamic images remain planned.


## 15. Explicit comparisons and Inkplate tone variants (0.5.2)

- Remove hover-driven image switching. Keep the diagonal split and explicit
  Split / Original / Variant buttons, keyboard shortcuts, and touch operation.
- Inkplate 6 variant preparation supports the eight-level palette and a strict
  black/white palette. Keep existing tone controls and dithering; optional Invert
  tones reverses the final quantized levels exactly without a second dither pass.
- Persist palette and inversion with the variant recipe; Edit restores both and
  Save changes retains its ID and assignments. Native PNG dimensions, portrait
  transport rotation, previews, and per-device 180° correction remain compatible.
- ESPHome greyscale: false uses prepared black-and-white variants. Its image
  decoder can remain GRAYSCALE because these PNGs contain only 0/255. Original
  mode continues to fit sources to eight levels; do not describe it as monochrome.
- Stored variants remain finished files under persistent /data/media. Do not move
  the library into RAM; only existing delivery transformations use the bounded
  cache. Planned dynamic images keep their separate RAM-only generation design.
- Software evidence: 128 Python and 14 JavaScript tests plus real Chromium worker
  and UI checks for gray/BW pixel sets, exact inversion, saved edit flags, native
  portrait pixels, unchanged assignments, and stable comparison on pointer moves.
  Physical grayscale/monochrome rendering and full ESPHome build remain pending.


## 16. Grouped selections and live playback queue (0.5.3)

- Use native optgroup categories for models versus registered target devices,
  device families, color palettes, dithering algorithms, originals versus saved
  variants, and primary versus rechargeable battery chemistries. Keep flat lists
  for simple choices, omit empty groups, and preserve defaults and option values.
- Update Current playback queue from automatic status polling when its contents
  change; preserve settings drafts, the expanded panel, and the base-list editor.
- Keep existing playback policy: finish the active queue, then adopt additions and
  the updated manual order (or shuffle). Removed/disabled entries leave immediately.
- Cover expansion from two to nine entries, reordering at either position,
  shuffle, restored persisted state, retries, and full-cycle completion. Browser
  coverage verifies grouped defaults and queue changes without manual refresh.
- Verification: 132 Python tests, 14 JavaScript tests, and the full Chromium
  smoke test passed, including the live two-to-nine queue transition and grouped
  selection defaults. Physical-device behavior remains a separate acceptance step.


## 17. Gradual activity battery decline (0.5.4)

- Add global battery_decay_seconds to the persisted MQTT/watchdog settings:
  integer seconds from 0 to 2592000, default 0. Existing image-fetch tolerance
  stays separate; support 300 seconds for five minutes and 86400 for 24 hours.
- After expected image time plus grace, decrease the synthetic activity estimate
  linearly from 100 to 0. Keep at least 1 until the full period ends. Report late
  during decline; turn the overdue problem on only at zero. Measured voltage and
  calibrated voltage-based charge stay separate.
- Compute from the original persisted delivery/watch deadline on every read; do
  not store a decrementing percentage or reset the clock on settings changes.
  Increasing the duration can restore a formerly zero estimate and clear an
  alarm. Restarting preserves the same result. New frames stay unknown through
  their first decline; paused/disabled/empty frames do not raise an alarm.
- Wake MQTT publication immediately after settings changes without reconnecting
  for watchdog-only changes. Publish the duration, decline start, and final
  alarm deadline as diagnostic attributes. UI and MQTT use the same calculation.
- Test linear five-minute/24-hour progress, zero/end boundaries, rounding without
  premature zero, retroactive increases/decreases, persistence, validation, real
  retained MQTT updates without availability changes, HTTP 304 recovery, and the
  browser setting's default, validation, persistence, and draft preservation.
- Verification: 152 Python tests, 14 JavaScript tests, and the complete Chromium
  smoke test passed. MQTT integration used a temporary real Mosquitto broker;
  changing decline duration updated retained percentages and problem status
  without reconnecting or changing availability.


## 18. Dynamic image implementation and validation (0.6.0)

- Implement Images / Dynamic images / Fonts library sections, stable resource IDs,
  local CodeMirror JavaScript editing, draft preview, Save image & target, Render
  now, per-target recipes, and independent generation intervals/time zones.
- Execute source in fresh bounded QuickJS-NG workers; pass only selected immutable
  HA snapshot data and a frozen clock. Read literal helper-call IDs automatically
  and support an explicit list for computed IDs. All host credentials stay in the
  trusted parent. Core API permission is enabled intentionally, with the platform's
  broad scope documented rather than represented as a narrowly scoped token.
- Render text/shapes/uploaded originals/fonts with trusted Pillow inside the same
  OS boundary. Optimize in a separate QuickJS context using existing epdoptimize
  code and presets; preserve named palette ink, native BMP/PNG geometry, grayscale
  inversion, and mounting correction. Bound all commands, resources and queues.
- Persist definitions and uploaded resources only. Atomically replace complete
  target batches in a 128 MiB RAM cache; rendering does not write files, blobs,
  hashes or histories. Preserve last-good output and return HTTP 503 before first
  success. Queue state stays pending for retry and real-byte ETags govern 304.
- Implement missing-image skip and missing-font fallback warnings, font-aware
  orphan cleanup, and metadata version 2 to prevent destructive old-version cleanup.
- Native CI container checks have passed on AMD64 and ARM64, including syscall
  restrictions, unprivileged UID/GID 10002, read-only filesystem, no network, and
  native encoded output for all three device profiles. macOS Seatbelt probes and
  real Chromium UI/device-delivery checks also pass. Final suite counts are
  recorded after the release checks. Installed HA/physical panel acceptance remains
  separate; no full ESPHome firmware build or hardware-quality success is claimed.
