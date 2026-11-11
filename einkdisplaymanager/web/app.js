import {viewSize,originalCompatible} from './profiles.js';
import {mqttSettingsHTML,bindMQTTForm,pollMQTT} from './mqtt.js';
import {optimizeImage} from './optimizer-client.js';
import {transferHTML, eventsHTML, transferActive} from './activity.js';
import {DITHERS, PALETTES, MATCHING} from './processing.js';
import {frameHelp, compositionHelp} from './guidance.js';
const $ = (selector, root=document) => root.querySelector(selector);
const content=$('#content'), dialog=$('#editor'), dialogContent=$('#dialog-content');
const state={deviceDetail:null,data:null, selected:new Set(), search:'', sort:'newest', optimization:null, previewURL:null, result:null};
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes=n=>n>=1048576?`${(n/1048576).toFixed(1)} MiB`:`${Math.round(n/1024)} KiB`;
const when=t=>t?new Date(t*1000).toLocaleString():'Not yet';
const asset=id=>state.data.assets.find(a=>a.id===id);
const variant=id=>state.data.variants.find(v=>v.id===id);
const thumb=(kind,id)=>`api/media/${kind}/${id}/thumbnail`;
const entryImage=(entry,device)=>{if(!entry)return '';const prepared=entry.mode==='variant',item=prepared?variant(entry.variant_id):asset(entry.asset_id),url=thumb(prepared?'variant':'asset',prepared?entry.variant_id:entry.asset_id);return `${url}?device=${device.id}&v=${item?.hash||'missing'}_${device.orientation}_${device.upside_down?1:0}`;};
const displayProfile=id=>state.data.profiles.find(p=>p.id===(id||'openpaper_l'));
const variantOrientation=v=>v?.recipe?.orientation||displayProfile(v?.profile).native_orientation;
const sizeLabel=(id,orientation)=>viewSize(displayProfile(id),orientation).join(' × ');
const orientationOptions=(id,selected)=>['portrait','landscape'].map(value=>`<option value="${value}" ${value===selected?'selected':''}>${value==='portrait'?'Portrait':'Landscape'} · ${sizeLabel(id,value)}</option>`).join('');
const imageKindLabel=kind=>({photo:'Photo',lowContrastPhoto:'Low-contrast photo',highContrastPhoto:'High-contrast photo',flatIllustration:'Illustration',lineArt:'Line art',textOrUi:'Text or interface',pixelArt:'Pixel art',unknown:'Mixed content'}[kind]||'Mixed content');
const variantFormat=v=>`${displayProfile(v.profile).name} · ${variantOrientation(v)} · ${sizeLabel(v.profile,variantOrientation(v))}`;
let noticeTimer;

function notice(message,error=false){
  const node=$('#notice');(dialog.open?dialog:$('main')).prepend(node);node.textContent=message;node.classList.toggle('error',error);node.hidden=false;
  clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>{node.hidden=true;},error?16000:7000);
}

function formStatus(node,message,result='success'){if(node?.isConnected){node.textContent=message;node.dataset.result=result;}}

async function api(path,{method='GET',data,body,headers={}}={}){
  const options={method,headers:{...headers},cache:'no-store'};
  if(method!=='GET')options.headers['X-Eink-CSRF']=state.data?.csrf||'';
  if(data!==undefined){options.body=JSON.stringify(data);options.headers['Content-Type']='application/json';}
  if(body!==undefined)options.body=body;
  const response=await fetch(`api/${path}`,options);
  if(!response.ok){let error;try{error=(await response.json()).error;}catch{error=`Request failed (${response.status}).`;}
    throw new Error(error);}
  return response.json();
}

async function refresh(){
  state.data=await api('state');
  $('#media-count').textContent=state.data.assets.length;$('#device-count').textContent=state.data.devices.length;
}

function route(){return location.hash.slice(1)||'library';}
function heading(label,title,description,action=''){
  return `<header class="page-head"><div><div class="eyebrow">${label}</div><h1>${title}</h1><p>${description}</p></div>${action}</header>`;
}

async function render(){
  if(!state.data)await refresh();
  const current=route();
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',current.startsWith(a.dataset.tab)));
  if(current.startsWith('devices/'))await deviceView(current.split('/')[1]);
  else if(current==='devices')devicesView();
  else if(current==='settings')settingsView();
  else libraryView();
}

function libraryView(){
  content.innerHTML=heading('Your collection','Media Library','One collection. Every frame. Originals stay untouched.',
    '<button class="primary" id="upload">＋ Upload images</button>')+
    `<div class="toolbar"><input id="search" type="search" aria-label="Search images" placeholder="Search your images…" value="${escape(state.search)}"><select id="sort" aria-label="Sort images"><option value="newest">Newest first</option><option value="name">Name</option><option value="used">Most used</option></select><div class="selection"><button class="small" id="select-all">Select visible</button><button class="small danger" id="bulk-delete" ${state.selected.size?'':'disabled'}>Delete selected (${state.selected.size})</button></div></div><div id="gallery"></div>`;
  $('#sort').value=state.sort;
  $('#upload').onclick=()=>$('#upload-input').click();
  $('#search').oninput=e=>{state.search=e.target.value;gallery();};
  $('#sort').onchange=e=>{state.sort=e.target.value;gallery();};
  $('#select-all').onclick=()=>{visibleAssets().forEach(a=>state.selected.add(a.id));gallery();};
  $('#bulk-delete').onclick=()=>run(async()=>{
    if(!confirm(`Delete ${state.selected.size} selected originals? Referenced images and images with saved variants will be kept.`))return;
    let count=0, failed=[];
    for(const id of [...state.selected]){try{await api(`media/asset/${id}`,{method:'DELETE'});state.selected.delete(id);count++;}catch(e){failed.push(e.message);}}
    await refresh();libraryView();notice(`${count} deleted.${failed.length?' '+failed.length+' kept: '+failed[0]:''}`,!!failed.length);
  });
  gallery();
}

function visibleAssets(){
  return state.data.assets.filter(a=>a.name.toLowerCase().includes(state.search.toLowerCase())).sort((a,b)=>state.sort==='name'?a.name.localeCompare(b.name):state.sort==='used'?b.usage-a.usage:b.created_at-a.created_at);
}

