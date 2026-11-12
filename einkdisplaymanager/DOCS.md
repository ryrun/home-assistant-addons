# E-Ink Display Manager documentation

## Installation and first connection

1. Install **E-Ink Display Manager** from this Home Assistant add-on repository.
   The add-on is configured to build locally for `aarch64` or `amd64`; it does not depend
   on a separately published container image.
2. Keep device port `8098/tcp` enabled and start the add-on. Port `8099` is internal
   management traffic for HA Ingress and must not be mapped to the host.
3. Open **Web UI**. In **Settings**, check and save the prefilled LAN base URL, for
   example `http://homeassistant.local:8098` or `http://192.168.1.10:8098`.
   Use the HA host's fixed LAN address and the mapped
   device port. Do not use a changing Ingress URL or the external HA URL.
4. Upload images in **Media Library**. Open an image, adjust it, update the
   full-resolution preview, and save a variant if desired.
5. In **Devices**, add an OpenPaper L, OpenPaper 7, or Inkplate 6 with the matching device type. Open **Add images** and select an original
   or a saved variant for each assignment. Already assigned motifs are hidden in this device’s picker, including
   disabled entries and other variants of the same original. Removing an entry
   makes its motif available again. Existing repeated entries remain supported; drag entries or use their arrow buttons to arrange the base order.
