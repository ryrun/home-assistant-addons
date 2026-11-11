import {optionGroups} from './selects.js';
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const chemistries={custom:'Custom / unspecified',alkaline:'Alkaline',nimh:'NiMH',li_ion:'Li-ion / LiPo',lifepo4:'LiFePO₄'};

export function intervalLabel(seconds){
  if(seconds%86400===0)return `${seconds/86400} day${seconds===86400?'':'s'}`;
  if(seconds%3600===0)return `${seconds/3600} hour${seconds===3600?'':'s'}`;
  if(seconds%60===0)return `${seconds/60} minute${seconds===60?'':'s'}`;
  return `${seconds} seconds`;
}

function localDate(zone){
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(p=>[p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function deviceOptionsHTML(device){
  const s=device.schedule,b=device.battery;
  const zone=!s.anchor_enabled&&!s.quiet_enabled&&s.timezone==='UTC'?Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC':s.timezone;
  const day=s.anchor_date==='1970-01-01'&&!s.anchor_enabled?localDate(zone):s.anchor_date;
  return `<fieldset class="device-option-group"><legend>Refresh schedule <span>Optional</span></legend>
  <label class="check"><input name="anchor_enabled" type="checkbox" ${s.anchor_enabled?'checked':''}>Align refreshes to an anchor time</label>
  <div data-anchor-fields class="stack"><label class="field">Anchor time<input name="anchor_time" type="time" value="${escape(s.anchor_time)}"><small>For 24 hours at 03:00: daily at 03:00. For 6 hours: 03:00, 09:00, 15:00, 21:00.</small></label>
  <details class="option-details"><summary>Reference date</summary><label class="field">Anchor reference date<input name="anchor_date" type="date" min="1970-01-01" max="2100-12-31" value="${escape(day)}"><small>Sets the phase for multi-day or uneven intervals. The time grid extends in both directions from this date.</small></label></details></div>
  <label class="check"><input name="quiet_enabled" type="checkbox" ${s.quiet_enabled?'checked':''}>Skip automatic refreshes during quiet hours</label>
  <div data-quiet-fields class="form-pair"><label class="field">Quiet hours start<input name="quiet_start" type="time" value="${escape(s.quiet_start)}"></label><label class="field">Quiet hours end<input name="quiet_end" type="time" value="${escape(s.quiet_end)}"></label></div>
  <label class="field" data-zone-field>Schedule time zone<input name="schedule_timezone" maxlength="80" value="${escape(zone)}" placeholder="Europe/Berlin"><small>IANA zone; local clock changes are handled automatically.</small></label>
  <p class="help">Quiet hours can cross midnight. Anchored slots are skipped; relative refreshes move to the end of the window. Manual selections and first setup can still be delivered. Settings apply on the next wake-up.</p></fieldset>
  <fieldset class="device-option-group"><legend>Battery profile <span>Optional</span></legend>
  <label class="check"><input name="charge_enabled" type="checkbox" ${b.enabled?'checked':''}>Estimate charge from reported voltage</label>
  <div data-battery-fields class="stack"><label class="field">Cell chemistry<select name="charge_chemistry"><option value="custom" ${b.chemistry==='custom'?'selected':''}>${chemistries.custom}</option>${optionGroups([['Primary cells',['alkaline']],['Rechargeable cells',['nimh','li_ion','lifepo4']]].map(([label,keys])=>[label,keys.map(key=>`<option value="${key}" ${key===b.chemistry?'selected':''}>${chemistries[key]}</option>`).join('')]))}</select></label>
  <label class="field">Cells in series<input name="charge_cells" type="number" min="1" max="32" step="1" value="${b.series_cells}"><small>OpenPaper L/7: four cells. Inkplate 6: one Li-ion cell. Parallel cells do not increase pack voltage.</small></label>
  <div class="form-pair"><label class="field">Empty voltage per cell (V)<input name="charge_empty" type="number" min="0.1" max="6" step="0.001" value="${b.empty_voltage??''}" placeholder="Your calibrated value"></label><label class="field">Full voltage per cell (V)<input name="charge_full" type="number" min="0.1" max="6" step="0.001" value="${b.full_voltage??''}" placeholder="Your calibrated value"></label></div></div>
  <p class="help">Uses total pack voltage divided by cells in series and a linear empty-to-full estimate. Enter values calibrated for your cells and load. Chemistry is descriptive; flat discharge curves reduce accuracy. No voltage report means unknown. Charging and the separate activity indicator stay independent.</p></fieldset>`;
}

export function bindDeviceOptions(form){
  const fields=key=>form.elements.namedItem(key);
  const update=()=>{
    for(const [selector,on] of [['[data-anchor-fields]',fields('anchor_enabled').checked],['[data-quiet-fields]',fields('quiet_enabled').checked],['[data-battery-fields]',fields('charge_enabled').checked]]){
      const group=form.querySelector(selector);group.hidden=!on;
      group.querySelectorAll('input,select').forEach(control=>{control.disabled=!on;control.required=on;});
    }
    form.querySelector('[data-zone-field]').hidden=!(fields('anchor_enabled').checked||fields('quiet_enabled').checked);
  };
  for(const name of ['anchor_enabled','quiet_enabled','charge_enabled'])fields(name).addEventListener('change',update);
  fields('interval').addEventListener('input',()=>{form.querySelector('[data-interval-label]').textContent=intervalLabel(Number(fields('interval').value));});
  update();
}

export function readDeviceOptions(form){
  const f=name=>form.elements.namedItem(name);
  const anchor=f('anchor_enabled').checked,quiet=f('quiet_enabled').checked,charge=f('charge_enabled').checked;
  return {schedule:{anchor_enabled:anchor,quiet_enabled:quiet,
    ...(anchor?{anchor_time:f('anchor_time').value,anchor_date:f('anchor_date').value}:{}),
    ...(quiet?{quiet_start:f('quiet_start').value,quiet_end:f('quiet_end').value}:{}),
    ...(anchor||quiet?{timezone:f('schedule_timezone').value.trim()}: {})},
  battery:{enabled:charge,...(charge?{chemistry:f('charge_chemistry').value,series_cells:Number(f('charge_cells').value),
    empty_voltage:f('charge_empty').value===''?null:Number(f('charge_empty').value),full_voltage:f('charge_full').value===''?null:Number(f('charge_full').value)}:{})}};
}
