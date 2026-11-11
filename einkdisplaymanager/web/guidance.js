export function frameHelp(){
  return `<details class="frame-help"><summary>Refresh the frame and apply settings</summary>
  <ol class="help"><li><strong>Wake and check settings:</strong> press the large reset button once. Bluetooth setup is available for about 30 seconds; without a connection, the frame then checks the settings JSON and image.</li>
  <li><strong>Reload the image immediately:</strong> press the large reset button twice, each press within 3 seconds. Offline firmware skips setup mode and forces the image download/refresh even if unchanged.</li>
  <li><strong>Apply a changed JSON:</strong> save settings here, then wake the frame. Firmware requests the settings URL before the image on every wake-up. An unchanged JSON may correctly return 304; double reset forces the image, not an unconditional JSON reload.</li>
  <li><strong>Show a different image:</strong> choose Next image or Show next here, then wake the physical frame. Add-on controls cannot remotely wake a sleeping frame.</li></ol>
  <p class="help">Use offline firmware in URL-download mode, with WiFi and the Settings-JSON-URL configured on the frame. Avoid five rapid reset presses: that is a factory reset. Check battery charge if the frame skips updates.</p>
  <p class="help">The JSON includes the image URL, interval, motion wake-up, sensor rotation, charging choice, and empty Basic Auth credentials because the URL token provides access. WiFi and the initial settings URL stay on the frame. Image lists, shuffle, crops, and mounting orientation are managed here, not sent as unsupported firmware fields. All JSON values are desired settings; HTTP delivery is not confirmation they were applied.</p>
  <p class="help">CORS is needed only for the Web UI’s browser-side Check/Prüfen action. The frame itself does not need it. Our CORS support retains tokens and network restrictions.</p>
  <a href="https://github.com/paperlesspaper/paperlesspaper-firmware-offline#buttons" target="_blank" rel="noreferrer">Offline firmware button instructions ↗</a></details>`;
}

export function compositionHelp(){
  return `<details class="help"><summary>Crop, dimensions, and multiple devices</summary>
  <p>Choose the target display before adjusting the crop. Contain keeps the whole image and adds white margins. Cover fills the target and trims edges; crop-position sliders move the visible area within those edges. Cropping never stretches the source.</p>
  <p>A variant stores the target model, native pixel dimensions, mounting orientation, crop position, and color recipe. Matching devices can reuse it. Editing and saving changes updates that variant for every assigned device. For a different size, aspect ratio, or orientation that should stay independent, prepare a separate variant from the original. We never silently resize an already dithered variant to fit another device.</p>
  <p>Only OpenPaper L is supported now. Portrait composition is 1200 × 1600; landscape is 1600 × 1200. Both export the native 1200 × 1600 BMP expected by the firmware. Other models will receive separate tested profiles, rather than arbitrary width/height fields.</p></details>`;
}
