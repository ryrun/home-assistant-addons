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
  explicitly estimated 0/100% battery indicator based on overdue image fetches.
- Correct upside-down mounting per device without editing shared variants.
- Play in order, optionally shuffling after each completed cycle. A sleeping frame
  does not cause images to be skipped in the background.
- Choose compatible original delivery or a prepared model-specific 4-bit BMP per entry
  (OpenPaper L: 1200 × 1600; OpenPaper 7: 800 × 480), or an eight-level
  grayscale PNG for Inkplate 6 (800 × 600).
- Use the included ESPHome example to fetch OpenPaper-compatible settings JSON
  and PNG images, sleep for the configured interval, and report measured battery voltage.
- Hide already assigned motifs in each device’s Add images picker.

**Experimental 0.4.0.** Automated and browser testing are separate from real-device
acceptance. Installation on Home Assistant Green and display quality on a physical
frame still need verification. The new OpenPaper 7 profile is validated in software;
physical acceptance on its 7.3-inch Spectra 6 hardware remains pending. Inkplate 6
also needs physical acceptance with your existing board configuration.
Dynamic, scripted images are planned in the repository’s [plan.md](../plan.md);
this release supports uploaded images only.

See [DOCS.md](DOCS.md) for installation, networking, firmware setup, and development.
No manufacturer-cloud account or custom Home Assistant integration is required.
