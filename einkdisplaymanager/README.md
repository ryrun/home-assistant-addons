# E-Ink Display Manager

A local photo library and slideshow manager for **OpenPaper L**, **OpenPaper 7**,
and **Inkplate 6**. OpenPaper uses the paperlesspaper offline firmware; Inkplate uses ESPHome. Runs as a Home Assistant add-on with an
English management interface through HA Ingress.

- Upload JPEG, PNG, and BMP originals once; share them across devices.
- Adjust color, fit, rotation, and dithering using a full-resolution browser worker.
  Automatic optimization uses the same `epdoptimize` library as the upstream Web UI.
- Save display-ready variants and edit them while retaining device assignments.
- Give each device an independent image list, settings JSON, and fixed image URL.
- Publish device status through MQTT and Home Assistant discovery, including an
  explicitly simulated battery indicator with an optional gradual decline after
  missed image fetches and a delayed overdue alarm.
- Correct upside-down mounting per device without editing shared variants.
- Optionally align refreshes to a local anchor time and skip daily quiet hours.
  Device cards show the next expected connection; JSON supplies the remaining sleep.
- Compare the original composition and prepared output diagonally, with buttons,
  keyboard, and touch controls; previews retain the complete image and native ratio.
- Configure optional cells-in-series and calibrated per-cell voltage endpoints for
  a separate, explicitly approximate charge estimate.
- Play in order, optionally shuffling after each completed cycle. A sleeping frame
  does not cause images to be skipped in the background.
- Choose compatible original delivery or a prepared model-specific 4-bit BMP per entry
  (OpenPaper L: 1200 × 1600; OpenPaper 7: 800 × 480), or an eight-level
  grayscale PNG for Inkplate 6 (800 × 600).
- Use the included ESPHome example to fetch OpenPaper-compatible settings JSON
  and PNG images, sleep for the configured interval, and report measured battery voltage.
- Prepare Inkplate 6 variants in eight grayscale levels or black and white, with
  optional tone inversion saved in the recipe. Use black-and-white variants for
  ESPHome `greyscale: false`.
- Hide already assigned motifs in each device’s Add images picker.

**Experimental 0.6.0.** Automated and browser testing are separate from real-device
acceptance. Installation on Home Assistant Green and display quality on a physical
frame still need verification. The new OpenPaper 7 profile is validated in software;
physical acceptance on its 7.3-inch Spectra 6 hardware remains pending. Inkplate 6
also needs physical acceptance with your existing board configuration.
Dynamic images are available in **Media Library → Dynamic images**. Write JavaScript
with the isolated QuickJS editor, upload fonts in **Fonts**, create target variants,
and use them in ordinary device lists. Generated images and variants stay in a
bounded RAM cache; scripts, recipes, uploaded images, and fonts persist.
See [the dynamic-image guide](DOCS.md#dynamic-images-and-fonts) for examples and limits.

See [DOCS.md](DOCS.md) for installation, networking, firmware setup, and development.
No manufacturer-cloud account or custom Home Assistant integration is required.
