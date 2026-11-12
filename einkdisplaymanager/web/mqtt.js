const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=selector=>document.querySelector(selector);

export function mqttSettingsHTML(config){
  return `<section class="panel"><h2>MQTT & Home Assistant</h2><p class="help">The add-on publishes your registered frames as Home Assistant MQTT devices. Frames continue fetching images over HTTP; they do not need MQTT firmware.</p>
  <form id="mqtt-form" class="stack">
    <label class="check"><input name="enabled" type="checkbox" ${config.enabled?'checked':''}>Enable MQTT</label>
    <div class="form-grid"><label class="field">Broker<input name="broker" aria-label="Broker" value="${escape(config.broker)}" placeholder="192.168.1.10" maxlength="253" autocomplete="off"><small>Hostname or IP address, without a URL scheme.</small></label>
    <label class="field">MQTT port<input name="port" type="number" min="1" max="65535" value="${config.port}" required></label>
    <label class="field">MQTT username<input name="username" value="${escape(config.username)}" maxlength="253" autocomplete="off"></label>
    <label class="field">MQTT password<input name="password" aria-label="MQTT password" type="password" maxlength="512" autocomplete="new-password" placeholder="${config.password_set?'Saved password · leave blank to keep':'Optional'}"><small>The saved password is never returned to your browser.</small></label></div>
    <label class="check"><input name="clear_password" type="checkbox">Clear saved MQTT password</label>
    <label class="check"><input name="tls" type="checkbox" ${config.tls?'checked':''}>Use TLS with certificate verification</label>
    <label class="check"><input name="discovery" type="checkbox" ${config.discovery?'checked':''}>Home Assistant discovery</label>
    <label class="field">Discovery prefix<input name="discovery_prefix" aria-label="Discovery prefix" value="${escape(config.discovery_prefix)}" maxlength="128" required><small>Usually homeassistant. Home Assistant must use the same broker and discovery prefix.</small></label>
    <label class="check"><input name="discovery_retain" type="checkbox" ${config.discovery_retain?'checked':''}>Retain discovery messages</label>
    <label class="field">Image-fetch grace period (seconds)<input name="grace_seconds" aria-label="Image-fetch grace period (seconds)" type="number" min="30" max="3600" step="1" value="${config.grace_seconds}" required><small>Tolerance after the expected image fetch before the simulated battery starts to decline.</small></label>
    <label class="field">Activity battery decline period (seconds)<input name="battery_decay_seconds" aria-label="Activity battery decline period (seconds)" type="number" min="0" max="2592000" step="1" value="${config.battery_decay_seconds}" required><small>0 (default) switches directly to 0% after the grace period. Otherwise, the estimate falls gradually from 100% to 0% over this many seconds. Examples: 300 = 5 minutes; 86400 = 24 hours. Image update overdue turns on only at 0%; the fetch status is late during the decline. Changes immediately recalculate existing estimates and can raise them again.</small></label>
    <p class="help">MQTT exposes one Battery Level percentage: calibrated voltage when available, otherwise this activity estimate. Image update overdue remains independent. These timing settings apply to all devices, including when MQTT is disabled. A completed image response, including 304, restores 100%. This is an activity estimate, not a battery measurement. WiFi loss or a powered-off frame can cause the same result. New frames stay unknown until their first completed image fetch or the full alarm deadline is missed. Paused, disabled, and empty image lists do not trigger overdue alerts. Availability tracks this add-on's MQTT connection; the estimate remains visible when a frame is overdue.</p>
    <button class="primary" id="save-mqtt">Save MQTT settings</button><p id="mqtt-save-status" class="save-status help" role="status" aria-live="polite"></p>
  </form><p id="mqtt-connection-status" class="help" role="status" aria-live="polite"></p></section>`;
}

function paintStatus(config){
  const node=$('#mqtt-connection-status');if(!node)return;
  node.textContent=`MQTT: ${config.status}.${config.error?' '+config.error:''}${config.pending_cleanup?` Retained-topic cleanup pending for ${config.pending_cleanup} previous broker connection(s).`:''}`;
}

export function bindMQTTForm(api,config,onSaved=()=>{}){
  const form=$('#mqtt-form');if(!form)return;
  paintStatus(config);
  form.elements.tls.onchange=()=>{const port=form.elements.port;if(form.elements.tls.checked&&port.value==='1883')port.value='8883';else if(!form.elements.tls.checked&&port.value==='8883')port.value='1883';};
  form.onsubmit=async event=>{
    event.preventDefault();const button=$('#save-mqtt'),status=$('#mqtt-save-status');
    const data=Object.fromEntries(['enabled','tls','discovery','discovery_retain','clear_password'].map(key=>[key,form.elements[key].checked]));
    for(const key of ['broker','username','discovery_prefix'])data[key]=form.elements[key].value;
    for(const key of ['port','grace_seconds','battery_decay_seconds'])data[key]=Number(form.elements[key].value);
    if(form.elements.password.value)data.password=form.elements.password.value;
    const controls=[...form.elements],disabled=controls.map(node=>node.disabled);
    controls.forEach(node=>{node.disabled=true;});button.textContent='Saving…';status.textContent='Saving MQTT settings…';status.dataset.result='saving';
    try{const saved=await api('mqtt',{method:'PUT',data});onSaved(saved);if(!form.isConnected)return;
      status.textContent='MQTT settings saved. Connection status updates below.';status.dataset.result='success';
      form.elements.password.value='';form.elements.clear_password.checked=false;
      form.elements.password.placeholder=saved.password_set?'Saved password · leave blank to keep':'Optional';paintStatus(saved);
    }catch(error){if(status.isConnected){status.textContent=error.message;status.dataset.result='error';}}
    finally{if(form.isConnected){controls.forEach((node,index)=>{node.disabled=disabled[index];});button.textContent='Save MQTT settings';}}
  };
}

let polling=false;
export async function pollMQTT(api){
  const node=$('#mqtt-connection-status');if(polling||!node||document.hidden)return;
  polling=true;
  try{const config=await api('mqtt');if(node.isConnected)paintStatus(config);}
  catch{if(node.isConnected)node.textContent='MQTT status is unavailable. Reload this page to retry.';}
  finally{polling=false;}
}