function gallery(){
  const items=visibleAssets();
  $('#gallery').innerHTML=items.length?`<div class="library-grid">${items.map(a=>{
    const variants=state.data.variants.filter(v=>v.asset_id===a.id);
    return `<article class="media-card"><button class="image-button" data-edit="${a.id}" aria-label="Open ${escape(a.name)}"><img loading="lazy" src="${thumb('asset',a.id)}" alt="${escape(a.name)}"></button><div class="card-meta"><h3 title="${escape(a.name)}">${escape(a.name)}</h3><label class="library-label"><input type="checkbox" data-select="${a.id}" aria-label="Select ${escape(a.name)}" ${state.selected.has(a.id)?'checked':''}></label></div><small>${a.width} × ${a.height} · ${a.mime.split('/')[1].toUpperCase()} · ${bytes(a.bytes)}</small><div class="card-meta"><small>${variants.length} variant${variants.length===1?'':'s'} · ${a.usage} assignment${a.usage===1?'':'s'}</small>${variants.length?'<span class="badge">Optimized</span>':''}</div></article>`;
  }).join('')}</div>`:`<div class="empty"><h2>${state.search?'No matching images':'A home for your images'}</h2><p>${state.search?'Try another name.':'Upload photos, keep the originals, and create display-ready versions for your OpenPaper frames.'}</p>${state.search?'':'<button id="empty-upload">Upload your first images</button>'}</div>`;
  $('#empty-upload')?.addEventListener('click',()=>$('#upload-input').click());
  document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>run(()=>openEditor(b.dataset.edit)));
  document.querySelectorAll('[data-select]').forEach(b=>b.onchange=()=>{b.checked?state.selected.add(b.dataset.select):state.selected.delete(b.dataset.select);updateBulk();});
  updateBulk();
}
function updateBulk(){const b=$('#bulk-delete');if(b){b.disabled=!state.selected.size;b.textContent=`Delete selected (${state.selected.size})`;}}

$('#upload-input').onchange=()=>run(async()=>{
  const files=[...$('#upload-input').files];let done=0, duplicates=0, errors=[];
  for(const file of files){
    notice(`Uploading ${done+1} of ${files.length}: ${file.name}`);
    try{const result=await api('assets',{method:'POST',body:file,headers:{'X-File-Name':encodeURIComponent(file.name.slice(0,120))}});if(result.duplicate)duplicates++;}
    catch(error){errors.push(`${file.name}: ${error.message}`);}done++;
  }
  $('#upload-input').value='';await refresh();await render();
  notice(`${files.length-errors.length} uploaded${duplicates?` (${duplicates} already in the library)`:''}.${errors.length?' '+errors.join(' '):''}`,!!errors.length);
});

function modal(title,body){
  stopWorker();
  document.documentElement.classList.add('modal-open');
  dialog.classList.remove('image-editor');
  dialogContent.innerHTML=`<div class="dialog-head"><h2 id="dialog-title">${escape(title)}</h2><button id="close-dialog" class="icon" aria-label="Close dialog">×</button></div><div class="dialog-body">${body}</div>`;
  $('#close-dialog').onclick=()=>dialog.close();
  if(!dialog.open)dialog.showModal();
  dialog.prepend($('#notice'));
}
function stopWorker(){state.optimization?.abort();state.optimization=null;state.result=null;if(state.previewURL){URL.revokeObjectURL(state.previewURL);state.previewURL=null;}}
dialog.addEventListener('close',()=>{stopWorker();document.documentElement.classList.remove('modal-open');$('main').prepend($('#notice'));});

