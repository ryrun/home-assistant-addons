import {DITHERS, PALETTES} from './processing.js';
import {frameHelp, compositionHelp} from './guidance.js';
const $ = (selector, root=document) => root.querySelector(selector);
const content=$('#content'), dialog=$('#editor'), dialogContent=$('#dialog-content');
const state={data:null, selected:new Set(), search:'', sort:'newest', worker:null, previewURL:null, result:null};
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes=n=>n>=1048576?`${(n/1048576).toFixed(1)} MiB`:`${Math.round(n/1024)} KiB`;
const when=t=>t?new Date(t*1000).toLocaleString():'Not yet';
const asset=id=>state.data.assets.find(a=>a.id===id);
const variant=id=>state.data.variants.find(v=>v.id===id);
const thumb=(kind,id)=>`api/media/${kind}/${id}/thumbnail`;
const entryImage=(e,orientation)=>{const url=e?.mode==='variant'?thumb('variant',e.variant_id):e?thumb('asset',e.asset_id):'';return url&&orientation?`${url}?orientation=${orientation}`:url;};
const variantOrientation=v=>v?.recipe?.orientation||'portrait';
const variantFormat=v=>{const profile=state.data.profiles?.find(p=>p.id===v.profile);const w=profile?.width||v.width,h=profile?.height||v.height;return `${profile?.name||v.profile} · ${variantOrientation(v)} · ${variantOrientation(v)==='landscape'?h:w} × ${variantOrientation(v)==='landscape'?w:h}`;};
let noticeTimer;

