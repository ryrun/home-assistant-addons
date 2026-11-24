const modes = [
  ['srgb', 'sRGB full color'],
  ['gray8', 'Inkplate 6 · eight gray levels'],
  ['grayscale', 'Inkplate 6 · black and white'],
  ['spectra6', 'OpenPaper L · Spectra 6'],
  ['custom', 'Own palette'],
];

const presets = {
  standby: [800, 800],
  small: [800, 800],
  medium: [1280, 600],
  large: [1200, 1260],
};

export function customDeviceFields(config, starting = false) {
  const {width=800, height=800, color_mode='srgb', colors=[], dither='none'} = config || {};
  return `<fieldset class="device-option-group" data-custom-device><legend>Custom output</legend>
    ${starting?`<label class="field">Template<select name="custom_preset" aria-label="Template"><option value="">Custom dimensions</option>
      ${Object.keys(presets).map(name=>`<option value="${name}">Widgy ${name==='standby'?'StandBy':name[0].toUpperCase()+name.slice(1)}</option>`).join('')}</select></label>`:''}
    <div class="form-pair">
      <label class="field">Width (pixels)<input name="custom_width" type="number" min="64" max="1600" required value="${width}"></label>
      <label class="field">Height (pixels)<input name="custom_height" type="number" min="64" max="1600" required value="${height}"></label>
    </div>
    <label class="field">Color mode<select name="custom_color_mode" aria-label="Color mode">${modes.map(([key,label])=>
      `<option value="${key}" ${key===color_mode?'selected':''}>${label}</option>`).join('')}</select></label>
    <label class="field" data-custom-colors>Palette colors<input name="custom_colors" maxlength="160" placeholder="#000000, #ffffff" value="${colors.join(', ')}"><small>Enter 2–16 distinct #RRGGBB colors, separated by commas or spaces.</small></label>
    <label class="field" data-custom-dither>Output dithering<select name="custom_dither" aria-label="Output dithering">
      <option value="none" ${dither==='none'?'selected':''}>None</option>
      <option value="floyd" ${dither==='floyd'?'selected':''}>Floyd–Steinberg</option>
    </select></label>
    <p class="help">Opaque PNG at the configured size.${starting?'':' Remove prepared variants for this device before changing its output settings.'}</p>
  </fieldset>`;
}

export function bindCustomDevice(form, active = () => true) {
  const group = form.querySelector('[data-custom-device]');
  const field = name => form.elements.namedItem('custom_'+name);
  function update() {
    const enabled = active();
    const mode = field('color_mode').value;
    group.hidden = !enabled;
    group.disabled = !enabled;
    field('colors').disabled = mode !== 'custom';
    field('colors').required = mode === 'custom';
    group.querySelector('[data-custom-colors]').hidden = mode !== 'custom';
    field('dither').disabled = mode === 'srgb';
    group.querySelector('[data-custom-dither]').hidden = mode === 'srgb';
  }
  field('color_mode').addEventListener('change', update);
  field('preset')?.addEventListener('change', () => {
    const size = presets[field('preset').value];
    if (size) {
      [field('width').value, field('height').value] = size;
      field('color_mode').value = 'srgb';
    }
    update();
  });
  form.elements.namedItem('profile')?.addEventListener('change', update);
  update();
}

export function readCustomDevice(form) {
  const field = name => form.elements.namedItem('custom_'+name).value;
  const mode = field('color_mode');
  return {width:Number(field('width')), height:Number(field('height')), color_mode:mode,
    colors:mode==='custom'?field('colors').trim().split(/[\s,]+/):[],
    dither:mode==='srgb'?'none':field('dither')};
}