async function openEditor(id, options={}){
  const item=asset(id);if(!item)throw new Error('Image not found.');
  const variants=state.data.variants.filter(v=>v.asset_id===id);
  const editing=options.variantId?variant(options.variantId):null;
  if(editing&&editing.asset_id!==id)throw new Error('Variant does not belong to this original.');
  const targetDevice=options.deviceId?state.data.devices.find(d=>d.id===options.deviceId):null;
  const recipeSeed=editing?.recipe||{};
  const initialProfile=displayProfile(editing?.profile||targetDevice?.profile||options.profileId||'openpaper_l');
  modal(editing?`Edit ${editing.name}`:item.name,`<form id="image-name-form" class="image-name-form"><label class="field" for="image-name">Image name<input id="image-name" name="display_name" maxlength="120" value="${escape(item.name)}" required><small>Displayed in the library and device lists. Original file: ${escape(item.filename||item.name)}</small></label><button type="submit">Save name</button><p id="image-name-status" class="save-status help" role="status" aria-live="polite"></p></form><div class="editor-layout"><div class="editor-preview"><div class="preview-stage"><img id="image-preview" src="${thumb('asset',id)}" alt="Image preview"></div><p class="help" id="preview-note">Original preview. The original file will remain unchanged.</p><div class="actions"><button class="small" id="show-original">Show original</button><button class="small" id="show-result" disabled>Show optimized</button></div></div><div class="controls"><h3>${editing?'Edit saved recipe':'Prepare a display variant'}</h3><label class="field">Target display<select id="target-profile">${(state.data.profiles||[]).map(p=>`<option value="profile:${p.id}">${escape(p.name)} · ${p.width} × ${p.height} native</option>`).join('')}${state.data.devices.map(d=>`<option value="device:${d.id}">${escape(d.name)} · ${escape(d.orientation||'portrait')}</option>`).join('')}</select></label><p class="help" id="output-dimensions">${initialProfile.width} × ${initialProfile.height} · ${initialProfile.native_orientation} · Six display colors</p><label class="field">Display orientation<select id="orientation">${orientationOptions(initialProfile.id,initialProfile.native_orientation)}</select><small>Choose how the frame is mounted. Image rotation is a separate adjustment.</small></label><label class="field">Fit<select id="fit"><option value="contain">Contain · keep the whole image</option><option value="cover">Cover · crop to fill</option></select></label><label class="field">Rotation<select id="rotation"><option value="0">0°</option><option value="90">90°</option><option value="180">180°</option><option value="270">270°</option></select></label><label class="field">Colors<select id="palette">${Object.entries(PALETTES).map(([value,p])=>`<option value="${value}">${escape(p.name)}</option>`).join('')}</select><small id="palette-tip"></small></label><label class="field">Color matching<select id="matching">${Object.entries(MATCHING).map(([value,m])=>`<option value="${value}">${escape(m.name)}</option>`).join('')}</select><small id="matching-tip"></small></label><label class="field">Dithering<select id="dither">${Object.entries(DITHERS).map(([value,d])=>`<option value="${value}">${escape(d.name)}</option>`).join('')}</select><small id="dither-tip"></small></label><label class="check"><input id="automatic" type="checkbox" checked>Automatic optimization</label><p id="automatic-summary" class="help" role="status"></p><label class="field">Automatic intent<select id="intent"><option value="natural">Natural · balanced starting point</option><option value="vivid">Vivid · stronger color emphasis</option></select><small>Applies while automatic optimization is enabled, with any selected palette.</small></label><p class="help">Automatic optimization adjusts tones and range. Matching and dithering follow your selections. A nonzero manual slider overrides only that channel; zero keeps its automatic value.</p>${['brightness','contrast','saturation'].map(k=>`<label class="field">${k[0].toUpperCase()+k.slice(1)} <output id="${k}-value">0</output><input id="${k}" type="range" min="-100" max="100" value="0"></label>`).join('')}<button id="optimize">Update full-resolution preview</button><label class="field">Variant name<input id="variant-name" maxlength="120" value="Optimized for ${escape(initialProfile.name)}"></label><button class="primary" id="save-variant" disabled>${editing?'Save changes':'Save as new variant'}</button></div></div>${compositionHelp()}<h3 class="variant-list">Saved variants</h3><div class="variant-list">${variants.map(v=>`<div class="variant-row"><img src="${thumb('variant',v.id)}" alt=""><div><strong>${escape(v.name)}</strong><br><small>${v.usage} assignments · ${bytes(v.bytes)}<br>${escape(variantFormat(v))}</small></div><button class="small" data-edit-variant="${v.id}">Edit</button><a class="button small" href="api/media/variant/${v.id}/file" download="${v.profile.replaceAll('_','-')}.bmp">Download</a><button class="small danger" data-delete-variant="${v.id}">Delete</button></div>`).join('')||'<p class="help">No saved variants yet. Try automatic optimization, then save the result.</p>'}</div><p class="help">${escape(item.original_note)} Display colors are an approximation; check the result on your frame.</p><div class="actions"><a class="button" href="api/media/asset/${id}/file" download="${escape(item.filename||item.name)}">Download original</a><button class="danger" id="delete-original">Delete original</button></div>`);
  dialog.classList.add('image-editor');
  $('#image-name-form').onsubmit=e=>{e.preventDefault();run(async()=>{
    const input=$('#image-name'), button=$('#image-name-form button'), status=$('#image-name-status');
    input.disabled=true;button.disabled=true;button.textContent='Saving…';formStatus(status,'Saving image name…','saving');
    try{const saved=await api(`assets/${id}`,{method:'PATCH',data:{name:input.value}});
      item.name=saved.name;input.value=saved.name;await refresh();await render();
      if(status.isConnected){formStatus(status,'Image name saved.');if(!editing)$('#dialog-title').textContent=saved.name;}
    }catch(error){formStatus(status,error.message,'error');throw error;}
    finally{if(button.isConnected){button.disabled=false;button.textContent='Save name';input.disabled=false;}}
  });};
  $('#fit').closest('.field').insertAdjacentHTML('afterend','<div id="crop-focus" class="stack" hidden><label class="field">Crop position · horizontal<input id="focusX" type="range" min="0" max="100" value="50"></label><label class="field">Crop position · vertical<input id="focusY" type="range" min="0" max="100" value="50"></label></div>');
  const defaults={orientation:targetDevice?.orientation||initialProfile.native_orientation,fit:'contain',rotation:0,palette:'spectra6',intent:recipeSeed.palette==='vivid'?'vivid':'natural',matching:'rgb',dither:'floyd',automatic:true,brightness:0,contrast:0,saturation:0,focusX:50,focusY:50};
  const restored={...defaults,...recipeSeed};
  for(const key of Object.keys(defaults)){const control=$(`#${key}`);if(control.type==='checkbox')control.checked=restored[key];else control.value=String(restored[key]);}
  $('#target-profile').value=targetDevice?`device:${targetDevice.id}`:`profile:${initialProfile.id}`;
  if(editing){$('#image-preview').src=thumb('variant',editing.id);$('#variant-name').value=editing.name;$('#preview-note').textContent='Saved recipe loaded from the original. Update the preview, then save changes to this variant. All its device assignments will use the updated result.';}
  let defaultVariantName=`Optimized for ${initialProfile.name}`;
  $('#target-profile').onchange=()=>{const target=$('#target-profile').value,device=target.startsWith('device:')?state.data.devices.find(d=>d.id===target.slice(7)):null,profile=displayProfile(device?device.profile:target.slice(8));$('#orientation').value=device?.orientation||profile.native_orientation;if(!editing&&$('#variant-name').value===defaultVariantName)$('#variant-name').value=`Optimized for ${profile.name}`;defaultVariantName=`Optimized for ${profile.name}`;invalidate();};
  for(const key of ['brightness','contrast','saturation'])$(`#${key}`).oninput=e=>{$(`#${key}-value`).textContent=e.target.value;invalidate();};
  for(const key of ['orientation','fit','rotation','palette','intent','matching','dither','automatic','focusX','focusY'])$(`#${key}`).onchange=()=>{$('#crop-focus').hidden=$('#fit').value!=='cover';invalidate();};
  function invalidate(){state.result=null;$('#save-variant').disabled=true;$('#show-result').disabled=true;updateDimensions();$('#preview-note').textContent='Settings changed. Update the preview before saving.';updateEditorHelp();}
  function updateDimensions(){const target=$('#target-profile').value,profile=displayProfile(target.startsWith('device:')?state.data.devices.find(d=>d.id===target.slice(7)).profile:target.slice(8));for(const option of $('#orientation').options)option.textContent=`${option.value==='portrait'?'Portrait':'Landscape'} · ${sizeLabel(profile.id,option.value)}`;$('#output-dimensions').textContent=`${sizeLabel(profile.id,$('#orientation').value)} · ${$('#orientation').value} · ${profile.name} · Six display colors`;}
  function updateEditorHelp(){$('#automatic-summary').textContent=$('#automatic').checked?'Automatic tone optimization is enabled. Update the preview to analyze this image.':'Automatic tone optimization is off. Only your manual adjustments are applied.';$('#matching-tip').textContent=MATCHING[$('#matching').value]?.use||'';$('#crop-focus').hidden=$('#fit').value!=='cover';$('#palette-tip').textContent=PALETTES[$('#palette').value]?.use||'';$('#dither-tip').textContent=DITHERS[$('#dither').value]?.use||'';for(const key of ['brightness','contrast','saturation'])$(`#${key}-value`).textContent=$(`#${key}`).value;}
  updateEditorHelp();updateDimensions();
  let source=null;
  $('#optimize').onclick=()=>run(async()=>{
    clearTimeout(noticeTimer);$('#notice').hidden=true;
    $('#optimize').disabled=true;$('#save-variant').disabled=true;$('#preview-note').textContent='Preparing full-resolution output…';
    const controls=[...$('#dialog-content').querySelectorAll('input,select')];
    controls.forEach(c=>{c.dataset.saveDisabled=String(c.disabled);c.disabled=true;});
    const job=new AbortController();state.optimization=job;
    const previewNote=$('#preview-note'),previewImage=$('#image-preview'),optimizeButton=$('#optimize');
    const current=()=>dialog.open&&state.optimization===job&&previewNote.isConnected;
    const targetValue=$('#target-profile').value;
    const targetProfile=targetValue.startsWith('device:')?state.data.devices.find(d=>d.id===targetValue.slice(7)).profile:targetValue.slice(8);
    const recipe={profile:targetProfile,intent:$('#intent').value,matching:$('#matching').value,orientation:$('#orientation').value,fit:$('#fit').value,rotation:Number($('#rotation').value),palette:$('#palette').value,dither:$('#dither').value,automatic:$('#automatic').checked,...Object.fromEntries(['brightness','contrast','saturation','focusX','focusY'].map(k=>[k,Number($(`#${k}`).value)]))};
    try{
      if(!window.Worker||!window.OffscreenCanvas)throw new Error('Use a current Chrome, Edge, Firefox, or Safari browser with OffscreenCanvas support.');
      state.result=null;$('#show-result').disabled=true;
      if(!source){const response=await fetch(`api/media/asset/${id}/source`,{signal:job.signal,cache:'no-store'});if(!response.ok){let message='Could not load the image source.';try{message=(await response.json()).error||message;}catch{}throw new Error(message);}source=await response.blob();}
      if(!current())return;
      const result=await optimizeImage({source,recipe,signal:job.signal,onProgress:message=>{if(current())previewNote.textContent=message;}});
      if(!current())return;
      previewNote.textContent='Rendering preview…';
      const nextURL=URL.createObjectURL(result.preview);
      try{const decoded=new Image();decoded.src=nextURL;await decoded.decode();if(!current())return;
        const previousURL=state.previewURL;state.previewURL=nextURL;state.result=result;previewImage.src=nextURL;if(previousURL)URL.revokeObjectURL(previousURL);
      }finally{if(state.previewURL!==nextURL)URL.revokeObjectURL(nextURL);}
      if(!current())return;
      previewNote.textContent='Full-resolution output. Physical display colors may differ.';
      const analysis=result.recipe.automaticAnalysis;$('#automatic-summary').textContent=analysis?.enabled?`Automatic applied · ${imageKindLabel(analysis.imageKind)} · ${analysis.preset||'image-specific adjustments'} · ${analysis.intent}${analysis.manualOverrides.length?` · Manual override: ${analysis.manualOverrides.join(', ')}`:''}.`:'Automatic off · Manual adjustments only.';
      $('#save-variant').disabled=false;$('#show-result').disabled=false;
    }catch(error){if(error.name==='AbortError'||!current())return;previewNote.textContent=error.message;throw error;}
    finally{if(state.optimization===job)state.optimization=null;controls.forEach(c=>{c.disabled=c.dataset.saveDisabled==='true';delete c.dataset.saveDisabled;});if(optimizeButton.isConnected)optimizeButton.disabled=false;}
  });
  $('#show-original').onclick=()=>{$('#image-preview').src=thumb('asset',id);$('#preview-note').textContent='Original preview; original bytes are preserved.';};
  $('#show-result').onclick=()=>{if(state.previewURL){$('#image-preview').src=state.previewURL;$('#preview-note').textContent='Optimized output; physical display colors may differ.';}};
  $('#save-variant').onclick=()=>run(async()=>{
    if(!state.result)return;
    const button=$('#save-variant'),savedProfile=state.result.recipe.profile;button.disabled=true;
    try{await api(`assets/${id}/variants${editing?`/${editing.id}`:''}`,{method:editing?'PUT':'POST',body:state.result.bmp,headers:{'Content-Type':'image/bmp','X-Variant-Name':encodeURIComponent($('#variant-name').value),'X-Recipe':JSON.stringify(state.result.recipe),...(editing?{'X-Variant-Version':String(editing.revision||0)}:{})}});
      await refresh();await render();await openEditor(id,{deviceId:options.deviceId,profileId:savedProfile});notice(editing?'Variant updated. All device assignments have been retained.':'Saved a new variant.');}
    finally{if(button.isConnected)button.disabled=false;}
  });
  document.querySelectorAll('[data-edit-variant]').forEach(b=>b.onclick=()=>run(()=>openEditor(id,{variantId:b.dataset.editVariant,deviceId:options.deviceId})));
  document.querySelectorAll('[data-delete-variant]').forEach(b=>b.onclick=()=>run(async()=>{
    if(!confirm('Delete this saved variant? Referenced variants cannot be deleted.'))return;
    await api(`media/variant/${b.dataset.deleteVariant}`,{method:'DELETE'});await refresh();await openEditor(id,{deviceId:options.deviceId,profileId:initialProfile.id});
  }));
  $('#delete-original').onclick=()=>run(async()=>{
    if(!confirm('Delete this original? Remove device assignments and saved variants first.'))return;
    await api(`media/asset/${id}`,{method:'DELETE'});dialog.close();await refresh();await render();notice('Original deleted.');
  });
}

