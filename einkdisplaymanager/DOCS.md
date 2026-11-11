# E-Ink Display Manager documentation

## Installation and first connection

1. Install **E-Ink Display Manager** from this Home Assistant add-on repository.
   The add-on currently builds locally for `aarch64` or `amd64`; it does not depend
   on a separately published container image.
2. Keep device port `8098/tcp` enabled and start the add-on. Port `8099` is internal
   management traffic for HA Ingress and must not be mapped to the host.
3. Open **Web UI**. In **Settings**, check and save the prefilled LAN base URL, for
   example `http://homeassistant.local:8098` or `http://192.168.1.10:8098`.
   Use the HA host's fixed LAN address and the mapped
   device port. Do not use a changing Ingress URL or the external HA URL.
4. Upload images in **Media Library**. Open an image, adjust it, update the
   full-resolution preview, and save a variant if desired.
5. In **Devices**, add an OpenPaper L. Open **Add images** and select an original
   or a saved variant for each assignment. Repeat images are allowed as separate
   entries; drag entries or use their arrow buttons to arrange the base order.
6. Copy the device's **Settings JSON URL**. In the upstream
   [Web UI & flasher](https://paperlesspaper.github.io/paperlesspaper-firmware-offline/),
   configure offline firmware, WiFi, and this Settings-JSON-URL on the frame.
   The add-on's JSON includes the fixed image URL and supported settings.
7. Wake the frame and verify that its request timestamps and last served image
   update. Test the output physically before leaving the device unattended.

**Save settings** displays progress and confirmation beside the button. “Settings
saved” confirms storage in the add-on; the frame applies them on its next wake-up.
Save failures remain visible beside the form, with the entered values retained.

## Live transfer status and device log

Each device page shows **Transfer status** and a **Device log**, updated every two
seconds while the page is visible. Polling updates only status fields, previews,
and log rows; it does not replace the settings form or discard unsaved edits.

Transfer states distinguish preparation, HTTP sending, completion, `304` unchanged,
and interruption/failure. Progress counts bytes written by the server, not bytes
acknowledged by the frame's application. At 100%, the frame may still be receiving,
writing flash, decoding, or refreshing the panel. There is no local acknowledgement
for those on-device stages, so the UI cannot confirm a physical refresh.

Manual Next/Previous/Show-next and token changes are blocked during an active image
transfer. Wait for sending to finish before resetting the physical frame, and
allow the panel refresh to finish afterward. A hardware reset can interrupt WiFi;
the add-on cannot prevent or observe the physical button press itself.

The latest **100 events per device** are retained across restarts, newest first in
the UI. Entries include timestamps, HTTP result, server-written bytes, duration,
and a bounded event/error category. They record authenticated frame requests,
settings checks, manual selections, and configuration changes. Browser previews
do not count as frame downloads. URLs, tokens, credentials, raw headers, and raw
exception strings are not recorded. Only the authenticated management interface
can read the log; device endpoints cannot access it. No older history can be
reconstructed for errors that occurred before this feature was installed.

An unfinished transfer detected after an add-on restart is marked interrupted,
with the prior byte count explicitly unknown. Progress is kept in memory while
streaming, with durable start/end summaries rather than a disk write for every
network chunk. Logs are automatically removed when the device is removed.

### Interpreting an interrupted transfer

- `connection_closed`: the peer closed the connection before server-side HTTP
  completion. A frame reset, WiFi failure, or firmware-side cancellation is possible;
  the server cannot determine which occurred from a closed socket alone.
- `timeout`: server delivery exceeded its 60-second deadline.
- `cancelled` / `restart`: the request or add-on stopped during preparation/sending.
- `file_unavailable`: the selected media file could not be read; restore it or
  deliberately choose another image.

One firmware compatibility trap is addressed in 0.1.4: with an existing flash image
and an empty cached validator, its code can compare an empty response Last-Modified
with that empty cached value even when an ETag is present. It may then skip the
body and close an HTTP 200 response. Images now include both nonempty Last-Modified
and ETag validators. Last-Modified changes monotonically when served bytes change,
so two images created in the same second cannot freeze legacy conditional fetches.
This is a concrete possible cause of the previous generic interruption message,
not proof of what happened on a particular device. See the
[upstream download path](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/src/main.cpp).

If the issue recurs, check the new event's category, duration, and byte count. No
new frame events suggest checking the LAN URL, mapped port, token, WiFi, allowlist,
and whether the frame is awake in URL-download mode. A prepared OpenPaper L BMP is
960,118 bytes and avoids on-device dithering; large originals need more transfer
and flash resources. CORS does not affect the frame's own HTTP client.

Before changing firmware, follow the upstream instructions to back up device
certificates; erasing their partition prevents returning to cloud firmware without
a backup/replacement. Flashing remains an external manual step. Bluetooth-upload
mode has no timed wake-up; use URL-download mode for this add-on's slideshow.

## Add-on configuration

| Option | Default | Purpose |
|---|---|---|
| `lan_base_url` | Empty | Optional fixed override of the URL entered in the UI; include the device port |
| `storage_limit_mb` | `1024` | File-storage ceiling in MiB, range 64–32768 |
| `allowed_networks` | Loopback and private IPv4/ULA ranges | CIDRs permitted on the device listener; restrict to your frame's network |

Changing the base URL changes both device URLs: reconfigure frames with their new
settings URL. Complete URLs are checked against the firmware's 128-character
limit; use a shorter hostname if needed. Never shorten tokens to make URLs fit.

The suggestion uses a private IPv4/`.local` host from the browser when available,
otherwise the Supervisor host name or `homeassistant.local`. At startup the add-on
reads only `/info` and `/addons/self/info`, without additional Supervisor privileges,
to discover its mapped host port (default 8098). Discovery failure falls back to a
clearly labeled default; existing saved URLs are never silently replaced.

**The device port is configurable.** In Home Assistant, open the add-on's
**Configuration → Network**, change the host port mapped to `8098/tcp`, and restart
the add-on. For example, if mapped to 8129, save `http://<ha-lan-host>:8129` in the
manager afterward. Editing a URL alone does not change the host's port mapping.
The container still listens internally on 8098. Do not expose management port 8099.

The frame must be able to reach this host/port, including across VLANs. Configure
firewall rules accordingly. Avoid internet port forwarding. The allowlist checks
the actual TCP peer address, not untrusted forwarding headers. A reverse proxy
can obscure the original peer, so direct LAN delivery is the supported setup.

Management is admin-only through HA Ingress. The device port exposes only
token-authenticated image and settings GET/HEAD endpoints. It has no library,
upload, or management API. Production management accepts only the Supervisor's
Ingress peer; proxy/user headers alone cannot grant access. Assets, previews, and
other downloads do not advance playback.

### Web UI JSON preview and CORS

The device endpoints allow read-only browser requests from the official flasher
origin, `https://paperlesspaper.github.io`, including OPTIONS preflight requests.
Tokens and the network allowlist still apply. Management APIs receive no cross-origin
permission. Flasher image previews do not consume a queue entry or count as a
completed frame delivery. A cache-busting `nocache` query parameter is supported.

If **Prüfen** reports “Failed to fetch”:

1. Confirm that the copied URL opens in the same browser, including its port/token.
2. In Chrome/Edge, allow local network access for the Web UI site when prompted,
   or in the browser's site permissions. CORS alone cannot grant this permission.
3. Some browsers block HTTPS-page requests to local HTTP endpoints. Use a browser
   supporting permission-gated local requests or a trusted HTTPS LAN endpoint.
4. A failed browser preview does not mean the frame cannot load the JSON. Save
   the settings URL to the frame through the Web UI's device settings; the frame's
   own HTTP client is not subject to browser CORS/mixed-content restrictions.

Do not expose the device listener to the internet to make the preview work.
See [Chrome local-network access guidance](https://developer.chrome.com/blog/local-network-access).

Both per-device URLs contain the same random 192-bit capability token. Keep URLs
private. Tokens are deliberately stored recoverably in the private SQLite data
file so the management UI can show them and JSON can include the image URL;
they are not falsely described as hash-only storage. The process uses a private
umask and drops root privileges at startup. Protect backups because they include
tokens. Rotation invalidates old URLs and requires updating the frame's settings
URL. No URL/credential-bearing request access logs are emitted.

HTTP does not encrypt images or tokens. This firmware's HTTPS client does not
verify certificates, so HTTPS alone is not authenticated protection. WiFi
credentials are configured on the frame, not stored by this add-on. Charger mode
requires an explicit NiMH confirmation and is omitted until configured.

## Original files and saved variants

The library accepts single-frame JPEG, PNG, and BMP images up to 20 MiB and
32 million decoded pixels. Corrupt files and unsupported/animated images are
rejected. Files are identified by content hash; matching filenames never replace
an existing original. The current limits are 2000 originals, 4000 variants,
32 devices, and 1000 entries per device.

Open an image and change **Image name**, then select **Save name**. This display
name replaces the filename in the gallery, search/sort, device lists, and image
picker. The original filename is shown separately and retained for downloads.
Renaming does not alter image bytes, saved variants, queue entries, or device URLs.
Uploading the same original again keeps its chosen display name.

**Original** means the exact uploaded bytes. Compatible baseline RGB/grayscale
JPEGs and uncompressed 24-/32-bit BMPs can be fitted/dithered on the frame. JPEG
headers and Huffman lookup constraints are checked. Progressive JPEGs, unsupported
Huffman tables, CMYK JPEGs, PNGs, and arbitrary indexed BMPs require a variant.
Some optimized-Huffman JPEGs are compatible; others are rejected. Original mode
does not promise browser-style EXIF orientation or color management on the frame.

**Variant** means a separately saved, immutable 1200 × 1600 top-down, uncompressed
4-bit BMP with valid Spectra 6 pixel codes. The firmware can take its direct-output
path instead of dithering again. A compatible original in that same format is
also accepted. The fixed image URL needs no extension: firmware detects the file
signature, and the server sends the corresponding content type and content ETag.

The editor's **Display orientation** chooses portrait (1200 × 1600) or landscape
(1600 × 1200) composition independently of source-image rotation. Landscape output
is rotated counter-clockwise into the native 1200 × 1600 transport BMP, without
another dithering pass; its saved thumbnail and editor preview remain landscape.
The preview corresponds to mounting the frame clockwise from its native portrait
position. Check physical orientation and sensor rotation on the device. This
retains the firmware's direct 4-bit BMP path instead of sending a differently sized
bitmap that the frame would convert again. Existing portrait variants are unchanged.

Set **Mounting orientation** in the device settings as well. This controls the
device card, frame preview, and list thumbnails. Prepared previews are derived
from native file pixels in that mounting orientation; original-mode previews only
approximate the firmware's fitting and color behavior. Changing a device's mounting
does not recrop or overwrite its assigned variants. It is distinct from the
firmware's sensor-driven `autoRotation` and is not an unsupported JSON field.

### Targets and crop recipes

Choose **Target display** before setting the crop: either the supported model or
a registered device, which supplies its profile and mounting orientation. A saved
variant records the model, native and viewing dimensions, orientation, normalized
crop position, and processing settings. The same original can have multiple
variants for different aspect ratios and models. Matching devices can share one
variant; incompatible model/resolution assignments are rejected rather than
silently scaling already dithered pixels. Only OpenPaper L is offered today;
other display sizes require separate tested profiles and encoders.

**Contain** preserves the whole image with white margins. **Cover** fills the
selected viewing area while cropping edges; horizontal/vertical crop positions
move the visible area within those edges. Neither mode stretches the source.

### Editing a saved variant

Use **Edit** beside a saved variant. This restores its orientation, crop, palette,
algorithm, and adjustment controls, then processes the unchanged original again.
**Save new revision** creates a separate variant linked to its parent. Existing
assignments continue to use the previous variant until deliberately changed.
The recipe is self-contained, so deleting an unused parent does not prevent
editing a child. **Prepare for this device** in the device image picker starts
with the appropriate target and mounting.

Optimization uses the vendored `epdoptimize@1.2.0` in an isolated browser worker,
not the HA backend's event loop. A current browser with OffscreenCanvas support
is needed. The server normalizes editor input orientation, embedded ICC profiles
to sRGB, and transparency, and
validates every finished BMP before saving. Automatic and manual settings are
recorded in the variant's recipe. Manual brightness/contrast/saturation adjustments
override automatic tone adjustment when nonzero. Vivid and black/white presets,
Floyd–Steinberg/Atkinson and the methods below, contain/cover with crop position,
and rotation are available. Updating the preview processes full output resolution; its saved
bytes are the authoritative result, not an enlarged reduced-resolution preview.
Physical e-paper colors depend on the display and lighting; the preview is not a
calibrated physical display simulation.

Adding or saving a variant never silently changes existing device assignments.
Create new assignments or remove/re-add an entry to choose a different variant.
Deleting an original or variant is blocked while referenced. Delete its variants
before deleting an original. Bulk deletion keeps referenced assets and reports
failures. Originals and variants are shared across devices without duplicate
original storage.

### Dithering and Spectra 6 color choices

The **?** beside Dithering opens explanations in the editor without discarding
your work. A short recommendation also follows the selected method.

| Method | Useful starting point | Tradeoff |
|---|---|---|
| Floyd–Steinberg | Photos and mixed content | Fine grain; may show directional patterns |
| Atkinson | High-contrast art, line work, text | Clear contrast; may discard subtle tones |
| Stucki | Skies, skin, photographic gradients | Smoother transitions; can soften details |
| Jarvis–Judice–Ninke | Smooth photographic gradients | Wider diffusion; more blur/work |
| Burkes | A lighter Stucki alternative | Less computation, different texture |
| Sierra-3 | Another photo/detail balance | Compare against Stucki on the actual panel |
| Ordered Bayer 4 × 4 | Graphics and consistent patterned texture | Visible regular grid |
| Blue-noise style (experimental) | Less directional texture | Uses the fixed 64 × 64 tile in the pinned 1.2.0 build |
| None | Native-color art, icons, text | No intermediate-shade simulation; photos may band |

All use the display's supported pixel codes. The library's calibrated Spectra 6
and alternative calibrated palettes match against ink-like colors before mapping
to native output codes. RGB and perceptual LAB matching can also be compared.
Try the calibrated Spectra 6 palette with Floyd–Steinberg or Stucki for photos,
then judge on the actual L; these are library calibrations, not measurements of
your specific panel. There is no universal best algorithm or guaranteed image
improvement. Existing variants are never silently reprocessed with new defaults.

See the [optimizer documentation](https://github.com/paperlesspaper/epdoptimize)
for palettes and methods; this add-on retains the vendored 1.2.0 implementation.

## Playback rules

- The first cycle follows the manually arranged order. The first selected image
  is retained until a delivery completes as far as the server can determine.
- After the interval, the next eligible authenticated image GET selects one next
  entry. A long outage never triggers catch-up through missed intervals.
- A selection pending delivery remains pending for retries, including across
  restarts. Concurrent requests are serialized per device. Successful completion
  starts the next deadline relative to this delivery.
- Repeated early GETs return the same image. Matching `If-None-Match` produces
  `304`; a different due image is selected before checking the validator so an old
  ETag cannot freeze the slideshow. Identical-byte entries still count as separate
  entries even when no display refresh is needed.
- HEAD and settings requests never advance playback. The frame supports settings
  `Last-Modified`; this value changes when generated JSON bytes change, including
  a base URL change or a changed JSON contract after an add-on update.
- Pause retains the selection. Next, previous, and show-next change selection
  immediately on the server, without waking the frame. Previous moves back within
  the current effective queue and stops at its beginning. Manually choosing an
  entry resumes traversal from its position; this deliberately can repeat/skip
  entries within that manually altered cycle.
- Shuffle affects only the queue for the next full cycle. It does not overwrite
  the base order. Avoidable repetition of the previous cycle's last image is
  prevented at the boundary. Zero images serve a white display-ready placeholder;
  one image remains stable; disabled entries are excluded.
- Mid-cycle additions and manual reorder apply at the next cycle. Invalid/disabled
  entries are removed from the remaining queue immediately. If the current entry
  is removed/disabled, select the first remaining queue entry; an empty queue
  returns the placeholder. Replacing a representation creates a new entry ID.
- “Selected” and “last served” are distinct. TCP/HTTP completion cannot prove a
  physical refresh. A crash after sending bytes but before saving completion may
  retry the same image; exactly-once physical display is not claimed.

Intervals range from 60 seconds to 30 days through JSON `timeout`. The add-on
does not emit `X-OpenPaper-Sleep-Seconds`: its smaller one-day limit and precedence
have not yet been validated on hardware. Motion wake-ups may fetch earlier;
low battery can suppress fetches. “Last contact” is not real-time online status.

### Refresh a physical OpenPaper L

The same instructions are available under **Refresh the frame and apply settings**
on each device page:

- Press the large reset button **once**: about 30 seconds of Bluetooth setup,
  followed by the normal settings/image check when no connection is made.
- Press it **twice**, each press within 3 seconds: skip setup and force an image
  download/refresh even when its cached validator says unchanged.
- Save changed settings here and wake the frame to apply them. Firmware checks
  the remote JSON before the image on every wake. Double reset forces the image,
  not an unconditional JSON reload; a `304` for unchanged settings is expected.
- Choose Next image/Show next here before waking the frame if you want another
  list entry. The add-on cannot remotely wake a sleeping device.

Do not press reset five times: that is a factory reset. Offline firmware must be
in WiFi URL-download mode. Check batteries if updates are suppressed.

The JSON supplies all supported runtime fields: `downloadUrl`, `timeout`,
`motionWakeup`, `autoRotation`, `chargerMode`, `httpAuthUser`, `httpAuthPassword`.
Basic Auth is explicitly empty because image/settings URL tokens provide access.
Charging defaults off unless explicitly enabled with NiMH confirmation. WiFi and
the initial Settings-JSON-URL are configured locally on the frame. Lists, shuffle,
mounting orientation, crop, and dithering remain add-on concerns, not invented
firmware JSON keys. CORS is only for the browser's Check/Prüfen preview and does
not affect the frame's own HTTP fetch.

## Data, backup, and recovery

All metadata is in `/data/manager.sqlite3` with schema version 1 and transactional
writes. Images/thumbnails are immutable content-addressed files under `/data/media`.
Data survives restarts. File publication is atomic; startup removes unreferenced
crash leftovers, not saved variants. Failed conversions cannot replace an existing
output. If a selected stored file disappears unexpectedly, fetching fails without
advancing to another image; restore that file or remove the affected entry.

Include the add-on and its data in HA backups. The configuration requests
`backup: cold`, so Supervisor stops the add-on for a consistent SQLite and file
snapshot. Actual Supervisor backup/restore still needs acceptance on Green.
For manual filesystem backups, stop the add-on first. Restore with it stopped. Credentials are preserved,
but the LAN base URL may need updating on a different host. JSON state exports in
the management API are not a complete data backup.

## Local development and checks

From `einkdisplaymanager/`:

```sh
python3 -m venv /tmp/eink-venv
/tmp/eink-venv/bin/pip install --require-hashes -r requirements-dev.txt
/tmp/eink-venv/bin/python -m pytest -q
/tmp/eink-venv/bin/python server.py --dev --data /tmp/eink-data
```

Open `http://127.0.0.1:8099`. Development mode binds both listeners to loopback and
accepts local management without Ingress; do not use it in the add-on container.
No real frame or cloud account is needed for local checks.

Optional browser test (install Playwright and its Chromium browser in that venv):

```sh
/tmp/eink-venv/bin/pip install playwright
/tmp/eink-venv/bin/python -m playwright install chromium
/tmp/eink-venv/bin/python scripts/browser_smoke.py
```

The script uses disposable local data and writes screenshots to
`/private/tmp/eink-browser-artifacts` by default; set `EINK_ARTIFACTS` elsewhere.

Tests cover firmware-compatible encoding, source/variant ownership, list behavior,
independent state, persistence, conditional requests, concurrent fetches, listener
isolation, token rotation, charging confirmation, and stale edits. Browser checks
exercise upload, the real full-resolution optimizer, saving a variant, device
settings, original/BMP switching at one URL, and mobile layout. The rotated
black/white crop with manual contrast and Atkinson processing is also checked
against actual saved BMP pixel codes. Landscape native pixels are rotated back
and compared exactly with the preview. Current local result: 32 Python tests and
the Chromium workflow pass. Hash-verified Linux ARM64 and AMD64 runtime wheels
are available for the pinned Python 3.13/Debian base; this is not a container build.

Browser coverage also restores an edited recipe, saves a linked revision,
operates the question-mark help, exercises all offered dithering methods at full
resolution, and checks the actual dimensions of a device's mounting-aware preview.

`scripts/transfer_smoke.py` additionally uses a real, deliberately stalled local
HTTP image response to verify live progress, selection protection, an interrupted
connection and retry, persistent form input, and mobile log layout. Run it in the
same Playwright-enabled environment as the general browser smoke test.

Before a stable release: build both Linux architectures, install on Green, verify
actual HA Ingress and backup/restore, measure Green resource use, and test image
quality, caching, interval application, retries, and power behavior on a real L.

## Sources

- [Offline firmware](https://github.com/paperlesspaper/paperlesspaper-firmware-offline)
- [Web UI and flasher](https://paperlesspaper.github.io/paperlesspaper-firmware-offline/)
- [Compatibility baseline commit](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/tree/64d47dfd4c57bb053d36813d212b4fe69aa04e8f)
- [Optimizer library](https://github.com/paperlesspaper/epdoptimize)
- [Home Assistant Ingress](https://contributors.home-assistant.io/apps/guides/ingress/)

See [UPSTREAM.md](UPSTREAM.md) for dependencies, licenses, and reproduction details.
