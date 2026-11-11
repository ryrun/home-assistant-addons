# E-Ink Display Manager

A local photo library and slideshow manager for **OpenPaper L** frames running
the paperlesspaper offline firmware. Runs as a Home Assistant add-on with an
English management interface through HA Ingress.

- Upload JPEG, PNG, and BMP originals once; share them across devices.
- Adjust color, fit, rotation, and dithering using a full-resolution browser worker.
  Automatic optimization uses the same `epdoptimize` library as the upstream Web UI.
- Save display-ready variants and edit them while retaining device assignments.
- Give each device an independent image list, settings JSON, and fixed image URL.
- Correct upside-down mounting per device without editing shared variants.
- Play in order, optionally shuffling after each completed cycle. A sleeping frame
  does not cause images to be skipped in the background.
- Choose compatible original delivery or a prepared 1200 × 1600 4-bit BMP per entry.

**Experimental 0.1.7.** Automated and browser testing are separate from real-device
acceptance. Installation on Home Assistant Green and display quality on a physical
OpenPaper L still need verification. Other OpenPaper models are not supported yet.

See [DOCS.md](DOCS.md) for installation, networking, firmware setup, and development.
No manufacturer-cloud account or custom Home Assistant integration is required.