function devicesView(){
  content.innerHTML=heading('Your displays','Devices','Independent image lists. Shared library.',
    '<button class="primary" id="add-device">＋ Add device</button>')+
    (state.data.devices.length?`<div class="device-grid">${state.data.devices.map(d=>{
      const e=d.entries.find(e=>e.id===d.state.last_served_entry);
      return `<article class="device-card"><div class="device-cover" data-orientation="${d.orientation||'portrait'}">${e?`<img src="${entryImage(e,d)}" alt="Last served image">`:'<span class="muted">No image served yet</span>'}</div><div class="card-meta"><h2>${escape(d.name)}</h2><span class="badge ${d.enabled&&!d.paused?'active':''}">${transferActive(d.transfer)?'Sending image':!d.enabled?'Disabled':d.paused?'Paused':'Playing'}</span></div><p class="help">${escape(d.orientation||'portrait')} · ${escape(displayProfile(d.profile).name)} · ${d.entries.filter(e=>e.enabled).length} enabled images<br>Last contact: ${when(d.state.last_image_request)}</p><div class="actions"><a class="button" href="#devices/${d.id}">Manage device</a><button class="small" data-quick-next="${d.id}" ${transferActive(d.transfer)?'disabled':''}>Next image</button></div></article>`;
    }).join('')}</div>`:'<div class="empty"><h2>Meet your first frame</h2><p>Add an OpenPaper L or OpenPaper 7, choose images from your library, and connect it using its settings URL.</p><button id="first-device">Add your first device</button></div>');
  $('#add-device').onclick=()=>deviceDialog();$('#first-device')?.addEventListener('click',()=>deviceDialog());
  document.querySelectorAll('[data-quick-next]').forEach(b=>b.onclick=()=>run(async()=>{await api(`devices/${b.dataset.quickNext}/next`,{method:'POST'});await refresh();devicesView();notice('Next image selected. The frame will fetch it on its next wake-up.');}));
}

