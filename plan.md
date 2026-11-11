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

Status: experimental implementation **0.3.0**; locally tested, with Green,
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
  The owner's L is available for testing; Seven has software validation only.
- Keep native dimensions, mounting, palette, and encoder behavior in explicit
  model profiles shared by the backend and browser.
- Provide a shared **Media Library** for originals and explicitly saved variants.
- Provide **Devices**, where each registered frame has its own settings, ordered
  image list, playback state, stable image URL, and stable settings JSON URL.
- Let each device image-list entry select either an optimized variant or the
  unmodified original, subject to firmware compatibility checks.
- Play entries in order. Optionally shuffle the next queue **after a complete
  cycle**, before selecting its first entry. Never choose randomly per request.
- Advance only on an eligible image request after the configured interval.
  Sleeping or temporarily disconnected frames must not cause background skipping.
- Persist originals, saved variants, settings, credentials, and playback progress
  across add-on restarts, Home Assistant restarts, and backup/restore.

V1 excludes manufacturer-cloud accounts, automatic firmware flashing, remote
wake-up of sleeping frames, arbitrary dashboard screenshots, and a general photo
editor. A custom integration, native HA entities, MQTT discovery, reusable shared
playlists, and fixed wall-clock playback are possible later extensions, not v1
requirements. An add-on does not automatically provide HA entities.

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
- Select OpenPaper L or OpenPaper 7; keep existing model identities fixed.
- Fill its image list from the Media Library without copying originals.
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
| Optimized variant | Saved, validated model-native 4-bit BMP (L 1200 × 1600; Seven 800 × 480) with the correct device color codes | Add-on prepares output; frame does not re-dither this compatible output |
| Original | Original uploaded file, byte-for-byte, if supported | Firmware decodes, fits, and dithers as required by that input format |

Selecting an original must not force the user to optimize it first. Conversely,
upload support and original-delivery support are different: JPEG and PNG may both
be accepted by the library, but **PNG cannot be passed through to this firmware**.
Explain incompatibility at assignment time and offer creation of a compatible
variant; never silently convert while calling the result an unmodified original.
An already compatible original 4-bit BMP may also bypass on-device dithering.

According to the upstream firmware documentation, JPEG and uncompressed 24-/32-bit
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
until their effective content changes. Do not put changing request timestamps in
settings responses or use request time as a content validator.

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
| `timeout` | Desired wake interval in seconds, 60–2592000 |
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
