# E-Ink Display Manager documentation

## Installation and first connection

1. Install **E-Ink Display Manager** from this Home Assistant add-on repository.
   The add-on currently builds locally for `aarch64` or `amd64`; it does not depend
   on a separately published container image.
2. Keep device port `8098/tcp` enabled and start the add-on. Port `8099` is internal
   management traffic for HA Ingress and must not be mapped to the host.
3. Open **Web UI**. In **Settings**, set the LAN base URL, for example
   `http://192.168.1.10:8098`. Use the HA host's fixed LAN address and the mapped
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

The frame must be able to reach this host/port, including across VLANs. Configure
firewall rules accordingly. Avoid internet port forwarding. The allowlist checks
the actual TCP peer address, not untrusted forwarding headers. A reverse proxy
can obscure the original peer, so direct LAN delivery is the supported setup.

Management is admin-only through HA Ingress. The device port exposes only
token-authenticated image and settings GET/HEAD endpoints. It has no library,
upload, or management API. Production management accepts only the Supervisor's
Ingress peer; proxy/user headers alone cannot grant access. Assets, previews, and
other downloads do not advance playback.

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

Optimization uses the vendored `epdoptimize@1.2.0` in an isolated browser worker,
not the HA backend's event loop. A current browser with OffscreenCanvas support
is needed. The server normalizes editor input orientation, embedded ICC profiles
to sRGB, and transparency, and
validates every finished BMP before saving. Automatic and manual settings are
recorded in the variant's recipe. Manual brightness/contrast/saturation adjustments
override automatic tone adjustment when nonzero. Vivid and black/white presets,
Floyd–Steinberg/Atkinson/nearest-color processing, contain/cover with crop position, and rotation are
available. Updating the preview processes the full output resolution; its saved
bytes are the authoritative result, not an enlarged reduced-resolution preview.
Physical e-paper colors depend on the display and lighting; the preview is not a
calibrated physical display simulation.

Adding or saving a variant never silently changes existing device assignments.
Create new assignments or remove/re-add an entry to choose a different variant.
Deleting an original or variant is blocked while referenced. Delete its variants
before deleting an original. Bulk deletion keeps referenced assets and reports
failures. Originals and variants are shared across devices without duplicate
original storage.

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
  `Last-Modified`; this value changes only when device configuration/base URL changes.
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
against actual saved BMP pixel codes. Current local result: 18 Python tests and
the Chromium workflow pass. Hash-verified Linux ARM64 and AMD64 runtime wheels
are available for the pinned Python 3.13/Debian base; this is not a container build.

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