function deviceDialog(copyFrom){
  modal(copyFrom?'Duplicate device':'Add device',`<form id="new-device" class="stack"><label class="field">Device name<input name="name" maxlength="120" required placeholder="Living room"></label><label class="field">Device type<select name="profile" ${copyFrom?'disabled':''}>${state.data.profiles.map(p=>`<option value="${p.id}" ${copyFrom&&state.data.devices.find(d=>d.id===copyFrom)?.profile===p.id?'selected':''}>${escape(p.name)} · ${p.diagonal}-inch · ${p.width} × ${p.height}</option>`).join('')}</select></label><p class="help">${copyFrom?'Copies settings and image assignments. Credentials and playback state will be independent.':'Choose the frame model. OpenPaper 7 uses 800 × 480 native pixels; OpenPaper L uses 1200 × 1600.'}</p><button class="primary">${copyFrom?'Duplicate device':'Add device'}</button></form>`);
  $('#new-device').onsubmit=e=>{e.preventDefault();run(async()=>{const d=await api('devices',{method:'POST',data:{name:new FormData(e.target).get('name'),profile:e.target.elements.profile.value,copy_from:copyFrom}});dialog.close();await refresh();location.hash=`devices/${d.id}`;});};
}

async function deviceView(id){
  const d=await api(`devices/${id}`),selected=d.entries.find(e=>e.id===d.state.selected);
  if(route()!==`devices/${id}`)return;
  state.deviceDetail=d;
  const queue=d.state.queue.map(id=>d.entries.find(e=>e.id===id)).filter(Boolean);
  content.innerHTML=`<div class="breadcrumbs"><a href="#devices">Devices</a> / ${escape(d.name)}</div>`+
    heading(displayProfile(d.profile).name,escape(d.name),'Selection changes arrive when the frame next fetches an image.',
      '<button id="refresh-device">Refresh status</button>')+
    `<div class="detail-layout"><div><section class="panel"><h2>Frame preview</h2><div id="device-frame-preview" class="device-cover" data-orientation="${d.orientation||'portrait'}">${selected?`<img src="${entryImage(selected,d)}" alt="Selected output in device mounting orientation">`:'<span class="muted">No image selected</span>'}</div><p class="help">${escape(d.orientation||'portrait')} · ${sizeLabel(d.profile,d.orientation)} viewing area. ${d.upside_down?'Mounted view with 180° delivery correction. ':''}Selected output; the frame fetches it on wake-up. Original-mode fitting and colors are approximate.</p></section><section class="panel"><div class="page-head"><div><h2>Image list</h2><p id="device-list-position">${d.entries.length} entries · Cycle ${d.state.cycle}</p></div><button class="primary" id="add-images">＋ Add images</button></div><p class="help">Arrange the base order below. With shuffle enabled, a new order is made only after the current cycle finishes.</p><ol class="queue">${d.entries.map((e,index)=>`<li draggable="true" data-entry="${e.id}" class="${e.id===d.state.selected?'current':''}"><img src="${entryImage(e,d)}" alt=""><div class="entry-text"><strong>${index+1}. ${escape(asset(e.asset_id)?.name||'Unavailable image')}</strong><small>${e.mode==='variant'?escape(variant(e.variant_id)?.name||'Saved variant'):'Original · processed by frame'}<span data-selected-tag="${e.id}" ${e.id===d.state.selected?'':'hidden'}> · Selected</span><span data-served-tag="${e.id}" ${e.id===d.state.last_served_entry?'':'hidden'}> · Last served</span></small></div><label class="check"><input data-enabled="${e.id}" type="checkbox" aria-label="Enable image ${index+1}" ${e.enabled?'checked':''}></label><div class="queue-controls"><button data-up="${index}" aria-label="Move image ${index+1} up" ${index===0?'disabled':''}>↑</button><button data-down="${index}" aria-label="Move image ${index+1} down" ${index===d.entries.length-1?'disabled':''}>↓</button><button data-choose="${e.id}" ${e.enabled?'':'disabled'}>Show next</button><button data-remove="${e.id}" aria-label="Remove image ${index+1}">×</button></div></li>`).join('')||'<li><p class="help">Add originals or saved variants from the Media Library.</p></li>'}</ol><div class="actions"><button id="previous">Previous</button><button id="pause">${d.paused?'Resume':'Pause'}</button><button id="next">Next image</button></div></section><section class="panel"><h2>Transfer status</h2><div id="transfer-status"></div><p id="activity-poll-status" class="help" role="status">Live status updates every 2 seconds.</p></section><section class="panel"><h2>Device log</h2><p class="help">Last 100 events for this device, newest first. Entries survive add-on restarts; URLs, credentials, and raw request data are not recorded.</p><div class="device-event-scroll"><table class="device-events"><thead><tr><th>Time</th><th>Event</th><th>HTTP</th><th>Transfer</th></tr></thead><tbody id="device-events"></tbody></table></div></section><section class="panel"><h2>Playback status</h2><div class="facts"><div><dt>Estimated battery · activity only</dt><dd id="device-battery-estimate">${d.health?.battery_estimate==null?'Unknown':d.health.battery_estimate+'%'}</dd></div><div><dt>Image fetch status</dt><dd id="device-fetch-health">${escape(d.health?.frame_status||'waiting')}</dd></div><div><dt>Selected image</dt><dd id="device-selected-name">${escape(selected?asset(selected.asset_id)?.name:'Placeholder')}</dd></div><div><dt>Last completed delivery</dt><dd id="device-last-served">${when(d.state.last_served_at)}</dd></div><div><dt>Next eligible change</dt><dd id="device-next-change">${d.paused?'Paused':when(d.state.deadline)}</dd></div><div><dt>Settings last requested</dt><dd id="device-last-settings">${when(d.state.last_settings_request)}</dd></div></div><p id="device-last-error" class="help">${escape(d.state.last_error||'HTTP delivery does not confirm what is physically visible on the screen.')}</p><p class="help">Battery is an activity estimate: 100% after successful HTTP image delivery, 0% when an expected fetch is overdue. It does not measure charge. WiFi issues or a powered-off frame can also cause 0%.</p><details><summary>Current playback queue</summary><ol>${queue.map(e=>`<li>${escape(asset(e.asset_id)?.name)}</li>`).join('')}</ol></details></section></div><div><section class="panel"><h2>Device settings</h2><form id="device-form" class="stack"><label class="field">Name<input name="name" maxlength="120" value="${escape(d.name)}" required></label><label class="field">Mounting orientation<select name="orientation">${orientationOptions(d.profile,d.orientation)}</select><small>Controls previews. Use a matching variant; changing mounting does not recrop existing images.</small></label><label class="check"><input name="upside_down" type="checkbox" ${d.upside_down?'checked':''}>Mounted upside down · correct by 180°</label><small>Automatically rotates delivery for this device and shows the corrected mounted view. Shared variants stay unchanged. Sensor rotation is disabled while correction is on; original JPEGs need another encoding pass.</small><label class="field">Update interval (seconds)<input name="interval" type="number" min="60" max="2592000" value="${d.interval}" required><small>60 seconds to 30 days. Early fetches retain the current selection.</small></label><label class="check"><input name="enabled" type="checkbox" ${d.enabled?'checked':''}>Device enabled</label><label class="check"><input name="shuffle" type="checkbox" ${d.shuffle?'checked':''}>Shuffle after a complete cycle</label><label class="check"><input name="motionWakeup" type="checkbox" ${d.settings.motionWakeup?'checked':''}>Wake on movement</label><label class="check"><input name="autoRotation" type="checkbox" ${d.settings.autoRotation&&!d.upside_down?'checked':''} ${d.upside_down?'disabled':''}>Automatic sensor rotation</label><label class="check"><input name="chargerMode" type="checkbox" ${d.settings.chargerMode?'checked':''}>Charge NiMH batteries over USB</label><small>Enable charging only with NiMH batteries. Leave off for other battery types.</small><button class="primary" id="save-device-settings">Save settings</button><p id="device-save-status" class="save-status help" role="status" aria-live="polite"></p></form></section><section class="panel"><h2>Connect your frame</h2>${d.urls.image?`<label class="field">Settings JSON URL<div class="url-row"><input readonly id="settings-url" value="${escape(d.urls.settings)}"><button class="small" data-copy="settings-url">Copy</button></div></label><label class="field">Fixed image URL<div class="url-row"><input readonly id="image-url" value="${escape(d.urls.image)}"><button class="small" data-copy="image-url">Copy</button></div></label><p class="help">Set the Settings-JSON-URL in the offline firmware Web UI. Both URLs stay fixed as images change. Keep these credential-bearing URLs private.</p><details><summary>Settings JSON preview</summary><pre>${escape(JSON.stringify(d.settings_json,null,2))}</pre></details>`:'<p class="help">Set the LAN base URL in <a href="#settings">Settings</a> to generate your device URLs.</p>'}${frameHelp(displayProfile(d.profile))}<div class="actions"><button class="small" id="rotate-token">Rotate access token</button><button class="small" id="duplicate-device">Duplicate device</button><button class="small danger" id="remove-device">Remove device</button></div></section></div></div>`;
  paintDeviceActivity(d.id,{transfer:d.transfer,events:d.events,state:d.state,paused:d.paused},d);
  $('#refresh-device').onclick=()=>run(async()=>{await refresh();await deviceView(id);});
  $('#add-images').onclick=()=>picker(d);
  for(const action of ['next','previous'])$(`#${action}`).onclick=()=>run(async()=>{await api(`devices/${id}/${action}`,{method:'POST'});await refresh();await deviceView(id);notice('Selection updated. Waiting for the frame’s next fetch.');});
  $('#pause').onclick=()=>saveDevice(d,{paused:!d.paused});
  const mountingForm=$('#device-form');
  mountingForm.upside_down.onchange=()=>{mountingForm.autoRotation.disabled=mountingForm.upside_down.checked;if(mountingForm.upside_down.checked)mountingForm.autoRotation.checked=false;};
  $('#device-form').onsubmit=e=>{e.preventDefault();const f=e.target;const settings={motionWakeup:f.motionWakeup.checked,autoRotation:f.autoRotation.checked,chargerMode:f.chargerMode.checked};let confirm_nimh=false;
    if(settings.chargerMode&&!d.settings.chargerMode){confirm_nimh=confirm('Confirm this frame contains NiMH rechargeable batteries. Charging other battery types is unsafe.');if(!confirm_nimh)return;}
    saveDevice(d,{name:f.elements.namedItem('name').value,orientation:f.elements.namedItem('orientation').value,upside_down:f.upside_down.checked,interval:Number(f.interval.value),enabled:f.enabled.checked,shuffle:f.shuffle.checked,settings,confirm_nimh},true);};
  const reorder=async(from,to)=>{const entries=[...d.entries];const [entry]=entries.splice(from,1);entries.splice(to,0,entry);await saveDevice(d,{entries});};
  document.querySelectorAll('[data-up]').forEach(b=>b.onclick=()=>reorder(Number(b.dataset.up),Number(b.dataset.up)-1));
  document.querySelectorAll('[data-down]').forEach(b=>b.onclick=()=>reorder(Number(b.dataset.down),Number(b.dataset.down)+1));
  document.querySelectorAll('[data-enabled]').forEach(b=>b.onchange=()=>saveDevice(d,{entries:d.entries.map(e=>e.id===b.dataset.enabled?{...e,enabled:b.checked}:e)}));
  document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>saveDevice(d,{entries:d.entries.filter(e=>e.id!==b.dataset.remove)}));
  document.querySelectorAll('[data-choose]').forEach(b=>b.onclick=()=>run(async()=>{await api(`devices/${id}/choose`,{method:'POST',data:{entry_id:b.dataset.choose}});await refresh();await deviceView(id);}));
  let drag=null;
  document.querySelectorAll('[data-entry]').forEach(row=>{row.ondragstart=e=>{drag=d.entries.findIndex(x=>x.id===row.dataset.entry);e.dataTransfer.effectAllowed='move';};row.ondragover=e=>e.preventDefault();row.ondrop=e=>{e.preventDefault();if(drag!==null)reorder(drag,d.entries.findIndex(x=>x.id===row.dataset.entry));drag=null;};});
  document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>run(async()=>{const input=$(`#${b.dataset.copy}`);if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(input.value);notice('URL copied.');}else{input.focus();input.select();notice('URL selected. Copy it using your browser.');}}));
  $('#rotate-token').onclick=()=>run(async()=>{if(!confirm('Rotate this device’s access token? Its existing URLs will stop working. Update the settings URL on the frame afterward.'))return;await api(`devices/${id}/rotate-token`,{method:'POST'});await refresh();await deviceView(id);notice('Token rotated. Reconfigure the settings URL on your frame.');});
  $('#duplicate-device').onclick=()=>deviceDialog(id);
  $('#remove-device').onclick=()=>run(async()=>{if(!confirm('Remove this device and its playback state? Shared library images will be retained.'))return;await api(`devices/${id}`,{method:'DELETE'});await refresh();location.hash='devices';});
}