function notice(message,error=false){
  const node=$('#notice');node.textContent=message;node.classList.toggle('error',error);node.hidden=false;
  clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>{node.hidden=true;},error?16000:7000);
}

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
  }).join('')}</div>`:`<div class="empty"><h2>${state.search?'No matching images':'A home for your images'}</h2><p>${state.search?'Try another name.':'Upload photos, keep the originals, and create display-ready versions for your OpenPaper L.'}</p>${state.search?'':'<button id="empty-upload">Upload your first images</button>'}</div>`;
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
}
function stopWorker(){state.worker?.terminate();state.worker=null;state.result=null;if(state.previewURL){URL.revokeObjectURL(state.previewURL);state.previewURL=null;}}
dialog.addEventListener('close',()=>{stopWorker();document.documentElement.classList.remove('modal-open');});

async function openEditor(id, options={}){
  const item=asset(id);if(!item)throw new Error('Image not found.');
  const variants=state.data.variants.filter(v=>v.asset_id===id);
  const editing=options.variantId?variant(options.variantId):null;
  if(editing&&editing.asset_id!==id)throw new Error('Variant does not belong to this original.');
  const targetDevice=options.deviceId?state.data.devices.find(d=>d.id===options.deviceId):null;
  const recipeSeed=editing?.recipe||{};
  modal(editing?`Edit ${editing.name}`:item.name,`<div class="editor-layout"><div class="editor-preview"><div class="preview-stage"><img id="image-preview" src="${thumb('asset',id)}" alt="Image preview"></div><p class="help" id="preview-note">Original preview. The original file will remain unchanged.</p><div class="actions"><button class="small" id="show-original">Show original</button><button class="small" id="show-result" disabled>Show optimized</button></div></div><div class="controls"><h3>${editing?'Edit saved recipe':'Prepare a display variant'}</h3><label class="field">Target display<select id="target-profile">${(state.data.profiles||[]).map(p=>`<option value="profile:${p.id}">${escape(p.name)} · ${p.width} × ${p.height} native</option>`).join('')}${state.data.devices.map(d=>`<option value="device:${d.id}">${escape(d.name)} · ${escape(d.orientation||'portrait')}</option>`).join('')}</select></label><p class="help" id="output-dimensions">1200 × 1600 · Portrait · Six display colors</p><label class="field">Display orientation<select id="orientation"><option value="portrait">Portrait · 1200 × 1600</option><option value="landscape">Landscape · 1600 × 1200</option></select><small>Choose how the frame is mounted. Image rotation is a separate adjustment.</small></label><label class="field">Fit<select id="fit"><option value="contain">Contain · keep the whole image</option><option value="cover">Cover · crop to fill</option></select></label><label class="field">Rotation<select id="rotation"><option value="0">0°</option><option value="90">90°</option><option value="180">180°</option><option value="270">270°</option></select></label><label class="field">Colors<select id="palette">${Object.entries(PALETTES).map(([value,p])=>`<option value="${value}">${escape(p.name)}</option>`).join('')}</select><small id="palette-tip"></small></label><label class="field">Color matching<select id="matching"><option value="rgb">RGB · predictable baseline</option><option value="lab">Perceptual LAB · compare on frame</option></select></label><div class="field"><div class="field-heading"><label for="dither">Dithering</label><button id="dither-help-toggle" class="help-button" type="button" aria-label="About dithering methods" aria-expanded="false" aria-controls="dither-help">?</button></div><select id="dither">${Object.entries(DITHERS).map(([value,d])=>`<option value="${value}">${escape(d.name)}</option>`).join('')}</select><small id="dither-tip"></small></div><div id="dither-help" class="method-help" hidden><h3>Choosing a dithering method</h3><p>These methods work with the six display colors. The best result depends on the image, palette, and panel; compare on your actual frame. Calibrated library palettes can matter as much as the diffusion method.</p>${Object.entries(DITHERS).map(([value,d])=>`<p><strong>${escape(d.name)}</strong><br>${escape(d.use)}</p>`).join('')}<a href="https://github.com/paperlesspaper/epdoptimize" target="_blank" rel="noreferrer">Optimizer documentation ↗</a></div><label class="check"><input id="automatic" type="checkbox" checked>Automatic optimization</label>${['brightness','contrast','saturation'].map(k=>`<label class="field">${k[0].toUpperCase()+k.slice(1)} <output id="${k}-value">0</output><input id="${k}" type="range" min="-100" max="100" value="0"></label>`).join('')}<button id="optimize">Update full-resolution preview</button><label class="field">Variant name<input id="variant-name" maxlength="120" value="Optimized for OpenPaper L"></label><button class="primary" id="save-variant" disabled>${editing?'Save new revision':'Save as new variant'}</button></div></div>${compositionHelp()}<h3 class="variant-list">Saved variants</h3><div class="variant-list">${variants.map(v=>`<div class="variant-row"><img src="${thumb('variant',v.id)}" alt=""><div><strong>${escape(v.name)}</strong><br><small>${v.usage} assignments · ${bytes(v.bytes)}<br>${escape(variantFormat(v))}</small></div><button class="small" data-edit-variant="${v.id}">Edit</button><a class="button small" href="api/media/variant/${v.id}/file" download="openpaper-l.bmp">Download</a><button class="small danger" data-delete-variant="${v.id}">Delete</button></div>`).join('')||'<p class="help">No saved variants yet. Try automatic optimization, then save the result.</p>'}</div><p class="help">${escape(item.original_note)} Display colors are an approximation; check the result on your frame.</p><div class="actions"><a class="button" href="api/media/asset/${id}/file" download="${escape(item.name)}">Download original</a><button class="danger" id="delete-original">Delete original</button></div>`);
  dialog.classList.add('image-editor');
  $('#fit').closest('.field').insertAdjacentHTML('afterend','<div id="crop-focus" class="stack" hidden><label class="field">Crop position · horizontal<input id="focusX" type="range" min="0" max="100" value="50"></label><label class="field">Crop position · vertical<input id="focusY" type="range" min="0" max="100" value="50"></label></div>');
  const defaults={orientation:targetDevice?.orientation||'portrait',fit:'contain',rotation:0,palette:'natural',matching:'rgb',dither:'floyd',automatic:true,brightness:0,contrast:0,saturation:0,focusX:50,focusY:50};
  const restored={...defaults,...recipeSeed};
  for(const key of Object.keys(defaults)){const control=$(`#${key}`);if(control.type==='checkbox')control.checked=restored[key];else control.value=String(restored[key]);}
  $('#target-profile').value=targetDevice?`device:${targetDevice.id}`:`profile:${editing?.profile||'openpaper_l'}`;
  if(editing){$('#image-preview').src=thumb('variant',editing.id);$('#variant-name').value=`${editing.name} (edited)`.slice(0,120);$('#preview-note').textContent='Saved recipe loaded from the original. Update the preview, then save a new revision; existing assignments stay unchanged.';}
  $('#dither-help-toggle').onclick=()=>{const expanded=$('#dither-help-toggle').getAttribute('aria-expanded')!=='true';$('#dither-help-toggle').setAttribute('aria-expanded',String(expanded));$('#dither-help').hidden=!expanded;};
  $('#target-profile').onchange=()=>{const target=$('#target-profile').value;if(target.startsWith('device:')){const device=state.data.devices.find(d=>d.id===target.slice(7));$('#orientation').value=device.orientation||'portrait';}invalidate();};
  for(const key of ['brightness','contrast','saturation'])$(`#${key}`).oninput=e=>{$(`#${key}-value`).textContent=e.target.value;invalidate();};
  for(const key of ['orientation','fit','rotation','palette','matching','dither','automatic','focusX','focusY'])$(`#${key}`).onchange=()=>{$('#crop-focus').hidden=$('#fit').value!=='cover';invalidate();};
  function invalidate(){state.result=null;$('#save-variant').disabled=true;$('#show-result').disabled=true;$('#output-dimensions').textContent=$('#orientation').value==='landscape'?'1600 × 1200 · Landscape · Six display colors':'1200 × 1600 · Portrait · Six display colors';$('#preview-note').textContent='Settings changed. Update the preview before saving.';updateEditorHelp();}
  function updateEditorHelp(){$('#crop-focus').hidden=$('#fit').value!=='cover';$('#palette-tip').textContent=PALETTES[$('#palette').value]?.use||'';$('#dither-tip').textContent=DITHERS[$('#dither').value]?.use||'';for(const key of ['brightness','contrast','saturation'])$(`#${key}-value`).textContent=$(`#${key}`).value;}
  updateEditorHelp();$('#output-dimensions').textContent=$('#orientation').value==='landscape'?'1600 × 1200 · Landscape · Six display colors':'1200 × 1600 · Portrait · Six display colors';
  let source=null;
  $('#optimize').onclick=()=>run(async()=>{
    if(!window.Worker||!window.OffscreenCanvas)throw new Error('Use a current Chrome, Edge, Firefox, or Safari browser with OffscreenCanvas support.');
    $('#optimize').disabled=true;$('#save-variant').disabled=true;$('#preview-note').textContent='Preparing full-resolution output…';
    const controls=[...$('#dialog-content').querySelectorAll('input,select')];
    controls.forEach(c=>{c.disabled=true;});
    let worker;
    const targetValue=$('#target-profile').value;
    const targetProfile=targetValue.startsWith('device:')?state.data.devices.find(d=>d.id===targetValue.slice(7)).profile:targetValue.slice(8);
    const recipe={profile:targetProfile,matching:$('#matching').value,orientation:$('#orientation').value,fit:$('#fit').value,rotation:Number($('#rotation').value),palette:$('#palette').value,dither:$('#dither').value,automatic:$('#automatic').checked,...Object.fromEntries(['brightness','contrast','saturation','focusX','focusY'].map(k=>[k,Number($(`#${k}`).value)]))};
    try{
      if(!source){const response=await fetch(`api/media/asset/${id}/source`);if(!response.ok)throw new Error('Could not load the image source.');source=await response.blob();}
      worker=new Worker(new URL('./optimizer.js',import.meta.url),{type:'module'});state.worker=worker;
      const result=await new Promise((resolve,reject)=>{worker.onmessage=e=>e.data.error?reject(new Error(e.data.error)):resolve(e.data);worker.onerror=e=>reject(new Error(e.message||'Optimizer could not start.'));worker.postMessage({source,recipe});});
      if(!dialog.open||state.worker!==worker)return;
      worker.terminate();state.worker=null;state.result=result;
      const previousURL=state.previewURL;state.previewURL=URL.createObjectURL(result.preview);
      const decoded=new Image();decoded.src=state.previewURL;await decoded.decode();
      if(!dialog.open||!$('#image-preview'))return;
      $('#image-preview').src=state.previewURL;if(previousURL)URL.revokeObjectURL(previousURL);$('#preview-note').textContent='Full-resolution output. Physical display colors may differ.';
      $('#save-variant').disabled=false;$('#show-result').disabled=false;
    }finally{worker?.terminate();if(state.worker===worker)state.worker=null;controls.forEach(c=>{c.disabled=false;});if($('#optimize'))$('#optimize').disabled=false;}
  });
  $('#show-original').onclick=()=>{$('#image-preview').src=thumb('asset',id);$('#preview-note').textContent='Original preview; original bytes are preserved.';};
  $('#show-result').onclick=()=>{if(state.previewURL){$('#image-preview').src=state.previewURL;$('#preview-note').textContent='Optimized output; physical display colors may differ.';}};
  $('#save-variant').onclick=()=>run(async()=>{
    if(!state.result)return;
    const button=$('#save-variant');button.disabled=true;
    try{await api(`assets/${id}/variants`,{method:'POST',body:state.result.bmp,headers:{'Content-Type':'image/bmp','X-Variant-Name':encodeURIComponent($('#variant-name').value),'X-Recipe':JSON.stringify(state.result.recipe),...(editing?{'X-Parent-Variant':editing.id}:{})}});
      await refresh();await render();await openEditor(id);notice('Saved a new variant. Existing device assignments are unchanged.');}
    finally{if(button.isConnected)button.disabled=false;}
  });
  document.querySelectorAll('[data-edit-variant]').forEach(b=>b.onclick=()=>run(()=>openEditor(id,{variantId:b.dataset.editVariant,deviceId:options.deviceId})));
  document.querySelectorAll('[data-delete-variant]').forEach(b=>b.onclick=()=>run(async()=>{
    if(!confirm('Delete this saved variant? Referenced variants cannot be deleted.'))return;
    await api(`media/variant/${b.dataset.deleteVariant}`,{method:'DELETE'});await refresh();await openEditor(id);
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
      return `<article class="device-card"><div class="device-cover" data-orientation="${d.orientation||'portrait'}">${e?`<img src="${entryImage(e,d.orientation||'portrait')}" alt="Last served image">`:'<span class="muted">No image served yet</span>'}</div><div class="card-meta"><h2>${escape(d.name)}</h2><span class="badge ${d.enabled&&!d.paused?'active':''}">${!d.enabled?'Disabled':d.paused?'Paused':'Playing'}</span></div><p class="help">${escape(d.orientation||'portrait')} · OpenPaper L · ${d.entries.filter(e=>e.enabled).length} enabled images<br>Last contact: ${when(d.state.last_image_request)}</p><div class="actions"><a class="button" href="#devices/${d.id}">Manage device</a><button class="small" data-quick-next="${d.id}">Next image</button></div></article>`;
    }).join('')}</div>`:'<div class="empty"><h2>Meet your first frame</h2><p>Add an OpenPaper L, choose images from your library, and connect it using its settings URL.</p><button id="first-device">Add your first device</button></div>');
  $('#add-device').onclick=()=>deviceDialog();$('#first-device')?.addEventListener('click',()=>deviceDialog());
  document.querySelectorAll('[data-quick-next]').forEach(b=>b.onclick=()=>run(async()=>{await api(`devices/${b.dataset.quickNext}/next`,{method:'POST'});await refresh();devicesView();notice('Next image selected. The frame will fetch it on its next wake-up.');}));
}

function deviceDialog(copyFrom){
  modal(copyFrom?'Duplicate device':'Add device',`<form id="new-device" class="stack"><label class="field">Device name<input name="name" maxlength="120" required placeholder="Living room"></label><label class="field">Device type<select name="profile"><option value="openpaper_l">OpenPaper L · 13.3-inch · 1200 × 1600</option></select></label><p class="help">${copyFrom?'Copies settings and image assignments. Credentials and playback state will be independent.':'Other OpenPaper models can be added after separate hardware validation.'}</p><button class="primary">${copyFrom?'Duplicate device':'Add device'}</button></form>`);
  $('#new-device').onsubmit=e=>{e.preventDefault();run(async()=>{const d=await api('devices',{method:'POST',data:{name:new FormData(e.target).get('name'),copy_from:copyFrom}});dialog.close();await refresh();location.hash=`devices/${d.id}`;});};
}

async function deviceView(id){
  const d=await api(`devices/${id}`),selected=d.entries.find(e=>e.id===d.state.selected);
  if(route()!==`devices/${id}`)return;
  const queue=d.state.queue.map(id=>d.entries.find(e=>e.id===id)).filter(Boolean);
  content.innerHTML=`<div class="breadcrumbs"><a href="#devices">Devices</a> / ${escape(d.name)}</div>`+
    heading('OpenPaper L',escape(d.name),'Selection changes arrive when the frame next fetches an image.',
      '<button id="refresh-device">Refresh status</button>')+
    `<div class="detail-layout"><div><section class="panel"><h2>Frame preview</h2><div class="device-cover" data-orientation="${d.orientation||'portrait'}">${selected?`<img src="${entryImage(selected,d.orientation||'portrait')}" alt="Selected output in device mounting orientation">`:'<span class="muted">No image selected</span>'}</div><p class="help">${escape(d.orientation||'portrait')} · ${d.orientation==='landscape'?'1600 × 1200':'1200 × 1600'} viewing area. Selected output; the frame fetches it on wake-up. Original-mode fitting and colors are approximate.</p></section><section class="panel"><div class="page-head"><div><h2>Image list</h2><p>${d.entries.length} entries · Cycle ${d.state.cycle}</p></div><button class="primary" id="add-images">＋ Add images</button></div><p class="help">Arrange the base order below. With shuffle enabled, a new order is made only after the current cycle finishes.</p><ol class="queue">${d.entries.map((e,index)=>`<li draggable="true" data-entry="${e.id}" class="${e.id===d.state.selected?'current':''}"><img src="${entryImage(e,d.orientation||'portrait')}" alt=""><div class="entry-text"><strong>${index+1}. ${escape(asset(e.asset_id)?.name||'Unavailable image')}</strong><small>${e.mode==='variant'?escape(variant(e.variant_id)?.name||'Saved variant'):'Original · processed by frame'}${e.id===d.state.selected?' · Selected':''}${e.id===d.state.last_served_entry?' · Last served':''}</small></div><label class="check"><input data-enabled="${e.id}" type="checkbox" aria-label="Enable image ${index+1}" ${e.enabled?'checked':''}></label><div class="queue-controls"><button data-up="${index}" aria-label="Move image ${index+1} up" ${index===0?'disabled':''}>↑</button><button data-down="${index}" aria-label="Move image ${index+1} down" ${index===d.entries.length-1?'disabled':''}>↓</button><button data-choose="${e.id}" ${e.enabled?'':'disabled'}>Show next</button><button data-remove="${e.id}" aria-label="Remove image ${index+1}">×</button></div></li>`).join('')||'<li><p class="help">Add originals or saved variants from the Media Library.</p></li>'}</ol><div class="actions"><button id="previous">Previous</button><button id="pause">${d.paused?'Resume':'Pause'}</button><button id="next">Next image</button></div></section><section class="panel"><h2>Playback status</h2><div class="facts"><div><dt>Selected image</dt><dd>${escape(selected?asset(selected.asset_id)?.name:'Placeholder')}</dd></div><div><dt>Last completed delivery</dt><dd>${when(d.state.last_served_at)}</dd></div><div><dt>Next eligible change</dt><dd>${d.paused?'Paused':when(d.state.deadline)}</dd></div><div><dt>Settings last requested</dt><dd>${when(d.state.last_settings_request)}</dd></div></div><p class="help">${escape(d.state.last_error||'HTTP delivery does not confirm what is physically visible on the screen.')}</p><details><summary>Current playback queue</summary><ol>${queue.map(e=>`<li>${escape(asset(e.asset_id)?.name)}</li>`).join('')}</ol></details></section></div><div><section class="panel"><h2>Device settings</h2><form id="device-form" class="stack"><label class="field">Name<input name="name" maxlength="120" value="${escape(d.name)}" required></label><label class="field">Mounting orientation<select name="orientation"><option value="portrait" ${d.orientation!=='landscape'?'selected':''}>Portrait · 1200 × 1600</option><option value="landscape" ${d.orientation==='landscape'?'selected':''}>Landscape · 1600 × 1200</option></select><small>Controls previews. Use a matching variant; changing mounting does not recrop existing images.</small></label><label class="field">Update interval (seconds)<input name="interval" type="number" min="60" max="2592000" value="${d.interval}" required><small>60 seconds to 30 days. Early fetches retain the current selection.</small></label><label class="check"><input name="enabled" type="checkbox" ${d.enabled?'checked':''}>Device enabled</label><label class="check"><input name="shuffle" type="checkbox" ${d.shuffle?'checked':''}>Shuffle after a complete cycle</label><label class="check"><input name="motionWakeup" type="checkbox" ${d.settings.motionWakeup?'checked':''}>Wake on movement</label><label class="check"><input name="autoRotation" type="checkbox" ${d.settings.autoRotation?'checked':''}>Automatic sensor rotation</label><label class="check"><input name="chargerMode" type="checkbox" ${d.settings.chargerMode?'checked':''}>Charge NiMH batteries over USB</label><small>Enable charging only with NiMH batteries. Leave off for other battery types.</small><button class="primary">Save settings</button></form></section><section class="panel"><h2>Connect your frame</h2>${d.urls.image?`<label class="field">Settings JSON URL<div class="url-row"><input readonly id="settings-url" value="${escape(d.urls.settings)}"><button class="small" data-copy="settings-url">Copy</button></div></label><label class="field">Fixed image URL<div class="url-row"><input readonly id="image-url" value="${escape(d.urls.image)}"><button class="small" data-copy="image-url">Copy</button></div></label><p class="help">Set the Settings-JSON-URL in the offline firmware Web UI. Both URLs stay fixed as images change. Keep these credential-bearing URLs private.</p><details><summary>Settings JSON preview</summary><pre>${escape(JSON.stringify(d.settings_json,null,2))}</pre></details>`:'<p class="help">Set the LAN base URL in <a href="#settings">Settings</a> to generate your device URLs.</p>'}${frameHelp()}<div class="actions"><button class="small" id="rotate-token">Rotate access token</button><button class="small" id="duplicate-device">Duplicate device</button><button class="small danger" id="remove-device">Remove device</button></div></section></div></div>`;
  $('#refresh-device').onclick=()=>run(async()=>{await refresh();await deviceView(id);});
  $('#add-images').onclick=()=>picker(d);
  for(const action of ['next','previous'])$(`#${action}`).onclick=()=>run(async()=>{await api(`devices/${id}/${action}`,{method:'POST'});await refresh();await deviceView(id);notice('Selection updated. Waiting for the frame’s next fetch.');});
  $('#pause').onclick=()=>saveDevice(d,{paused:!d.paused});
  $('#device-form').onsubmit=e=>{e.preventDefault();const f=e.target;const settings={motionWakeup:f.motionWakeup.checked,autoRotation:f.autoRotation.checked,chargerMode:f.chargerMode.checked};let confirm_nimh=false;
    if(settings.chargerMode&&!d.settings.chargerMode){confirm_nimh=confirm('Confirm this frame contains NiMH rechargeable batteries. Charging other battery types is unsafe.');if(!confirm_nimh)return;}
    saveDevice(d,{name:f.elements.namedItem('name').value,orientation:f.elements.namedItem('orientation').value,interval:Number(f.interval.value),enabled:f.enabled.checked,shuffle:f.shuffle.checked,settings,confirm_nimh});};
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

