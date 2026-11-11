// Omit empty categories while keeping native select behavior and option values.
export function optionGroups(groups){
  return groups.filter(([,options])=>options).map(([label,options])=>{
    const safe=String(label).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    return `<optgroup label="${safe}">${options}</optgroup>`;
  }).join('');
}