function paintDeviceActivity(id,activity,detail=state.deviceDetail){
  if(route()!==`devices/${id}`||!$('#transfer-status'))return;
  const transfer=activity.transfer||{status:'idle'};
  $('#transfer-status').innerHTML=transferHTML(transfer,asset(transfer.asset_id)?.name||'');
  const body=$('#device-events'), events=activity.events||[];
  const signature=events.length?`${events.length}:${events.at(-1).id}`:'empty';
  if(body.dataset.signature!==signature){const scroll=body.closest('.device-event-scroll'),top=scroll.scrollTop;body.innerHTML=eventsHTML(events,entryId=>{const entry=detail?.entries.find(e=>e.id===entryId);return entry?asset(entry.asset_id)?.name:null;});body.dataset.signature=signature;scroll.scrollTop=top;}
  const active=transferActive(transfer);
  for(const button of document.querySelectorAll('#next,#previous,[data-choose],#rotate-token,#remove-device')){
    if(active){if(button.dataset.transferDisabled===undefined)button.dataset.transferDisabled=String(button.disabled);button.disabled=true;button.title='Wait for the active image transfer to finish.';}
    else if(button.dataset.transferDisabled!==undefined){button.disabled=button.dataset.transferDisabled==='true';delete button.dataset.transferDisabled;button.removeAttribute('title');}
  }
  if(activity.state&&detail){const current=activity.state, entry=detail.entries.find(e=>e.id===current.selected);
    const health=activity.health||detail.health;if(health){$('#device-battery-estimate').textContent=health.battery_estimate==null?'Unknown':`${health.battery_estimate}%`;$('#device-fetch-health').textContent=health.frame_status;}
    $('#device-selected-name').textContent=entry?asset(entry.asset_id)?.name||'Unavailable image':'Placeholder';
    $('#device-last-served').textContent=when(current.last_served_at);
    $('#device-last-settings').textContent=when(current.last_settings_request);
    $('#device-next-change').textContent=activity.paused?'Paused':when(current.deadline);
    $('#device-last-error').textContent=current.last_error?`${active?'Previous transfer issue':'Last transfer issue'}: ${current.last_error}`:'HTTP delivery does not confirm what is physically visible on the screen.';
    $('#device-list-position').textContent=`${detail.entries.length} entries · Cycle ${current.cycle}`;
    document.querySelectorAll('[data-entry]').forEach(row=>row.classList.toggle('current',row.dataset.entry===current.selected));
    document.querySelectorAll('[data-selected-tag]').forEach(node=>{node.hidden=node.dataset.selectedTag!==current.selected;});
    document.querySelectorAll('[data-served-tag]').forEach(node=>{node.hidden=node.dataset.servedTag!==current.last_served_entry;});
    const preview=$('#device-frame-preview'),url=entryImage(entry,detail);
    if(preview.dataset.source!==url){preview.innerHTML=url?`<img src="${url}" alt="Selected output in device mounting orientation">`:'<span class="muted">No image selected</span>';preview.dataset.source=url;}
  }
}
let activityPolling=false;
async function pollDeviceActivity(){
  const current=route();if(activityPolling||document.hidden||dialog.open||!current.startsWith('devices/'))return;
  const id=current.split('/')[1];activityPolling=true;
  try{const activity=await api(`devices/${id}/status`);if(route()!==current||dialog.open)return;paintDeviceActivity(id,activity);$('#activity-poll-status').textContent='Live status updates every 2 seconds.';}
  catch{if(route()===current&&$('#activity-poll-status'))$('#activity-poll-status').textContent='Live status is unavailable. Use Refresh status or reload the page.';}
  finally{activityPolling=false;}
}