6. For Inkplate 6, follow the ESPHome section below. For OpenPaper, copy the device's **Settings JSON URL**. In the upstream
   [Web UI & flasher](https://paperlesspaper.github.io/paperlesspaper-firmware-offline/),
   configure offline firmware, WiFi, and this Settings-JSON-URL on the frame.
   The add-on's JSON includes the fixed image URL and supported settings.
7. Wake the frame and verify that its request timestamps and last served image
   update. Test the output physically before leaving the device unattended.

**Save settings** displays progress and confirmation beside the button. “Settings
saved” confirms storage in the add-on; the frame applies them on its next wake-up.
Save failures remain visible beside the form, with the entered values retained.

## Optional refresh schedule

Each device keeps its normal **Update interval**. Under **Refresh schedule**, both
options are off by default and can be enabled independently:

- **Align refreshes to an anchor time**: a 24-hour interval at 03:00 targets 03:00
  each local day. A six-hour interval targets 03:00, 09:00, 15:00, and 21:00.
  The reference date sets the phase for multi-day or uneven intervals; a seven-hour
  grid continues across midnight rather than restarting its interval every day.
- **Quiet hours**: a daily start/end window can cross midnight, e.g. 22:00–08:00.
  The start is included; the end is available for updates. Anchored slots inside
  the window are skipped, so 03:00/09:00 with that window resumes at 09:00.
  Without an anchor, a relative target inside the window moves to its end.

Choose an IANA **Schedule time zone** such as `Europe/Berlin`. The UI suggests your
browser zone when first enabling the options. An anchor follows local wall time:
03:00 remains 03:00 across daylight-saving changes. A nonexistent spring-forward
slot is skipped; a repeated autumn slot runs at its first occurrence only. A quiet
window ending inside a spring gap ends at the first valid local minute afterward;
an ambiguous quiet end uses the next real occurrence. The
zone database is pinned in the container rather than inherited from its host.
Schedules that block every possible anchored slot are rejected with an inline
error. Disabling an option retains its previous valid settings for later use.

The server computes **remaining seconds until the next permitted target** in the
existing JSON `timeout`, clamped to the firmware's supported 60–2,592,000 seconds.
A target less than a minute away can be reached slightly late; a target beyond
30 days requires an intermediate wake. Active schedules always return JSON **200**
with `Cache-Control: private, no-store`, even for conditional requests. Reusing a
cached countdown in a JSON 304 would apply an old relative duration. With both
options off, the original interval and conditional JSON behavior remain unchanged.
Image ETags and image 304 handling are unaffected. Leaving scheduled mode
invalidates the previous countdown before resuming normal conditional JSON.

No new JSON keys or sleep response headers are required. Current OpenPaper source
accepts these timeout values and resets its sleep prediction after applying changed
settings. ESPHome uses the same JSON example. Changes apply when the device next
requests settings; the add-on cannot wake an already sleeping frame or stop a reset,
movement wake, firmware retry, or hardware-controlled refresh. Download and panel
processing can make a physical update slightly later than its target. Check the
installed firmware on real hardware before relying on minute-level accuracy.

Automatic playlist advancement is suppressed inside quiet hours. First setup,
pending transfer retries, and explicit manual selections can still be delivered.
Missed slots do not consume playlist entries: after a long absence the frame gets
one next image. The image watchdog uses the last successful delivery and its
issued sleep duration, or the permitted schedule target when no JSON duration is
known, plus the grace period and optional decline period before an overdue alarm.
A planned night pause therefore does not create an empty-battery signal. A newly supplied shorter sleep can bring the outstanding image deadline forward.
Settings-only requests can never postpone it or restore an overdue activity indicator.

**Device cards** show last image/settings contact and **Next expected connection**.
After a JSON GET this reflects the sleep duration supplied. After a successful
image GET, the forecast uses that issued duration starting from transfer completion,
allowing for the frame’s subsequent processing. A transfer crossing an anchor
boundary must not replace a previously issued short sleep with a later grid slot.
A desired interval change cannot imply the frame has already applied it. The
next connection is unknown before first contact. It is an expectation, not a connection reservation or physical panel
acknowledgement; disabled devices have no expected connection. The device detail
also shows its next schedule slot and whether quiet hours are currently active.
MQTT publishes a separate next-connection timestamp.

## Original and variant comparison

Device cards and the detail preview preserve the complete native viewing ratio;
there is no fixed-height crop or artificial picture-frame border. A saved variant
shows a diagonal split: **Original** uses the same source rotation, fit/crop, focus,
and mounting before tone optimization; **Variant** uses the delivered output.
**Split / Original / Variant** buttons select the view explicitly. Moving the
pointer across the preview does not change it. The buttons also work on touch
screens and with the keyboard. On the focused preview,
Left/Right choose an image and Escape restores the split.

The comparison does not modify stored media or device output. Original-mode
entries show only their output preview. OpenPaper original-mode fitting and
physical ink colors remain approximations. Status polling retains the chosen
preview mode and unsaved forms. Mobile controls wrap rather than hiding buttons.

## Optional voltage-based battery estimate

Every supported model has a **Battery profile**, disabled by default. Enter:

- **Cells in series**: divide total pack voltage by this count. Defaults are four
  for OpenPaper L/7 and one for Inkplate 6; adjust for your actual hardware.
  Parallel capacity does not multiply the voltage or the series count.
- **Cell chemistry**: descriptive metadata, independent of charger settings.
- **Empty/full voltage per cell** in volts, calibrated or taken from suitable
  manufacturer data under the device's load. Full must exceed empty. No universal
  voltage thresholds are silently assumed.

The estimate is linear between those per-cell endpoints and clamped to 0–100%.
For a synthetic example, a four-cell pack at 5.6 V is 1.4 V per cell; user-selected
endpoints of 1.2/1.6 V give 50%. Those example endpoints are not a chemistry-specific
recommendation. Temperature, load, aging, and flat discharge curves (notably NiMH
and LiFePO₄) limit accuracy. Selecting a chemistry does not install a calibrated
nonlinear discharge curve. No report means unknown; a retained old report keeps
its receipt timestamp visible. Capacity in mAh alone cannot infer charge from voltage.

This **Estimated charge from voltage** is separate from **Estimated battery ·
activity only**, which remains an explicitly simulated image-fetch watchdog with
an optional gradual decline. Configuring cells never changes charging, invents
voltage, queries sleeping hardware, or resets
fetch health. Raw voltage and receipt time remain available if estimation is off.
MQTT discovers a separate charge sensor while estimation is enabled, with estimated
source/time/chemistry attributes. Voltage/timestamp sensors are discovered for
Inkplate, configured profiles, or any device that has actually reported voltage.

All authenticated non-browser device GETs may supply the generic
`X-Display-Battery-Millivolts` or the compatible
`X-OpenPaper-Battery-Millivolts` header as **total pack millivolts**. ASCII integer
500–200000 mV values are accepted to support future series packs; malformed/missing
values, HEAD/browser requests, disabled devices, and invalid credentials cannot
update telemetry. Do not expose the device token. Current OpenPaper offline
firmware still needs upstream support to send this header; Inkplate's ESPHome
example already does. The JSON schema is unchanged and does not echo telemetry.

## Inkplate 6 with ESPHome

Inkplate 6 has 800 × 600 pixels and **eight total grayscale levels**, including
black and white. Register it as **Inkplate 6**, then choose portrait or landscape
mounting. Native delivery stays 800 × 600 in either case. Portrait composition is
600 × 800 and rotates into native raster without another dithering pass.

- Original mode accepts validated JPEG, PNG, or BMP library sources (including
  progressive JPEG), normalizes EXIF/ICC/transparency, fits the entire image with
  white margins, and converts it to eight grayscale levels on the server. Sources
  remain unchanged. This is a simple fit with nearest-level quantization; use a
  variant to control cropping, tone, and dithering. OpenPaper-native indexed BMP
  originals remain model-specific; prepare a fresh Inkplate variant from the source.
- Saved Inkplate variants are full-resolution PNG, opaque, with equal RGB channels
  at levels `0, 36, 73, 109, 146, 182, 219, 255`. The server validates decoded pixels.
  In **Colors**, choose **Inkplate · eight grayscale levels** or **Black and white**.
  Black-and-white PNGs contain only `0` and `255`; the server checks that restriction
  as well as opacity and native dimensions. Both palettes offer tone optimization,
  RGB/LAB matching, and the existing dithering choices. Saturation stays hidden.
  **Invert tones** reverses the final quantized output, including margins: black
  becomes white and each gray level becomes its complement. It does not run another
  dithering pass. Palette and inversion are saved in the variant recipe and restored
  by Edit. Saving changes retains the same variant ID and all device assignments.
- Previews use actual delivered pixels, including per-device 180° correction.
  Original conversions share the bounded RAM delivery cache (8 entries / 32 MiB);
  cache keys include source hash, profile, mounting, and correction. Variants are
  never resized or re-dithered during delivery. PNG uses `Content-Type: image/png`
  at the same extensionless image URL, with content-based ETag/Last-Modified.
- Settings JSON retains the exact OpenPaper schema. ESPHome reads `downloadUrl`
  and `timeout` in seconds; motion/rotation/NiMH fields stay false and are ignored.
  Hardware charging on Inkplate is independent of these OpenPaper settings.

Download [the ESPHome merge example](web/examples/inkplate6.yaml), also linked under
**Devices → Connect your frame**. Baseline: ESPHome **2026.10.2 or later**.
This is a package fragment for an existing working configuration, not a replacement
for your board pins. Keep your WiFi, OTA, calibrated battery sensor, and PSRAM setup.

1. Set `eink_settings_url` in ESPHome `secrets.yaml` to the device’s Settings JSON URL.
2. Keep the correct display model/pins for your board revision (`inkplate_6` or
   `inkplate_6_v2`). Set display ID `inkplate_display`, `greyscale: true`,
   `partial_updating: false`, `rotation: 0`, and `update_interval: never`.
   Its drawing lambda is `it.image(0, 0, id(manager_image));`. Grayscale mode does
   not support partial refresh. For a black-and-white configuration use
   `greyscale: false`, prepare a **Black and white** variant in the library, and
   assign that saved variant to the device. Keep the example’s image type
   `GRAYSCALE`: its PNG contains only black/white values in that case. Original
   delivery remains eight-level; it is not a monochrome conversion path.
   Do not add another scale/rotation or on-frame layout.
3. The example references your calibrated polling sensor `battery_voltage` in
   **volts**. Rename those references to your existing sensor ID. To omit telemetry,
   remove the sensor update and request-header mapping; image fetching still works.
4. Merge the example’s `esphome.on_boot`, image, scripts, HTTP client, globals,
   and deep sleep configuration with your existing sections. Do not keep an old
   timer or drawing automation that refreshes the same panel independently.
5. On wake, the client measures voltage, GETs settings, parses bounded valid fields,
   GETs the image, refreshes the panel after decode, then sleeps for `timeout`.
   Network/JSON/decode errors retain the physical image and retry after 15 minutes.
   A 120-second awake limit prevents endless wake time. Keep an OTA maintenance
   method from your existing configuration; deep sleep limits the OTA window.

The JSON request supplies `X-Display-Battery-Millivolts: 3870` for a 3.870 V reading.
The server accepts ASCII integer values from 500 to 200000 mV on authenticated
non-browser GETs for any device’s settings/image endpoints, including default-mode JSON 304 responses.
Missing/invalid headers are ignored without blocking downloads. HEAD, browser
previews and rejected credentials cannot update this telemetry.
Voltage and receipt time persist, appear in device status, and publish as separate
**Battery voltage** (V) and **Battery measured at** MQTT discovery sensors. Old values
retain their measurement timestamp; no chemistry-independent charge percentage is
inferred. The existing Estimated battery sensor remains an explicitly synthetic
image-delivery watchdog. A voltage report alone does not reset that watchdog.

The example requests JSON unconditionally on each wake: deep sleep loses ordinary
RAM caches, so a cold client must not persist validators without the matching body.
`online_image` handles its own RAM validators; a fresh boot starts without them.
An in-memory 304 avoids another panel refresh. Do not persist a bare ETag across
boots without retaining the image data. The JSON response does not echo battery
telemetry; measurement flows from device to server in the request header.

Sources: [Inkplate 6 specification](https://docs.soldered.com/inkplate/6/overview/),
[ESPHome Inkplate](https://esphome.io/components/display/inkplate/),
[Online Image](https://esphome.io/components/image/online_image/),
[HTTP request and JSON parsing](https://esphome.io/components/http_request/),
[Deep Sleep](https://esphome.io/components/deep_sleep/).
Software validation does not establish physical grayscale quality or battery life.

## Supported display models

| Device type | Native transport | Native mounting | Portrait view | Landscape view | Firmware target |
|---|---|---|---|---|---|
| OpenPaper L · 13.3-inch Spectra 6 | BMP · 1200 × 1600 | Portrait | 1200 × 1600 | 1600 × 1200 | `epd13` |
| OpenPaper 7 · 7.3-inch Spectra 6 | BMP · 800 × 480 | Landscape | 480 × 800 | 800 × 480 | `epd7` |
| Inkplate 6 · eight grayscale levels | PNG · 800 × 600 | Landscape | 600 × 800 | 800 × 600 | ESPHome `inkplate_6` / `inkplate_6_v2` |

OpenPaper 7 is the smaller current Spectra 6 model, not a generic profile for older
AcEP/7-color hardware. Select the device type when registering a frame and choose
the matching display/firmware in the upstream flasher. A registered device's model
is fixed; create another device for another model. Duplicating keeps the original
model and assignments. Old records and recipes without explicit model settings
retain their OpenPaper L defaults.

The authoritative catalog is `web/profiles.json`, shared by Python and the browser
worker. OpenPaper models have their own strict top-down uncompressed 4-bit BMP contract,
valid pixel codes, native size, placeholder, preview dimensions, and mounting
conversion. OpenPaper L output is 960,118 bytes; OpenPaper 7 output is 192,118 bytes.
The 118-byte header/palette and native pixel indices remain unchanged by the
lossless 180° position correction.

Variants and already prepared 4-bit BMP originals must match the device model;
they are not silently resized and dithered again. This also applies to old saved
originals without `native_profile` metadata, identified from their validated
native dimensions and file size. A shared source JPEG/24-/32-bit BMP can still be
processed on either frame, or independently prepared into variants for both models.
If an older upload of a Seven BMP was marked unsupported before this model existed,
re-upload the same file once: validated Original compatibility is refreshed while
its ID, chosen name, files, and assignments are retained.
Selecting a target device in the editor sets that model and mounting. Saving keeps
the target context; editing a Seven recipe restores the Seven model and settings.
Changing an assigned variant to a different model is rejected to protect its devices.

Sources checked 2026-11-11: [OpenPaper 7 specification](https://paperlesspaper.de/en/buy-7-inch-epaper-picture-frame),
[manufacturer parts list](https://docs.paperlesspaper.de/manufacturing/bill-of-materials),
and the firmware's [native image raster](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/src/epaper_display.h)
(file blob `d4b5f35da0871dcc50677489e22bb26e87ba4dac`) and BMP decoder. The physical
13.3-inch driver uses 1600 × 1200 internally, while its stored/transport raster is
1200 × 1600; the 7.3-inch native raster is 800 × 480. Software checks cover both
contracts, but no new physical OpenPaper 7 or HA Ingress acceptance is claimed.

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

### HTTP 304 and unchanged images

Current upstream firmware explicitly handles **304 Not Modified** for both images
and the settings JSON. With a valid cached image and no forced download, its image
request sends `If-None-Match` for a cached ETag or `If-Modified-Since` for a cached
Last-Modified value. A 304 keeps the image and skips download and panel rendering.
The add-on still evaluates a due image-list change before comparing validators,
so an old cache entry does not stop playback from advancing. Editing the selected
variant or changing mounting correction changes the validator with the output.

This describes the current [upstream download and refresh code](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/src/main.cpp)
(file blob `c96c94eab76fa42dd7e1d8ffa9320a5c6a37c6ec`, checked 2026-11-11),
not a claim about every installed firmware build. Older builds may instead request
HTTP 200 and skip its body after comparing Last-Modified locally. Keep both image
validators available for compatibility.

### Reading battery information

The offline firmware exposes system information over its BLE characteristic
`60000001-7b0e-11ed-a1eb-0242ac120002`: `voltage` in millivolts, `usb`, and
`charging`, plus firmware/display metadata in current builds. The system-info
value is updated every ten seconds while connected. Wake the frame with one
press of its large reset button and connect nearby through the official
[Web UI & flasher](https://paperlesspaper.github.io/paperlesspaper-firmware-offline/).
Its system-information view displays voltage and charging information. A sleeping
frame does not provide continuous BLE readings.

The current offline-firmware image and settings HTTP requests do not send battery
telemetry, and it does not expose a battery HTTP endpoint for this add-on to poll.
The add-on therefore cannot infer battery charge from successful fetches or last
contact. For automatic reporting during normal wake-ups, firmware would need to
include voltage/USB/charging data, for example in authenticated image-request
headers; no extra WiFi connection would then be necessary. That is a proposed
firmware extension, not an implemented capability. Voltage is not a reliable
universal battery percentage: OpenPaper L uses four AA cells, OpenPaper 7 four AAA
cells, with different supported chemistries including NiMH. Any future telemetry should show the measured voltage,
source, and timestamp before attempting chemistry-dependent estimates.

Verified against the current [offline firmware](https://github.com/paperlesspaper/paperlesspaper-firmware-offline/blob/main/src/main.cpp)
and its [BLE documentation](https://github.com/paperlesspaper/paperlesspaper-firmware-offline#readme)
on 2026-11-11. These findings do not describe the separate manufacturer-cloud firmware.

## MQTT and Home Assistant discovery

Open **Settings → MQTT & Home Assistant**, enable MQTT, and enter the broker
hostname/IP, port, and credentials. Use the same broker as Home Assistant's MQTT
integration. The default port is `1883`; verified TLS normally uses `8883` and the
system CA trust store. The TLS checkbox suggests that port without changing a
custom port. Custom CA/client certificates are not currently configurable here.
Enter actual credentials in the form; this UI does not resolve ESPHome `!secret`
YAML references. MQTT is disabled by default and requires no new inbound port or
Home Assistant API permission.

The add-on makes one outbound MQTT connection and represents registered frames
through discovery; the sleeping frames themselves keep using HTTP and need no
MQTT firmware. Default discovery settings are enabled, prefix `homeassistant`,
and retained configs. After saving, connection status updates in place without
replacing the settings form or discarding drafts. Saving confirms persistence;
**connected** confirms broker access. Broker credentials must permit publishing
owned state/discovery topics and subscribing to Home Assistant status messages.
A connection/authentication/permission failure does not interrupt HTTP playback.

The password is stored only in the add-on's private persistent SQLite data and is
never returned by its APIs, prefilled in HTML, placed in device JSON, or included
in MQTT discovery/state. Leave the password field blank to retain it; check
**Clear saved MQTT password** to remove it. Device URLs/tokens and broker passwords
are excluded from published state and configuration. Backups contain MQTT credentials.

### Entities per registered frame

| Entity | Meaning |
|---|---|
| Estimated battery | Simulated activity percentage with an optional gradual decline after missed image fetches |
| Image update overdue | Problem binary sensor; turns on after the grace and decline periods finish |
| Image fetch status | `waiting`, `on_schedule`, `late`, `overdue`, `paused`, `disabled`, or `no_images` |
| Last contact | Latest authenticated frame image/settings GET, not browser previews |
| Last image delivery | Most recent successful HTTP image response, including 304 |
| Next expected image fetch | Expected image request based on the last delivery and supplied sleep; a schedule target is used if no JSON duration is known |
| Next expected connection | Predicted next device contact from its supplied sleep / latest completed image fetch |
| Selected image | Name of the currently selected library image; not physical-display acknowledgement |
| Enabled images | Number of enabled entries in the frame's list |
| Image interval | Desired image interval in seconds |
| Image transfer status | Idle/preparing/sending/completed/unchanged/interrupted/failed; latest error is an attribute |
| Battery voltage / measured at | Raw report and timestamp for supported/configured/reporting devices |
| Estimated charge from voltage | Optional user-calibrated linear estimate, distinct from the activity indicator |

Diagnostic entities use Home Assistant's diagnostic category. The battery entity
has `%` and the battery device class so existing dashboards can display it, but
its name and attributes identify an **activity estimate**, not a measured charge.
There is no numeric state class creating long-term battery statistics.

### Estimated battery and deadline rules

- After a completed image HTTP response, the estimate is **100%**. A successful
  **304** counts; a settings-only request, HEAD, browser preview, failed token, or
  interrupted image transfer does not reset the image watchdog.
- **Image-fetch grace period (seconds)** is the existing tolerance after the expected
  fetch: default **120 seconds**, adjustable globally from 30 to 3600 seconds.
- **Activity battery decline period (seconds)** adds a linear decline after that
  tolerance: default **0** for the existing immediate switch, configurable from
  **0 to 2592000 seconds** (30 days). Use **300** for five minutes or **86400** for
  24 hours. The setting is under **Settings → MQTT & Home Assistant** and applies
  to every device, including when MQTT is disabled.
- During a configured decline, **Image fetch status** is **late** and the estimate
  decreases from 100% toward 0%. Keep at least 1% until the full duration finishes.
  **Image update overdue** remains off until **expected image fetch + grace + decline
  period**, when the estimate becomes **0%** and status becomes **overdue**. With a
  24-hour decline, halfway through the decline the estimate is 50%.
- Changes recalculate estimates immediately from their original deadlines. For
  example, if the grace period ended ten minutes ago, a zero-duration estimate is
  0%; setting the decline to 1200 seconds raises it to 50% and clears the overdue
  problem without any image fetch. Shortening the duration can lower it again.
  Saving does not restart the decline clock. MQTT updates within approximately
  five seconds while connected; changing only these watchdog settings does not
  reconnect the broker. Device status uses the same calculation.
- A new frame starts **unknown**, including during its first decline period.
  Missing the full alarm deadline changes it to 0%; its first successful image
  response changes it to 100%.
- Paused/disabled frames and lists without enabled entries have an unknown
  estimate and no overdue problem. Resuming monitoring starts a fresh deadline.
- Each device has independent timing. The watch start and successful delivery
  timestamp survive add-on restarts, so restarting does not falsely restore 100%.

A 0% value is a signal that the frame may need attention: depleted batteries,
WiFi/network loss, a powered-off frame, or firmware/configuration issues can all
produce it. Settings may be requested without a successful image transfer. Any percentage
says nothing about actual remaining charge and HTTP success does not confirm
panel refresh. Desired interval changes may not have been applied on a sleeping
frame yet. Voltage is separately supported when firmware reports it (currently the Inkplate
ESPHome example); current OpenPaper firmware still requires an upstream change.
The activity indicator does not derive charge from HTTP success.

The MQTT battery attributes include `grace_seconds`, `battery_decay_seconds`,
`decline_starts_at`, and `overdue_at` so automations can inspect the tolerance,
decline duration, and alarm deadline. The default zero decline keeps the previous
behavior for existing installations; stored broker credentials and grace values
remain unchanged.

### Availability, retained messages, and cleanup

State topics use `einkdisplaymanager/<instance>/<broker-id>/<device-id>/state`.
The private random instance ID and stable device IDs prevent names from changing
entity identities. Discovery topics use
`<prefix>/<sensor|binary_sensor>/<instance>_<broker-id>_<device-id>/<entity>/config`.
All messages use QoS 1; state is retained, and config retention follows the setting.
The per-connection availability topic has an `online` birth and retained `offline`
last will. Graceful shutdown also publishes offline. Availability represents the
**add-on MQTT connection**, not whether a sleeping frame is awake; an overdue
battery estimate therefore stays visible while the broker connection is healthy.

The bridge reconnects with bounded backoff and republishes discovery/state when
Home Assistant announces `online` on `homeassistant/status` or `<prefix>/status`.
If you use another custom HA birth topic, retain configs or align that topic.
Retained state and configs are reconstructed from persistent add-on data on reconnect.

An owned-topic manifest is stored before publication. Removing a device or changing
discovery settings clears obsolete retained configs/state. Prefix changes retain
the same unique IDs. A previous broker's unavailable cleanup is retried separately;
its credentials and topic manifest remain in private data until cleanup succeeds.
Up to eight pending broker destinations are retained. **Pending cleanup** is shown
in settings, and device/prefix deletions on an offline current broker are processed
when it reconnects. Disable MQTT while the broker is reachable and let cleanup
finish before uninstalling if you want retained registrations removed. The bridge
only clears its own recorded topics; it never deletes a wildcard namespace.

Implementation references: [Home Assistant MQTT discovery and availability](https://www.home-assistant.io/integrations/mqtt/),
[MQTT sensor](https://www.home-assistant.io/integrations/sensor.mqtt/),
[MQTT binary sensor](https://www.home-assistant.io/integrations/binary_sensor.mqtt/),
and [aiomqtt](https://aiomqtt.bo3hm.com/).

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

HTTP does not encrypt images or tokens. OpenPaper offline firmware's HTTPS client
does not verify certificates, so HTTPS alone is not authenticated protection on
those frames. Keep HTTPS certificate verification enabled in ESPHome. WiFi
credentials are configured on the frame, not stored by this add-on. Charger mode
requires an explicit NiMH confirmation and defaults to false. This OpenPaper
option does not control Inkplate charging.

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

**OpenPaper Original** normally delivers the exact uploaded bytes; the explicit per-device
upside-down correction described below transforms only the delivery copy. Compatible baseline RGB/grayscale
JPEGs and uncompressed 24-/32-bit BMPs can be fitted/dithered on the frame. JPEG
headers and Huffman lookup constraints are checked. Progressive JPEGs, unsupported
Huffman tables, CMYK JPEGs, PNGs, and arbitrary indexed BMPs require a variant.
Some optimized-Huffman JPEGs are compatible; others are rejected. Original mode
does not promise browser-style EXIF orientation or color management on the frame.

**OpenPaper Variant** means a saved model-sized top-down, uncompressed
4-bit BMP with valid Spectra 6 pixel codes. The firmware can take its direct-output
path instead of dithering again. A compatible original in that same format is
also accepted. **Inkplate Original** fits and quantizes a delivery copy; an
**Inkplate Variant** is an eight-level grayscale PNG, as described above.
The fixed image URL needs no extension: firmware detects the file
signature, and the server sends the corresponding content type and content ETag.

The editor's **Display orientation** chooses portrait/landscape composition
independently of source-image rotation. Dimensions follow the model table above.
When composition differs from the native mounting (L landscape, Seven portrait, or Inkplate portrait),
the output is rotated counter-clockwise into that model's native transport raster,
without another dithering pass. Saved thumbnails and editor previews stay in the
chosen viewing orientation. The mounted preview corresponds to turning the frame
clockwise from its native position. Check physical orientation and sensor rotation
on the device. This retains the direct 4-bit firmware path instead of sending a
wrong-sized bitmap that the frame would convert again. Existing L portrait and
landscape recipes retain their dimensions and native rotation behavior.

Set **Mounting orientation** in the device settings as well. This controls the
device card, frame preview, and list thumbnails. Prepared previews are derived
from native file pixels in that mounting orientation; original-mode previews only
approximate the firmware's fitting and color behavior. Changing a device's mounting
does not recrop or overwrite its assigned variants. It is distinct from the
firmware's sensor-driven `autoRotation` and is not an unsupported JSON field.

### Upside-down mounting correction

If an image appears upside down, enable **Mounted upside down · correct by 180°**
in **Device settings**, then **Save settings** and wake the frame. This is a
one-time choice per device; subsequent image deliveries are corrected automatically.
The add-on cannot detect physical mounting. Use **Mounting orientation** separately
for portrait/landscape composition and a matching variant.

The device card, frame preview, and queue thumbnails show the compensated view
for that physical mounting. The transmitted bitmap itself is rotated 180°.
Prepared native 4-bit BMPs retain their palette and exact pixel codes without
another dithering pass. Compatible original BMPs are rotated as RGB BMPs; original
JPEGs require an additional baseline encoding pass and remain firmware-compatible.
Stored originals, shared variants, recipes, and other devices stay unchanged.

Correction disables automatic sensor rotation in the settings JSON to avoid
conflicting rotations. If sensor rotation was previously enabled, allow the new
settings to apply and wake the frame once more if needed. Wait for an active
transfer and panel refresh to finish before resetting the frame. The fixed image
URL stays the same; validators change with the delivered bytes so the frame can
fetch the corrected current image before the list advances. Transformed files are
cached only in RAM, limited to eight entries and 32 MiB, and rebuilt after restart.

### Targets and crop recipes

Choose **Target display** before setting the crop: either a supported model or
a registered device, which supplies its profile and mounting orientation. Native
**Display models** and **My devices** option groups distinguish the two sources;
landscape mounting does not create another model. Device types are grouped by
family. Colors, dithering, image versions, and battery chemistries also use
labeled option groups where categories apply. Empty categories are omitted. A saved
variant records the model, native and viewing dimensions, orientation, normalized
crop position, and processing settings. The same original can have multiple
variants for different aspect ratios and models. Matching devices can share one
variant; incompatible model/resolution assignments are rejected rather than
silently scaling already dithered pixels. OpenPaper L and OpenPaper 7 have separate
profiles/encoders; other display models need their own validated native contracts.

**Contain** preserves the whole image with white margins. **Cover** fills the
selected viewing area while cropping edges; horizontal/vertical crop positions
move the visible area within those edges. Neither mode stretches the source.

### OpenPaper L image-quality starting point

For a controlled comparison, use the same original, crop, physical mounting, and
lighting for each output. Start with **Spectra 6 · calibrated library palette**,
**Automatic optimization** on, **Natural** intent, **Floyd–Steinberg**, and all three
manual sliders at zero. Compare **Perceptual LAB** with RGB on the physical frame.
If the result is too muted, compare **Vivid** automatic intent with the same
calibrated palette; it no longer requires the ideal-RGB vivid palette. Try Stucki
as a second photographic diffusion option for gradients and skin tones. These are
starting points, not an objectively optimal profile for every photo or panel.

Make sure the device entry selects the prepared variant. An entry set to
**Original** bypasses this optimizer and lets the frame process the source.
After changing a recipe, **Update full-resolution preview → Save changes**, then
wake the frame and let the complete refresh finish. Existing saved BMPs are not
reprocessed by an add-on update. For a diagnostic comparison you can also prepare
the same source in the upstream Web UI and assign that compatible BMP as an
original: its native 4-bit output is delivered directly without another dither pass.

E-paper is reflective and has a smaller reproducible color range than a screen.
The exported native RGB codes and browser preview can look much brighter or more
saturated than the inks. Good, consistent ambient light matters when judging the
result. Built-in calibrated palettes are generic library measurements and are not
calibrated to this particular OpenPaper L. The upstream measurement notes explicitly
say their newer 13.3-inch camera measurements have not yet been applied to the
built-in palettes. See the [optimizer documentation](https://github.com/paperlesspaper/epdoptimize#readme)
and [OpenPaper L specification](https://paperlesspaper.de/en/openpaper-l).

The add-on retains pinned optimizer 1.2.0, also pinned in the offline Web UI's
package lock at the time of this investigation. Upstream main identifies itself as
1.4.1 and documents newer gamut-aware diffusion and other changes. Upgrading that
code, including changed blue-noise assets/behavior, needs a separate regression and
physical comparison; the integration fixes here do not claim those newer algorithms.

Version 0.1.7 fixes two integration defects: the menu-list helper
`getProcessingPresetOptions()` was incorrectly treated as a preset lookup, and
any nonzero manual slider replaced the entire automatic tone mapping. Preset
resolution now uses the actual preset configuration; changing contrast preserves
inferred saturation and curve shaping. Matching and dithering continue to follow
the explicit selections. The post-processing status shows which automatic
classification, preset, intent, and manual channels were applied. Synthetic
full-resolution comparisons verify different BMP pixels for Auto on/off; this is
functional evidence, not a measured improvement on the physical frame.

### Color matching and dithering help

Descriptions below **Color matching** and **Dithering** follow the selected option.
RGB compares channel distances and provides a predictable baseline for graphics
and palette comparisons. Perceptual LAB approximates differences as perceived by
people; try it for photos, skin tones, and subtle colors, allowing more processing
time. The optimizer uses its own perceptual matching paths for different methods;
compare the palette and matching choice on the actual reflective panel. Neither
choice guarantees a better result for every photo. There is no separate dithering
question-mark button.

### Editing a saved variant

Use **Edit** beside a saved variant. This restores its orientation, crop, palette,
algorithm, and adjustment controls, then processes the unchanged original again.
**Save changes** replaces that variant's output, name, and recipe while keeping
its ID and all device assignments. Every device sharing it will use the updated
result. An active transfer finishes before replacement; a currently selected
changed variant stays selected for its next corrected delivery, even if its
interval has elapsed. The image URL stays fixed, while cache validators reflect
the changed bytes. Concurrent edits from an older window are rejected so a stale
editor cannot silently overwrite a newer save.

Files remain immutable and content-addressed internally: validated replacement
files are written before variant metadata and affected playback state are committed
together. Files still referenced by another variant/original are retained. A failed
validation or storage-limit check leaves the previous variant intact. There is no
version-history UI or undo for a successful overwrite. To prepare a separate variant,
open the original's editor and use **Save as new variant**. **Prepare for this device**
in the device image picker starts with the appropriate target and mounting.

Optimization uses the vendored `epdoptimize@1.2.0` in an isolated browser worker,
not the HA backend's event loop. A current browser with OffscreenCanvas support
is needed. Startup has a readiness check, one retry for a failed start, and a
15-second startup timeout; processing has a three-minute timeout. Progress and
errors appear beside the preview, with failures also visible over an open dialog.
Closing/replacing the editor cancels its pending source request and worker so a
late result cannot overwrite a different editor. Decoded source bitmaps are
released after composition. This does not establish the cause of any previously
reported browser failure. The server normalizes editor input orientation, embedded ICC profiles
to sRGB, and transparency, and
validates every finished OpenPaper BMP or Inkplate grayscale PNG before saving. Automatic and manual settings are
recorded in the variant's recipe. Manual brightness/contrast/saturation adjustments
override only their corresponding automatic channel when nonzero. Zero retains
the automatic value; disable automatic optimization for neutral manual-only output. Vivid and black/white presets,
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
  starts the next deadline relative to this delivery, or at the next permitted
  wall-clock slot when optional scheduling is enabled.
- Repeated early GETs return the same image. Matching `If-None-Match` produces
  `304`; a different due image is selected before checking the validator so an old
  ETag cannot freeze the slideshow. Identical-byte entries still count as separate
  entries even when no display refresh is needed.
- HEAD and settings requests never advance playback. The frame supports settings
  `Last-Modified`; this value changes when generated JSON bytes change, including
  a base URL change or a changed JSON contract after an add-on update. Active
  schedules always return fresh JSON 200 because timeout is a countdown.
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
- **Current playback queue** follows the live status poll, including a new cycle.
  Its list may be shorter than the edited base list until that cycle finishes.
  For example, expanding two entries to nine finishes the two-entry cycle first,
  then starts a nine-entry cycle using the updated base order (or shuffle).
  Polling preserves unsaved settings and the open queue details panel.
- “Selected” and “last served” are distinct. TCP/HTTP completion cannot prove a
  physical refresh. A crash after sending bytes but before saving completion may
  retry the same image; exactly-once physical display is not claimed.

Intervals range from 60 seconds to 30 days through JSON `timeout`. The add-on
does not emit `X-OpenPaper-Sleep-Seconds`: its smaller one-day limit and precedence
have not yet been validated on hardware. Motion wake-ups may fetch earlier;
low battery can suppress fetches. “Last contact” is not real-time online status.

### Refresh a physical OpenPaper frame

The same instructions are available under **Refresh the frame and apply settings**
on each device page:

- Press the large reset button **once**: about 30 seconds of Bluetooth setup,
  followed by the normal settings/image check when no connection is made.
- Press it **twice**, each press within 3 seconds: skip setup and force an image
  download/refresh even when its cached validator says unchanged.
- Save changed settings here and wake the frame to apply them. Firmware checks
  the remote JSON before the image on every wake. Double reset forces the image,
  not an unconditional JSON reload; a `304` for unchanged default-mode settings is expected. Active schedules
  return fresh JSON 200 to update the remaining sleep duration.
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
node --test scripts/test_optimizer_options.mjs scripts/test_display_profiles.mjs
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
and compared exactly with the preview. Historical 0.3.0 result: 68 Python tests, eleven JavaScript optimizer/geometry checks,
and the Chromium workflow pass. Hash-verified Linux ARM64 and AMD64 runtime wheels
are available for the pinned Python 3.13/Debian base; this is not a container build.

Browser coverage also restores and overwrites an edited variant, checks inline
matching/dithering help and notifications above modal content, injects worker-start
failures and invalid source data, verifies cancellation, and exercises all offered methods at full
resolution, and checks the actual dimensions of a device's mounting-aware preview.
Rotation checks cover exact native BMP pixels, compatible original formats,
unchanged shared media, device-specific previews, cache validators, current-image
retention, sensor conflicts, and persistence of the mounting setting in the UI.

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

The MQTT tests use a disposable, loopback-only **Mosquitto** broker and
`mosquitto_passwd` when installed. They verify discovery/state, authentication
failure/recovery with redacted errors, HA birth replay with nonretained configs,
retained-topic cleanup, offline deletion across restart, and watchdog boundaries.
These broker-specific tests are skipped if Mosquitto is absent; they are not a
claim that real HA discovery has been accepted on a running Home Assistant instance.
Chromium also checks MQTT form persistence, password preservation/clear behavior,
responsive settings layout, and the device activity estimate. Existing transfer
smoke checks continue to cover pending HTTP responses and interruption/retry.

OpenPaper 7 browser checks register the model through the real UI, prepare and
save its 800 × 480 output, edit a portrait 480 × 800 recipe under the same variant
ID, compare decoded native pixels exactly with the preview, serve its fixed URL
with device-specific 180° correction, and check the 384 × 640 mounted preview on
desktop/mobile. The picker excludes L variants from Seven devices and disables a
prepared Seven original on an L device. Python tests also exercise per-model
placeholders, legacy-original compatibility, duplication, strict BMP validation,
original/variant assignment rules, firmware JSON, and MQTT model metadata.

### Inkplate 6 validation (0.4.0)

The suite has 72 Python and 14 JavaScript tests. Inkplate coverage includes strict
PNG pixel/size validation, lossless correction, original conversion and its mounted
previews, placeholders, fixed-URL cache validators, variant overwrite with retained
assignments, unchanged JSON schema, authenticated telemetry and ignored invalid/
browser/HEAD reports, separate voltage discovery, and device cleanup.

The real Chromium worker/UI checks all eight grayscale levels on a ramp, prepares
and edits an Inkplate variant, verifies portrait output against preview pixels,
assigns it, checks immediate picker filtering, reads voltage, and verifies corrected
delivery/mobile layout. Existing OpenPaper, MQTT, and interrupted-transfer browser
checks remain in the suite. Firmware compilation, real HA installation, and actual
Inkplate display/battery acceptance are separate checks.

### Scheduling, comparison, and battery validation (0.5.0)

120 Python tests include local anchors, uneven/multi-day phases, overnight and
daytime quiet hours, DST gaps/folds, blocked grids, dynamic JSON, default-mode
304 retention, watchdog independence, next-connection timestamps, calibrated pack
voltage, unknown/clamped charge, MQTT metadata, and matching source-crop comparisons
for every model/orientation. Tests run with PYTHONTZPATH empty to exercise only the
pinned timezone package. Browser checks cover real hover, keyboard, touch controls,
complete-image dimensions, schedule/battery save/error/draft behavior, next-contact
cards, and desktop/mobile spacing. Physical firmware timing and calibrated cell
charge accuracy remain hardware acceptance work.

### Final review (0.5.1)

Current local evidence is 127 Python tests and 14 JavaScript tests, with real
Chromium and interrupted-transfer checks. Boundary coverage includes a slow image
transfer crossing an anchor slot while the frame retains an already issued short
sleep, watchdog behavior after a settings-only contact, oversized PNG headers,
large numeric voltage endpoints, and calendar-form anchor dates. The image-change
deadline remains distinct from the sleep actually supplied to a frame. Sparse
second-based grids skip excluded phases directly, so a valid schedule cannot
exhaust the old search budget and prevent device/status reads. Clock-phase lookup
is cached in at most 64 byte maps (about 5.3 MiB worst-case).

Local Markdown links and add-on YAML were checked. Full ESPHome firmware compilation
is still pending: the temporary validation environment could not download the
ESPHome package before its network timeout. The example has source/syntax review;
it is not described as a successfully built or physically tested firmware.

### Inkplate tone modes and explicit comparison (0.5.2)

Variants remain persistent files in `/data/media`, with metadata and recipes in
SQLite. Preparing black-and-white or inverted output writes the finished PNG;
normal requests read it without rerunning the optimizer. Existing per-device 180°
correction and its bounded RAM cache are unchanged. This release does not move
variants into RAM or implement the planned dynamic images.

128 Python tests, 14 JavaScript checks, and the Chromium workflow cover strict
monochrome validation, stored palette/inversion flags, edited assignments, PNG
delivery, all eight tones / only two tones on full-resolution ramps, exact inverse
pixels with automatic tone/dithering options, native portrait pixel equivalence,
and button/keyboard/touch comparison with no hover switching. Physical display
quality and the complete ESPHome firmware build still need external acceptance.

## Dynamic images and fonts

Version 0.6.0 adds **Images**, **Dynamic images**, and **Fonts** within Media Library.
Normal uploaded originals and their manually prepared variants keep their existing
persistent storage. Dynamic images are programmable canvases with a separate,
volatile rendering pipeline.

### Create a dynamic image

1. Optionally upload backgrounds or symbols in **Images**, and TTF/OTF fonts in
   **Fonts**. Use **Copy ID** to reference them. Image/font IDs stay stable when
   their display name changes; scripts never use filenames or filesystem paths.
2. Open **Dynamic images → Create dynamic image**. Enter a name, generation
   interval, and IANA time zone. JavaScript editing includes syntax highlighting,
   line numbers, bracket matching, completion, and indentation with Tab.
3. Choose a display model and orientation. Every saved target variant has its own
   palette, matching, dithering, automatic-optimization and grayscale-inversion
   recipe. The **Image optimization** section contains these options. Exact
   `palette` colors bypass tone/matching changes; RGB colors and photos are optimized.
4. Use **Render preview** to render the unsaved draft without publishing it to
   devices. **Save image & target** saves the script and selected recipe and starts
   rendering saved targets. **Render now** regenerates saved targets; save edits
   first or use the separate draft preview.
5. Add the saved target variant through a device's ordinary **Add images** dialog.
   Dynamic items have no original-delivery mode. Matching targets can be shared by
   devices. Create a new target when changing hardware models; editing a target
   retains its ID and assignments.

Script changes apply to all of the item's saved target variants. A render uses
one frozen time and HA snapshot, runs the script for each target's dimensions,
then publishes the completed batch atomically. An active transfer keeps its own
immutable bytes. Target recipes can be edited; source/recipe edits during a render
invalidate that in-flight result and schedule another run.

### JavaScript example

```javascript
screen.clear("#ffffff");

screen.rectangle({
  x: 20, y: 20,
  width: screen.width - 40,
  height: screen.height - 40,
  stroke: palette.black,
  strokeWidth: 2
});

const greeting = now.hour < 12 ? "Good morning"
  : now.hour < 18 ? "Good afternoon" : "Good evening";
const temperature = ha.number("sensor.living_room_temperature", null);

screen.text(greeting, {
  x: screen.width / 2, y: screen.height / 2,
  font: "default", fontSize: 48,
  color: palette.black,
  align: "center", verticalAlign: "middle"
});

screen.text(temperature === null ? "Temperature unavailable" : `${temperature} °C`, {
  x: 40, y: screen.height - 80,
  font: "your-uploaded-font-id", fontSize: 30,
  color: palette.black
});

screen.image("your-uploaded-image-id", {
  x: 40, y: 100, width: 160, height: 120, fit: "contain"
});
```

This is synchronous JavaScript source interpreted by QuickJS-NG, not Python or a
browser/Node environment. Conditions, loops, arrays, arithmetic and helper
functions work normally. There are no host `fetch`, file, shell, `process`,
`require`, package-installation or HA service-call functions. Asynchronous jobs
are not used to draw: issue commands synchronously within the script.

### Drawing API version 1

Coordinates are pixels from the viewing area's top left, before native transport
rotation or per-device 180° correction. Later commands draw over earlier commands.
Content is clipped at the canvas edge. Common options are plain JSON values;
unknown fields, invalid sizes/nonfinite coordinates and excessive output fail the
render instead of reaching unrestricted Pillow APIs.

| API | Options / behavior |
|---|---|
| `screen.width`, `screen.height` | Current target's viewing dimensions; do not hard-code a device size |
| `screen.clear(color)` | Opaque background; default `#ffffff` |
| `screen.text(text, options)` | `x`, `y`, `font`, `fontSize`, `color`, `align`, `verticalAlign`, optional `maxWidth` for word wrapping |
| `screen.line(options)` | `x1`, `y1`, `x2`, `y2`, `stroke`, `strokeWidth` |
| `screen.rectangle(options)` | Top-left `x`, `y`, `width`, `height`, optional `fill`, `stroke`, `strokeWidth` |
| `screen.circle(options)` | Center `x`, `y`, `radius`, optional `fill`, `stroke`, `strokeWidth` |
| `screen.image(id, options)` | `x`, `y`, `width`, `height`, `fit: "contain"` or `"cover"`; uses an uploaded original |

Text defaults to left/top alignment, 24 px, black and font `default`. Use
`align: "center"` and `verticalAlign: "middle"` to place the text's visible block
around a point. Right/bottom alignment and multiline text are supported. Font
sizes are pixels, not CSS points. The bundled default font has a limited character
set; upload a suitable font for additional scripts or symbols.

Ordinary opaque CSS color names and `#RRGGBB` colors are mapped to the target
palette. `palette.black`, `palette.white`, and available named panel colors select
exact device colors. OpenPaper offers black, blue, green, red, yellow, and white.
Inkplate offers black, white, and `palette.gray0` through `palette.gray7` in
8-level mode; monochrome mode exposes black/white only. A missing named palette
entry is an error. Explicit palette ink remains exact through optimization;
intentional Inkplate inversion then reverses its final gray level.

`now` is a frozen object in the item's configured time zone: `hour`, `minute`,
`second`, `year`, `month`, `day`, ISO weekday `weekday` (1–7), `iso`, and Unix-seconds
`timestamp`. A new greeting appears on the display only after a new image is
generated **and** the device fetches it.

### Home Assistant snapshots

The add-on now requests the **Home Assistant Core API** permission. The trusted
parent service uses the Supervisor Core proxy to fetch selected entity states;
this permission is broad at the platform level. Application code restricts this
feature to reads of `/api/states/<entity_id>`. It is not a narrowly scoped HA token.
No Supervisor/MQTT credentials, API client or live connection enters the worker.

Literal IDs in `ha.state("sensor.example")`, `ha.number(...)`, and
`ha.attribute(...)` are detected automatically. For loops or calculated IDs, list
all permitted IDs under **Home Assistant inputs → Additional entity IDs**. Scripts
can read only that preloaded snapshot. Use the explicit list for unusual syntax;
ID detection is a convenience, not a complete JavaScript dependency parser.

- `ha.state(id, fallback = null)` returns the state string; missing, unknown and
  unavailable states return the fallback.
- `ha.number(id, fallback = null)` converts a finite numeric state. Always choose
  a useful fallback before formatting a potentially unavailable value.
- `ha.attribute(id, name, fallback = null)` returns a selected state's attribute.

Up to 64 selected entities are loaded per render with a ten-second total snapshot
budget, 64 KiB per entity, and 256 KiB combined data limit. A missing entity is
unavailable; authentication/network/snapshot failures retain the last good image.
The Core proxy connection still requires acceptance on an installed Home Assistant
system; local tests do not replace Green/Supervisor or physical-device testing.

### Storage, scheduling, and errors

- Scripts, names, intervals, time zones, target recipes, uploaded originals and
  fonts persist. Generated source rasters, native target outputs, previews and
  render status are **RAM only**. No generated files, image blobs, render histories
  or per-render hash/status updates are written to SQLite. Normal authenticated
  device-transfer/playback diagnostics continue to persist as before.
- Each item's generation interval is independent of device sleep/playlist timing.
  Device GETs consume the latest successful output; they never start a render or
  fetch HA data. Rendering does not advance queues, count as device contact, or
  reset the simulated battery watchdog.
- The scheduler coalesces overlapping runs, skips catch-up bursts, and runs one
  isolated rendering worker at a time. Interactive previews can run between target
  variants; manual queues are bounded. ETags hash actual delivered bytes, so an
  unchanged generated image can still produce HTTP 304 at the fixed image URL.
- A missing image ID draws nothing and reports a warning. A missing font ID uses
  the bundled default with a warning. Script references do not prevent deleting
  an otherwise unused uploaded resource. Normal direct device assignments and
  static saved variants retain their existing deletion protection.
- Errors preserve the last successful batch. The editor shows running/error state,
  warnings and last-success time separately from device transfer diagnostics.
  When no good output exists, including immediately after restart, image delivery
  returns **HTTP 503** with `Retry-After: 60`; pending playback is retained for retry.
  The firmware controls its retry behavior. No replacement error image is sent.
- A 128 MiB dynamic-output budget bounds the RAM cache. At capacity a render fails
  while retaining prior good outputs; remove unused targets to free space. Other
  limits: 32 dynamic items, eight targets/item, 32 uploaded fonts at 4 MiB each,
  64 KiB source, 1000 drawing commands/256 KiB command output, 8 MiB per embedded
  resource and 12 MiB combined resources. Generation intervals are 10 seconds to
  30 days. Complex/frequent renders consume CPU; there is no unlimited catch-up.
- Each disposable worker has sanitized environment/closed inherited descriptors,
  CPU and wall-clock limits, a limited QuickJS heap/stack and (Linux) a 512 MiB
  process address-space limit. Linux installs a default-deny seccomp filter with
  no-new-privileges; macOS development uses Seatbelt. Native file access, network
  connections and process creation are tested at startup. Failed/unsupported
  isolation disables dynamic execution while uploaded-image delivery remains
  available. Only source is accepted; no untrusted QuickJS bytecode is loaded.

Metadata upgrades to version 2 so older builds refuse an unsafe downgrade instead
of deleting uploaded font files as orphans. Use a matching backup to roll back;
do not edit the database version manually. Font licensing remains the uploader's
responsibility. See [UPSTREAM.md](UPSTREAM.md) for editor/runtime attribution.

### Dynamic image verification

Run `scripts/dynamic_browser_smoke.py` with the same Playwright environment as the
existing browser smoke. It exercises the real editor, fonts/IDs, draft preview,
saved rendering, device PNG/304 delivery, errors, last-good images and absence of
persistent generated files. `tests/test_dynamic.py` covers bounded hostile scripts,
native target geometry, resource fallbacks, RAM budgets, clock/snapshot APIs and
retry/ETag behavior. `.github/workflows/eink-dynamic.yml` builds the actual image
natively on AMD64 and ARM64 and verifies seccomp/rendering as UID/GID 10002 in a
read-only, network-disabled container. These checks do not certify physical
screen quality or a particular installed Home Assistant configuration.