async function saveDevice(d,changes){return run(async()=>{await api(`devices/${d.id}`,{method:'PUT',data:{...changes,modified:d.modified}});await refresh();await deviceView(d.id);});}

function picker(device){
  modal('Add images to '+device.name,`<p class="help">Choose an original or a saved variant for each image. Variants are prepared for a model and mounting orientation. Use Prepare for this device to start from the right target; a different mounting can show a sideways result.</p><div class="picker-grid">${state.data.assets.map(a=>{
    const variants=state.data.variants.filter(v=>v.asset_id===a.id&&v.profile===device.profile);
    return `<div class="picker-card"><img src="${thumb('asset',a.id)}" alt=""><strong>${escape(a.name)}</strong><select data-representation="${a.id}" aria-label="Image version for ${escape(a.name)}"><option value="original" ${a.original_supported?'':'disabled'}>Original ${a.original_supported?'':'(not compatible)'}</option>${variants.map(v=>`<option value="${v.id}" ${!a.original_supported?'selected':''}>${escape(v.name)} · ${escape(variantFormat(v))}${variantOrientation(v)!==(device.orientation||'portrait')?' · different mounting':''}</option>`).join('')}</select><button data-prepare-asset="${a.id}">Prepare for this device</button><button data-add-asset="${a.id}" ${a.original_supported||variants.length?'':'disabled'}>Add to device</button>${!a.original_supported&&!variants.length?'<small>Create a variant in the Media Library first.</small>':''}</div>`;
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
    `<section class="panel"><h2>Device endpoint</h2><form id="global-form" class="stack"><label class="field">LAN base URL<input id="base-url" type="url" placeholder="http://192.168.1.10:8098" value="${escape(state.data.settings.base_url||suggestedBaseURL())}" ${state.data.base_url_locked?'readonly':''} required><small>${state.data.settings.base_url?'Saved address.':'Suggested address; confirm that your frame can reach this host, then save it.'} Device URLs must fit within 128 characters.</small></label>${state.data.base_url_locked?'<p class="help">This URL is set in the Home Assistant add-on configuration.</p>':'<button class="primary">Save LAN base URL</button>'}</form><p class="help"><strong>Device port: ${state.data.network?.device_port===null?'disabled':state.data.network?.device_port||8098}</strong>${state.data.network?.detected?' (detected host mapping)':' (default; confirm in Home Assistant)'}. To change it, open the add-on’s Configuration → Network in Home Assistant, change the host port for 8098/tcp, and restart the add-on. Then save the matching port in this LAN base URL. Editing the URL alone does not change the port mapping.</p><p class="help">Restrict allowed_networks in the add-on configuration to your frame network. Device endpoints require a per-device token. They expose images and settings only; management stays behind Home Assistant Ingress. HTTP does not encrypt images or credentials, and the firmware does not verify HTTPS certificates.</p></section><section class="panel"><h2>Storage</h2><p>${bytes(state.data.storage_bytes)} used of ${bytes(state.data.storage_limit)}</p><div class="storage-meter"><progress max="${state.data.storage_limit}" value="${state.data.storage_bytes}" aria-label="Storage used"></progress></div><p class="help">Originals, saved variants, settings, and playback progress live in the add-on’s persistent data. Include this add-on in Home Assistant backups. Only unreferenced crash leftovers are cleaned automatically.</p></section><section class="panel"><h2>Frame setup</h2><ol class="help"><li>Back up device certificates before changing firmware.</li><li>Use the upstream Web UI to install offline firmware and configure WiFi.</li><li>Add a device here, choose its images, and copy its settings JSON URL.</li><li>Set that URL in the frame’s Settings-JSON-URL field. URL-download mode is needed for timed wake-ups.</li><li>If the Web UI reports “Failed to fetch”, allow local network access in its browser site permissions and check the URL and port. Some browsers still block HTTPS-to-HTTP previews; the frame itself is not subject to CORS. Save the settings URL on the frame even if the browser preview is blocked.</li></ol><div class="actions"><a class="button" href="https://paperlesspaper.github.io/paperlesspaper-firmware-offline/" target="_blank" rel="noreferrer">Open Web UI & flasher ↗</a><a href="https://github.com/paperlesspaper/paperlesspaper-firmware-offline" target="_blank" rel="noreferrer">Offline firmware source ↗</a></div><p class="help">E-Ink Display Manager ${state.data.version} · Experimental. OpenPaper L hardware acceptance is required before a stable release.</p></section>`;
  $('#global-form').onsubmit=e=>{e.preventDefault();run(async()=>{await api('settings',{method:'PUT',data:{base_url:$('#base-url').value}});await refresh();settingsView();notice('LAN base URL saved. Reconfigure existing frames if their settings URL changed.');});};
}

async function run(action){try{return await action();}catch(error){notice(error.message||'The operation failed. Refresh and try again.',true);}}
window.addEventListener('hashchange',()=>run(render));
setInterval(()=>{if(!dialog.open&&route()==='devices'&&!state.search&&!state.selected.size)run(async()=>{await refresh();await render();});},15000);
run(render);
