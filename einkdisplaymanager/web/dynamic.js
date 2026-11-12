import {createCodeEditor} from './vendor/editor-6.mjs';
import {DITHERS,PALETTES,MATCHING} from './processing.js';
import {optionGroups} from './selects.js';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=(selector,root=document)=>root.querySelector(selector);
const when=value=>value?new Date(value*1000).toLocaleString():'Not yet';
const button=(label,id)=>`<button class="small" data-copy-id="${esc(id)}">${label}</button>`;
function blobURL(encoded,mime){const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));return URL.createObjectURL(new Blob([bytes],{type:mime}));}

export function dynamicUI({api,modal,notice,refresh,getData,render}){
  let editor=null,poll=null,urls=[];
  function dispose(){editor?.destroy();editor=null;clearInterval(poll);poll=null;urls.forEach(u=>URL.revokeObjectURL(u));urls=[];}
  async function copy(id){try{await navigator.clipboard.writeText(id);notice('ID copied.');}catch{notice('Copy this ID: '+id);}}
  function bindCopies(){document.querySelectorAll('[data-copy-id]').forEach(b=>b.onclick=()=>copy(b.dataset.copyId));}
  async function action(fn){try{await fn();}catch(error){notice(error.message,true);}}
  function library(content){
    const data=getData(),items=data.assets.filter(a=>a.dynamic);
    content.insertAdjacentHTML('beforeend',`<div class="page-head"><p class="help">Write once, render for each display. Generated images and target variants stay in RAM.</p><button id="new-dynamic" class="primary">＋ Create dynamic image</button></div>${data.dynamic.error?`<p class="save-status" data-result="error">${esc(data.dynamic.error)}</p>`:''}<div class="library-grid dynamic-grid">${items.map(a=>{
      const status=a.render_status,ready=status.ready_variants.length;
      return `<article class="media-card dynamic-card"><button class="image-button" data-dynamic="${a.id}" aria-label="Edit ${esc(a.name)}">${ready?`<img src="api/media/asset/${a.id}/thumbnail?v=${status.last_success}" alt="${esc(a.name)}">`:'<span class="dynamic-placeholder" aria-hidden="true">{ }</span>'}</button><h3>${esc(a.name)}</h3><div class="card-meta"><span class="badge">Dynamic</span>${button('Copy ID',a.id)}</div><small>Generate every ${a.interval} s · ${ready} targets ready<br>Last render: ${when(status.last_success)}</small>${status.error?`<p class="help error-text">${esc(status.error)}</p>`:''}</article>`;
    }).join('')}</div>${items.length?'':'<div class="empty"><h2>A canvas that stays current</h2><p>Draw text, shapes, photos, and Home Assistant values with JavaScript.</p></div>'}`);
    $('#new-dynamic').onclick=()=>edit();
    document.querySelectorAll('[data-dynamic]').forEach(b=>b.onclick=()=>edit(b.dataset.dynamic));bindCopies();
  }
  function fonts(content){
    const fonts=getData().fonts;
    content.insertAdjacentHTML('beforeend',`<section class="panel"><div class="page-head"><div><h2>Your fonts</h2><p>Upload TTF or OTF files up to 4 MiB. Use the stable ID in screen.text().</p></div><label class="button">Upload fonts<input type="file" id="font-upload" accept=".ttf,.otf" multiple hidden></label></div><p class="help">A bundled default font is always available as <code>default</code>. Missing IDs fall back to it with a render warning. Uploaded files are stored permanently; keep their licenses in mind.</p><div class="font-list">${fonts.map(f=>`<article class="font-row"><div><strong>${esc(f.name)}</strong><br><code>${f.id}</code><small> · ${Math.ceil(f.bytes/1024)} KiB</small></div><div class="actions">${button('Copy ID',f.id)}<button class="small danger" data-delete-font="${f.id}">Delete</button></div></article>`).join('')||'<p class="help">No uploaded fonts yet. You can start with the default font.</p>'}</div></section>`);
    $('#font-upload').onchange=()=>action(async()=>{for(const file of $('#font-upload').files){await api('fonts',{method:'POST',body:file,headers:{'X-File-Name':encodeURIComponent(file.name)}});}await refresh();render();notice('Fonts uploaded.');});
    document.querySelectorAll('[data-delete-font]').forEach(b=>b.onclick=()=>action(async()=>{if(!confirm('Delete this font? Scripts using its ID will fall back to the default font.'))return;await api('fonts/'+b.dataset.deleteFont,{method:'DELETE'});await refresh();render();}));bindCopies();
  }
  async function edit(id,options={}){
    const data=getData(),item=id?data.assets.find(a=>a.id===id):null;
    let targets=id?data.variants.filter(v=>v.asset_id===id):[];
    let active=options.profileId?targets.find(v=>v.profile===options.profileId&&v.recipe.orientation===options.orientation):targets.find(v=>v.id===options.targetId)||targets[0];
    const seed=active?.recipe||{profile:options.profileId||'openpaper_l',orientation:options.orientation||'portrait',palette:'natural',dither:'none',matching:'rgb',automatic:false,invert:false,brightness:0,contrast:0,saturation:0,intent:'natural'};
    let draft={...seed},saving=false,dirty=false;
    const families=[...new Set(data.profiles.map(p=>p.family))];
    modal(item?'Edit '+item.name:'Create dynamic image',`<form id="dynamic-form" class="stack"><div class="form-grid"><label class="field">Name<input id="dynamic-name" maxlength="120" required value="${esc(item?.name||'New dynamic image')}"></label><label class="field">Generation interval (seconds)<input id="dynamic-interval" type="number" min="10" max="2592000" step="1" required value="${item?.interval||300}"><small>Independent of device fetch intervals.</small></label><label class="field">Time zone<input id="dynamic-timezone" required value="${esc(item?.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC')}"></label></div>
      <div class="dynamic-layout"><div class="script-pane"><div class="card-meta"><h3>JavaScript source</h3><div class="actions"><span id="script-dirty" class="help">${item?'Saved source':'Unsaved source'}</span><button type="button" id="dynamic-preview">Render preview</button></div></div><div id="script-editor"></div><details class="option-details"><summary>Home Assistant inputs</summary><label class="field">Additional entity IDs<textarea id="dynamic-entities" rows="3" placeholder="sensor.living_room_temperature">${esc((item?.entities||[]).join('\n'))}</textarea><small>Literal entity IDs in ha.state/number/attribute calls are detected automatically. Add IDs here if the script constructs them dynamically. Only this read-only snapshot is passed to JavaScript.</small></label></details>
      <details class="option-details"><summary>Drawing API and resource IDs</summary><p class="help">Coordinates and sizes are pixels. Colors accept #RRGGBB or palette.black / palette.white and the target's available colors. Missing images are skipped; missing fonts use the default.</p><pre class="api-example">screen.clear("#ffffff");
screen.text("Hello", {x:20, y:40, font:"default", fontSize:32,
  color:palette.black, align:"left", verticalAlign:"top"});
screen.line({x1:20,y1:90,x2:300,y2:90,stroke:palette.black,strokeWidth:2});
screen.rectangle({x:20,y:110,width:200,height:100,stroke:palette.black});
screen.circle({x:300,y:160,radius:40,fill:palette.black});
screen.image("image-id", {x:20,y:250,width:200,height:150,fit:"contain"});
ha.state("sensor.temperature", "—");
ha.number("sensor.temperature", null);
ha.attribute("sensor.temperature", "unit_of_measurement", "");
// screen.width, screen.height; now.hour/minute/day/month/year/iso</pre><div class="resource-ids">${data.assets.filter(a=>!a.dynamic).map(a=>`<div>${esc(a.name)} ${button('Copy image ID',a.id)}</div>`).join('')}${data.fonts.map(f=>`<div>${esc(f.name)} ${button('Copy font ID',f.id)}</div>`).join('')}</div></details></div>
      <div class="dynamic-target-pane stack"><label class="field">Saved target<select id="dynamic-target">${optionGroups([['Saved variants',targets.map(v=>`<option value="${v.id}">${esc(v.name)}</option>`).join('')]])}<option value="new">New target variant</option></select></label><label class="field">Target name<input id="dynamic-target-name" required maxlength="120" value="${esc(active?.name||'Display variant')}"></label><label class="field">Display model<select id="dynamic-profile">${optionGroups(families.map(f=>[f,data.profiles.filter(p=>p.family===f).map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('')]))}</select></label><label class="field">Orientation<select id="dynamic-orientation"><option value="portrait">Portrait</option><option value="landscape">Landscape</option></select></label><details class="option-details"><summary>Image optimization</summary><div class="stack"><label class="field">Colors<select id="dynamic-palette"></select></label><label class="field">Dithering<select id="dynamic-dither">${optionGroups([['Error diffusion',['errorDiffusion']],['Pattern dithering',['ordered','blueNoise']],['No dithering',['quantizationOnly']]].map(([label,types])=>[label,Object.entries(DITHERS).filter(([,d])=>types.includes(d.type)).map(([value,d])=>`<option value="${value}">${esc(d.name)}</option>`).join('')]))}</select><small id="dynamic-dither-tip"></small></label><label class="field">Color matching<select id="dynamic-matching">${Object.entries(MATCHING).map(([id,m])=>`<option value="${id}">${esc(m.name)}</option>`).join('')}</select><small id="dynamic-matching-tip"></small></label><label class="check"><input type="checkbox" id="dynamic-automatic">Automatic optimization</label><label class="check" id="dynamic-invert-label"><input type="checkbox" id="dynamic-invert">Invert tones</label></div></details><div id="dynamic-preview-stage" class="preview-stage"><span class="help">Render a preview to inspect this target.</span></div><p id="dynamic-output-size" class="help"></p><p id="dynamic-render-status" class="help" role="status"></p></div></div>
      <div class="actions"><button type="submit" class="primary" id="dynamic-save">Save image & target</button><button type="button" id="dynamic-render" ${item?'':'disabled'}>Render now</button>${active?'<button type="button" id="dynamic-delete-target" class="danger">Delete target</button>':''}${item?'<button type="button" id="dynamic-delete" class="danger">Delete dynamic image</button>':''}</div><p id="dynamic-save-status" class="save-status help" role="status"></p></form>`);
    const form=$('#dynamic-form');document.querySelector('#editor').classList.add('dynamic-editor');
    const mark=()=>{dirty=true;$('#script-dirty').textContent='Unsaved changes';};
    editor=createCodeEditor($('#script-editor'),item?.script||data.dynamic.default_script,mark,data.csrf);
    for(const node of form.querySelectorAll('input,select,textarea'))node.addEventListener('input',mark);
    const apply=()=>{
      const p=data.profiles.find(p=>p.id===draft.profile),ink=p.id==='inkplate_6';
      $('#dynamic-profile').value=draft.profile;$('#dynamic-profile').disabled=!!active;
      const allowed=Object.keys(PALETTES).filter(key=>ink?['gray8','grayscale'].includes(key):key!=='gray8');
      $('#dynamic-palette').innerHTML=optionGroups([['Spectra 6',allowed.filter(k=>!['gray8','grayscale'].includes(k))],['Monochrome',allowed.filter(k=>['gray8','grayscale'].includes(k))]].map(([label,keys])=>[label,keys.map(key=>`<option value="${key}">${esc(PALETTES[key].name)}</option>`).join('')]));
      if(!allowed.includes(draft.palette))draft.palette=ink?'gray8':'natural';
      for(const key of ['orientation','palette','dither','matching'])$('#dynamic-'+key).value=draft[key];
      for(const key of ['automatic','invert'])$('#dynamic-'+key).checked=!!draft[key];
      $('#dynamic-invert-label').hidden=!ink;$('#dynamic-invert').disabled=!ink;
      if(!ink)draft.invert=false;
      $('#dynamic-dither-tip').textContent=DITHERS[draft.dither].use;
      $('#dynamic-matching-tip').textContent=MATCHING[draft.matching].use;
      const size=draft.orientation==='landscape'?[Math.max(p.width,p.height),Math.min(p.width,p.height)]:[Math.min(p.width,p.height),Math.max(p.width,p.height)];
      $('#dynamic-output-size').textContent=size.join(' × ')+' viewing area · '+p.name;
    };
    $('#dynamic-target').value=active?.id||'new';apply();
    const read=()=>({name:$('#dynamic-name').value,script:editor.getValue(),interval:Number($('#dynamic-interval').value),timezone:$('#dynamic-timezone').value,entities:$('#dynamic-entities').value.split(/[\s,]+/).filter(Boolean)});
    const readRecipe=()=>({...draft,profile:$('#dynamic-profile').value,orientation:$('#dynamic-orientation').value,palette:$('#dynamic-palette').value,dither:$('#dynamic-dither').value,matching:$('#dynamic-matching').value,automatic:$('#dynamic-automatic').checked,invert:$('#dynamic-profile').value==='inkplate_6'&&$('#dynamic-invert').checked});
    for(const key of ['profile','orientation','palette','dither','matching','automatic','invert'])$('#dynamic-'+key).onchange=()=>{draft=readRecipe();if(key==='profile')draft.orientation=data.profiles.find(p=>p.id===draft.profile).native_orientation;apply();};
    $('#dynamic-target').onchange=()=>{
      active=targets.find(v=>v.id===$('#dynamic-target').value);draft={...(active?.recipe||draft)};
      $('#dynamic-target-name').value=active?.name||'New display variant';apply();
      $('#dynamic-delete-target')?.toggleAttribute('disabled',!active);
    };
    function paint(status){
      if(!form.isConnected)return;
      $('#dynamic-render-status').textContent=[status.running?'Rendering…':status.error?'Last render failed':status.last_success?'Ready':'Not rendered yet',status.error||'',`Last successful render: ${when(status.last_success)}`,...(status.warnings||[])].filter(Boolean).join('\n');
      $('#dynamic-render-status').classList.toggle('error-text',!!status.error);
      if(active&&status.ready_variants.includes(active.id)&&!dirty){
        const url=`api/media/variant/${active.id}/thumbnail?v=${status.last_success}`;
        if($('#dynamic-preview-stage').dataset.source!==url){$('#dynamic-preview-stage').innerHTML=`<img src="${url}" alt="Rendered target preview">`;$('#dynamic-preview-stage').dataset.source=url;}
      }
    }
    if(item){paint(item.render_status||{ready_variants:[],last_success:null});poll=setInterval(()=>{if(!form.isConnected)return;api('dynamic/'+id+'/status').then(paint).catch(()=>{});},2000);}
    $('#dynamic-preview').onclick=()=>action(async()=>{
      if(!form.reportValidity())return;
      const b=$('#dynamic-preview');b.disabled=true;b.textContent='Rendering preview…';
      try{const result=await api('dynamic-preview',{method:'POST',data:{...read(),recipe:readRecipe()}});if(!form.isConnected)return;
        urls.forEach(u=>URL.revokeObjectURL(u));urls=[];const url=blobURL(result.preview,'image/jpeg');urls.push(url);
        $('#dynamic-preview-stage').innerHTML=`<img src="${url}" alt="Unsaved dynamic image preview">`;
        $('#dynamic-render-status').textContent='Preview of the current draft. '+result.warnings.join(' ');
      }finally{if(b.isConnected){b.disabled=false;b.textContent='Render preview';}}
    });
    form.onsubmit=e=>{e.preventDefault();action(async()=>{
      if(saving)return;saving=true;$('#dynamic-save').disabled=true;
      try{const saved=await api(id?'dynamic/'+id:'dynamic',{method:id?'PUT':'POST',data:{...read(),...(item?{modified:item.modified}:{})}});
        await api('dynamic/'+saved.id+'/targets'+(active?'/'+active.id:''),{method:active?'PUT':'POST',data:{name:$('#dynamic-target-name').value,recipe:readRecipe(),...(active?{modified:active.modified}:{})}});
        await api('dynamic/'+saved.id+'/render',{method:'POST'});await refresh();edit(saved.id,{targetId:active?.id});notice('Dynamic image and target saved. Rendering in the background.');
      }finally{saving=false;if($('#dynamic-save'))$('#dynamic-save').disabled=false;}
    });};
    $('#dynamic-render').onclick=()=>action(async()=>{if(dirty)throw new Error('Save your changes first, or use Render preview for an unsaved draft.');paint(await api('dynamic/'+id+'/render',{method:'POST'}));});
    $('#dynamic-delete-target')?.addEventListener('click',()=>action(async()=>{if(!active||!confirm('Delete this target? Remove device assignments first.'))return;await api('media/variant/'+active.id,{method:'DELETE'});await refresh();edit(id);}));
    $('#dynamic-delete')?.addEventListener('click',()=>action(async()=>{if(!confirm('Delete this dynamic image? Remove its device assignments and targets first.'))return;await api('media/asset/'+id,{method:'DELETE'});document.querySelector('#editor').close();await refresh();render();}));
    bindCopies();
  }
  return {library,fonts,edit,dispose,bindCopies,copy};
}