async function saveDevice(d,changes,feedback=false){return run(async()=>{
  const button=feedback?$('#save-device-settings'):null;
  const status=feedback?$('#device-save-status'):null;
  const controls=feedback?[...$('#device-form').querySelectorAll('input,select')]:[];
  const scrollY=window.scrollY;
  if(button){button.disabled=true;button.textContent='Saving…';formStatus(status,'Saving settings…','saving');controls.forEach(c=>{c.dataset.saveDisabled=String(c.disabled);c.disabled=true;});}
  try{await api(`devices/${d.id}`,{method:'PUT',data:{...changes,modified:d.modified}});await refresh();await deviceView(d.id);
    if(feedback&&route()===`devices/${d.id}`){window.scrollTo(0,scrollY);formStatus($('#device-save-status'),'Settings saved. The frame will apply them on its next wake-up.');}
  }catch(error){formStatus(status,error.message,'error');throw error;}
  finally{if(button?.isConnected){button.disabled=false;button.textContent='Save settings';controls.forEach(c=>{c.disabled=c.dataset.saveDisabled==='true';delete c.dataset.saveDisabled;});}}
});}

function picker(device){
  modal('Add images to '+device.name,`<p class="help">Choose an original or a saved variant for each image. Variants are prepared for a model and mounting orientation. Use Prepare for this device to start from the right target; a different mounting can show a sideways result.</p><div class="picker-grid">${state.data.assets.map(a=>{
    const variants=state.data.variants.filter(v=>v.asset_id===a.id&&v.profile===device.profile);
    const compatible=originalCompatible(a,device.profile,state.data.profiles);
    return `<div class="picker-card"><img src="${thumb('asset',a.id)}" alt=""><strong>${escape(a.name)}</strong><select data-representation="${a.id}" aria-label="Image version for ${escape(a.name)}"><option value="original" ${compatible?'':'disabled'}>Original ${compatible?'':'(not compatible)'}</option>${variants.map((v,index)=>`<option value="${v.id}" ${!compatible&&index===0?'selected':''}>${escape(v.name)} · ${escape(variantFormat(v))}${variantOrientation(v)!==(device.orientation||'portrait')?' · different mounting':''}</option>`).join('')}</select><button data-prepare-asset="${a.id}">Prepare for this device</button><button data-add-asset="${a.id}" ${compatible||variants.length?'':'disabled'}>Add to device</button>${!compatible&&!variants.length?'<small>Create a variant in the Media Library first.</small>':''}</div>`;
  }).join('')||'<p class="help">Upload images in the Media Library first.</p>'}</div>`);
  document.querySelectorAll('[data-prepare-asset]').forEach(b=>b.onclick=()=>run(()=>openEditor(b.dataset.prepareAsset,{deviceId:device.id})));
  document.querySelectorAll('[data-add-asset]').forEach(b=>b.onclick=()=>run(async()=>{
    b.disabled=true;try{const representation=$(`[data-representation="${b.dataset.addAsset}"]`).value;
      const latest=await api(`devices/${device.id}`);
      const entry={asset_id:b.dataset.addAsset,mode:representation==='original'?'original':'variant',variant_id:representation==='original'?null:representation,enabled:true};
      await api(`devices/${device.id}`,{method:'PUT',data:{entries:[...latest.entries,entry],modified:latest.modified}});
      await refresh();await deviceView(device.id);notice('Image added to the device list.');b.textContent='Added · add again';
    }finally{b.disabled=false;}
  }));
}

