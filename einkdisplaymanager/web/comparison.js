const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function comparisonHTML(output,source='',{id='',orientation='portrait'}={}){
  const compare=!!source;
  return `<div class="comparison-block"><div class="comparison-stage"><div ${id?`id="${id}"`:''} class="comparison-preview ${compare?'has-comparison':''}" data-orientation="${orientation}" data-mode="split" data-source="${escape(output)}" data-choice="split" tabindex="0" role="group" aria-label="${compare?'Image comparison. Left arrow: original. Right arrow: variant. Escape: split.':'Selected output preview'}">
  ${output?`<img class="preview-output" src="${escape(output)}" alt="Selected output in device mounting orientation">`:'<span class="muted">No image selected</span>'}
  ${compare?`<img class="preview-original" src="${escape(source)}" alt="Original composition before color optimization"><span class="comparison-label label-original">Original</span><span class="comparison-label label-output">Variant</span>`:''}</div></div>
  ${compare?`<div class="comparison-controls" role="group" aria-label="Preview mode"><button class="small" data-preview-mode="split" aria-pressed="true">Split</button><button class="small" data-preview-mode="original" aria-pressed="false">Original</button><button class="small" data-preview-mode="output" aria-pressed="false">Variant</button></div>`:''}</div>`;
}

export function bindComparisons(root,dimensions){
  root.querySelectorAll('.comparison-preview').forEach(preview=>{
    const [width,height]=dimensions(preview);
    preview.style.setProperty('--preview-ratio',String(width/height));
    if(!preview.classList.contains('has-comparison'))return;
    const buttons=preview.closest('.comparison-block').querySelectorAll('[data-preview-mode]');
    const choose=mode=>{preview.dataset.choice=mode;preview.dataset.mode=mode;buttons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.previewMode===mode)));};
    buttons.forEach(button=>button.onclick=()=>choose(button.dataset.previewMode));
    preview.onpointermove=event=>{if(event.pointerType==='touch'||preview.dataset.choice!=='split')return;const rect=preview.getBoundingClientRect();preview.dataset.mode=(event.clientX-rect.x)/rect.width+(event.clientY-rect.y)/rect.height<1?'original':'output';};
    preview.onpointerleave=()=>{preview.dataset.mode=preview.dataset.choice;};
    preview.onkeydown=event=>{const mode={ArrowLeft:'original',ArrowRight:'output',Escape:'split'}[event.key];if(mode){event.preventDefault();choose(mode);}};
  });
}
