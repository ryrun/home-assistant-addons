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
  <p class="help">Quiet hours can cross midnight. Anchored slots are skipped; relative refreshes move to the end of the window. Manual selections and first setup can still be delivered. Settings apply on the next wake-up.</p>
  <div class="schedule-preview"><h3>Upcoming refresh slots</h3><p class="help" data-schedule-status role="status"></p>
  <ol data-schedule-slots></ol></div></fieldset>
  <fieldset class="device-option-group"><legend>Battery profile <span>Optional</span></legend>
  <label class="check"><input name="charge_enabled" type="checkbox" ${b.enabled?'checked':''}>Estimate charge from reported voltage</label>
  <div data-battery-fields class="stack"><label class="field">Estimation method<select aria-label="Estimation method" name="charge_method" data-default-chemistry="${device.profile==='inkplate_6'?'li_ion':'alkaline'}"><option value="chemistry" ${b.method==='chemistry'?'selected':''}>Chemistry profile</option><option value="linear" ${!b.method||b.method==='linear'?'selected':''}>Linear</option><option value="custom" ${b.method==='custom'?'selected':''}>Custom curve</option></select></label><p class="help" data-charge-method-help></p><label class="field">Cell chemistry<select name="charge_chemistry"><option value="custom" ${b.chemistry==='custom'?'selected':''}>${chemistries.custom}</option>${optionGroups([['Primary cells',['alkaline']],['Rechargeable cells',['nimh','li_ion','lifepo4']]].map(([label,keys])=>[label,keys.map(key=>`<option value="${key}" ${key===b.chemistry?'selected':''}>${chemistries[key]}</option>`).join('')]))}</select></label>
  <label class="field">Cells in series<input name="charge_cells" type="number" min="1" max="32" step="1" value="${b.series_cells}"><small>OpenPaper L/7: four cells. Inkplate 6: one Li-ion cell. Parallel cells do not increase pack voltage.</small></label>
  <div class="form-pair" data-charge-linear><label class="field">Empty voltage per cell (V)<input name="charge_empty" type="number" min="0.1" max="6" step="0.001" value="${b.empty_voltage??''}" placeholder="Your calibrated value"></label><label class="field">Full voltage per cell (V)<input name="charge_full" type="number" min="0.1" max="6" step="0.001" value="${b.full_voltage??''}" placeholder="Your calibrated value"></label></div>
  <label class="field" data-charge-custom>Custom curve points<textarea aria-label="Custom curve points" name="charge_curve" rows="8" maxlength="4096" spellcheck="false" placeholder="1.0, 0&#10;1.3, 55&#10;1.6, 100">${escape((b.curve||[]).map(point=>point.join(', ')).join('\n'))}</textarea><small>One voltage-per-cell, percent pair per line, using decimal points. Use 2–32 points in ascending order, from 0% to 100%. Changing this curve restarts forecast collection.</small></label></div>
  <p class="help">Pack voltage is divided by cells in series. Reference profiles are approximate, not standardized calibrations. NiMH and LiFePO₄ percentages are especially uncertain because of their flat voltage curves. Changing the estimation method restarts forecast collection. Estimates do not configure charging or protect batteries.</p></fieldset>`;
}

export function parseCurveText(text){
  return text.trim().split(/\n/).filter(line=>line.trim()).map(line=>line.trim().split(/[,\s]+/).map(Number));
}

export function bindDeviceOptions(form,curves={},loadSchedule){
  const fields=key=>form.elements.namedItem(key);
  const update=()=>{
    for(const [selector,on] of [['[data-anchor-fields]',fields('anchor_enabled').checked],['[data-quiet-fields]',fields('quiet_enabled').checked],['[data-battery-fields]',fields('charge_enabled').checked]]){
      const group=form.querySelector(selector);group.hidden=!on;
      group.querySelectorAll('input,select,textarea').forEach(control=>{control.disabled=!on;control.required=on;});
    }
    const enabled=fields('charge_enabled').checked,method=fields('charge_method').value;
    for(const [selector,active] of [['[data-charge-linear]',method==='linear'],['[data-charge-custom]',method==='custom']]){
      const group=form.querySelector(selector);group.hidden=!active;
      group.querySelectorAll('input,textarea').forEach(control=>{control.disabled=!enabled||!active;control.required=enabled&&active;});
    }
    const profile=curves[fields('charge_chemistry').value];
    fields('charge_chemistry').setCustomValidity(enabled&&method==='chemistry'&&!profile?'Choose a supported chemistry for the chemistry profile.':'');
    form.querySelector('[data-charge-method-help]').textContent=method==='linear'?'Maps your empty/full voltages to 0–100%. Existing profiles retain this method until you change it.':method==='custom'?'Interpolates your own per-cell voltage/percentage points.':profile?`Typical ${chemistries[fields('charge_chemistry').value]} reference: ${profile[0][0]}–${profile.at(-1)[0]} V per cell.${fields('charge_chemistry').value==='li_ion'?' For conventional 4.2 V cells, not high-voltage or regulated 1.5 V cells.':fields('charge_chemistry').value==='lifepo4'?' Uses rested voltage, not the charging ceiling.':''}`:'Choose a supported chemistry.';
    const points=parseCurveText(fields('charge_curve').value);
    const valid=points.length>=2&&points.length<=32&&points.every((point,i)=>point.length===2&&point.every(Number.isFinite)&&point[0]>=.1&&point[0]<=6&&point[1]>=0&&point[1]<=100&&(!i||(point[0]>points[i-1][0]&&point[1]>points[i-1][1])))&&points[0][1]===0&&points.at(-1)[1]===100;
    fields('charge_curve').setCustomValidity(enabled&&method==='custom'&&!valid?'Enter 2–32 increasing voltage, percent pairs, starting at 0% and ending at 100%.':'');
    form.querySelector('[data-zone-field]').hidden=!(fields('anchor_enabled').checked||fields('quiet_enabled').checked);
  };
  for(const name of ['anchor_enabled','quiet_enabled','charge_enabled'])fields(name).addEventListener('change',update);
  fields('charge_method').addEventListener('change',()=>{
    if(fields('charge_method').value==='chemistry'&&fields('charge_chemistry').value==='custom')fields('charge_chemistry').value=fields('charge_method').dataset.defaultChemistry;
    if(fields('charge_method').value==='custom'&&!fields('charge_curve').value.trim())fields('charge_curve').value=(curves[fields('charge_chemistry').value]||[]).map(point=>point.join(', ')).join('\n');
    update();
  });
  fields('charge_chemistry').addEventListener('change',update);
  fields('charge_curve').addEventListener('input',update);
  fields('interval').addEventListener('input',()=>{form.querySelector('[data-interval-label]').textContent=intervalLabel(Number(fields('interval').value));});
  const status=form.querySelector('[data-schedule-status]');
  const list=form.querySelector('[data-schedule-slots]');
  let timer, revision=0;
  function requestPreview(){
    const current=++revision;
    clearTimeout(timer);
    status.textContent='Calculating planned slots…';
    list.replaceChildren();
    timer=setTimeout(async()=>{
      if(!form.isConnected)return;
      try{
        const result=await loadSchedule({interval:Number(fields('interval').value),schedule:readSchedule(form)});
        if(!form.isConnected||current!==revision)return;
        const formatter=new Intl.DateTimeFormat(undefined,{
          timeZone:result.timezone,weekday:'short',month:'short',day:'numeric',year:'numeric',
          hour:'numeric',minute:'2-digit',second:'2-digit',timeZoneName:'short'
        });
        for(const slot of result.slots){
          const item=document.createElement('li');
          item.textContent=formatter.format(slot*1000);
          list.append(item);
        }
        const wait=result.first_slot_in_seconds;
        const hours=Math.floor(wait/3600);
        const minutes=Math.floor((wait%3600)/60);
        let firstWait=intervalLabel(wait);
        if(wait>=86400){
          firstWait=`about ${(wait/86400).toLocaleString(undefined,{maximumFractionDigits:1})} days`;
        }else if(hours||minutes){
          firstWait=`about ${[hours?`${hours} h`:'',minutes?`${minutes} min`:''].filter(Boolean).join(' ')}`;
        }
        const gap=result.longest_wait_seconds;
        const longGap=gap>result.max_sleep_seconds
          ? ` A planned gap of about ${Math.round(gap/86400).toLocaleString()} days exceeds the 30-day sleep limit. The device can check in before the next scheduled image change.`
          : '';
        status.textContent=`First planned refresh in ${firstWait}. Expected device contact is shown above.${longGap}`;
      }catch(error){
        if(form.isConnected&&current===revision)status.textContent=error.message;
      }
    },250);
  }
  if(loadSchedule){
    form.addEventListener('input',event=>{
      if(event.target.name==='interval'||event.target.closest('.device-option-group')?.contains(status))requestPreview();
    });
    requestPreview();
  }
  update();
}

function readSchedule(form){
  const f=name=>form.elements.namedItem(name);
  const anchor=f('anchor_enabled').checked,quiet=f('quiet_enabled').checked;
  return {anchor_enabled:anchor,quiet_enabled:quiet,
    ...(anchor?{anchor_time:f('anchor_time').value,anchor_date:f('anchor_date').value}:{}),
    ...(quiet?{quiet_start:f('quiet_start').value,quiet_end:f('quiet_end').value}:{}),
    ...(anchor||quiet?{timezone:f('schedule_timezone').value.trim()}: {})};
}

export function readDeviceOptions(form){
  const f=name=>form.elements.namedItem(name);
  const charge=f('charge_enabled').checked;
  return {schedule:readSchedule(form),
  battery:{enabled:charge,...(charge?{chemistry:f('charge_chemistry').value,series_cells:Number(f('charge_cells').value),method:f('charge_method').value,
    ...(f('charge_method').value==='custom'?{curve:parseCurveText(f('charge_curve').value)}:{}),
    ...(f('charge_method').value==='linear'?{empty_voltage:f('charge_empty').value===''?null:Number(f('charge_empty').value),full_voltage:f('charge_full').value===''?null:Number(f('charge_full').value)}:{})}:{})}};
}