function suggestedBaseURL(){
  const network=state.data.network||{};
  const current=location.hostname;
  const octets=current.split('.').map(Number);
  const localIPv4=octets.length===4&&octets.every(n=>Number.isInteger(n)&&n>=0&&n<=255)&&
    (octets[0]===10||octets[0]===192&&octets[1]===168||octets[0]===172&&octets[1]>=16&&octets[1]<=31);
  const host=localIPv4||current.endsWith('.local')?current:network.host||'homeassistant.local';
  return `http://${host}:${network.device_port||8098}`;
}

function settingsView(){
  content.innerHTML=heading('Local connections','Settings','Connect frames to your Home Assistant host, without a cloud.')+
    `<section class="panel"><h2>Device endpoint</h2><form id="global-form" class="stack"><label class="field">LAN base URL<input id="base-url" type="url" placeholder="http://192.168.1.10:8098" value="${escape(state.data.settings.base_url||suggestedBaseURL())}" ${state.data.base_url_locked?'readonly':''} required><small>${state.data.settings.base_url?'Saved address.':'Suggested address; confirm that your frame can reach this host, then save it.'} Device URLs must fit within 128 characters.</small></label>${state.data.base_url_locked?'<p class="help">This URL is set in the Home Assistant add-on configuration.</p>':'<button class="primary">Save LAN base URL</button>'}</form><p class="help"><strong>Device port: ${state.data.network?.device_port===null?'disabled':state.data.network?.device_port||8098}</strong>${state.data.network?.detected?' (detected host mapping)':' (default; confirm in Home Assistant)'}. To change it, open the add-on’s Configuration → Network in Home Assistant, change the host port for 8098/tcp, and restart the add-on. Then save the matching port in this LAN base URL. Editing the URL alone does not change the port mapping.</p><p class="help">Restrict allowed_networks in the add-on configuration to your frame network. Device endpoints require a per-device token. They expose images and settings only; management stays behind Home Assistant Ingress. HTTP does not encrypt images or credentials, and the firmware does not verify HTTPS certificates.</p></section>${mqttSettingsHTML(state.data.mqtt)}<section class="panel"><h2>Storage</h2><p>${bytes(state.data.storage_bytes)} used of ${bytes(state.data.storage_limit)}</p><div class="storage-meter"><progress max="${state.data.storage_limit}" value="${state.data.storage_bytes}" aria-label="Storage used"></progress></div><p class="help">Originals, saved variants, settings, and playback progress live in the add-on’s persistent data. Include this add-on in Home Assistant backups. Only unreferenced crash leftovers are cleaned automatically.</p></section><section class="panel"><h2>Frame setup</h2><ol class="help"><li>Back up device certificates before changing firmware.</li><li>Use the upstream Web UI to install offline firmware and configure WiFi.</li><li>Add a device here, choose its images, and copy its settings JSON URL.</li><li>Set that URL in the frame’s Settings-JSON-URL field. URL-download mode is needed for timed wake-ups.</li><li>If the Web UI reports “Failed to fetch”, allow local network access in its browser site permissions and check the URL and port. Some browsers still block HTTPS-to-HTTP previews; the frame itself is not subject to CORS. Save the settings URL on the frame even if the browser preview is blocked.</li></ol><div class="actions"><a class="button" href="https://paperlesspaper.github.io/paperlesspaper-firmware-offline/" target="_blank" rel="noreferrer">Open Web UI & flasher ↗</a><a href="https://github.com/paperlesspaper/paperlesspaper-firmware-offline" target="_blank" rel="noreferrer">Offline firmware source ↗</a></div><p class="help">E-Ink Display Manager ${state.data.version} · Experimental. Physical hardware acceptance is required before a stable release.</p></section>`;
  bindMQTTForm(api,state.data.mqtt);
  $('#global-form').onsubmit=e=>{e.preventDefault();run(async()=>{await api('settings',{method:'PUT',data:{base_url:$('#base-url').value}});await refresh();settingsView();notice('LAN base URL saved. Reconfigure existing frames if their settings URL changed.');});};
}

async function run(action){try{return await action();}catch(error){notice(error.message||'The operation failed. Refresh and try again.',true);}}
window.addEventListener('hashchange',()=>run(render));
setInterval(()=>{if(!dialog.open&&route()==='devices'&&!state.search&&!state.selected.size)run(async()=>{await refresh();await render();});},15000);
run(render);
setInterval(pollDeviceActivity,2000);

setInterval(()=>pollMQTT(api),5000);
