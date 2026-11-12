const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const clipboardAvailable=()=>globalThis.isSecureContext&&typeof navigator.clipboard?.writeText==='function';
export function idField(id,label='Resource ID'){
  return `<label class="copy-field"><span>${escape(label.split(' for ')[0])}</span><div class="url-row"><input readonly data-select-copy aria-label="${escape(label)}" value="${escape(id)}" spellcheck="false">${clipboardAvailable()?'<button type="button" class="small" data-copy-value>Copy</button>':''}</div></label>`;
}
export function bindCopyFields(root=document,notify=()=>{}){
  for(const input of root.querySelectorAll('input[data-select-copy]')){
    input.onfocus=()=>input.select();
    input.onclick=()=>input.select();
    input.onpointerup=event=>{if(event.pointerType==='mouse'){event.preventDefault();input.select();}};
  }
  for(const button of root.querySelectorAll('[data-copy-value],[data-copy]')){
    if(!clipboardAvailable()){button.remove();continue;}
    button.onclick=async()=>{
      const input=button.dataset.copy?document.getElementById(button.dataset.copy):button.parentElement.querySelector('input');
      input.focus();input.select();
      try{await navigator.clipboard.writeText(input.value);notify('Copied.');}
      catch{notify('Text selected. Press Ctrl+C or Command+C to copy.');}
    };
  }
}
