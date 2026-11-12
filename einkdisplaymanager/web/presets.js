// Starting points; applying a preset keeps composition and device assignments.
const tones={brightness:0,contrast:0,saturation:0,invert:false,intent:'natural'};
export function processingPresets(profile){
  const photo={...tones,automatic:true,matching:'lab',dither:'floyd'};
  if(profile==='inkplate_6')return [
    {id:'photo',name:'Grayscale photo preset',group:'Recommended',description:'Eight grayscale levels, automatic Natural tones, LAB and Floyd–Steinberg. Resets manual tones and inversion.',settings:{...photo,palette:'gray8'}},
    {id:'monochrome',name:'Monochrome preset',group:'Recommended',description:'Black and white, RGB, no dithering and automatic optimization off. Resets manual tones and inversion.',settings:{...tones,palette:'grayscale',matching:'rgb',dither:'none',automatic:false}},
  ];
  const presets=[{id:'photo',name:'Photo preset',group:'Recommended',description:'Calibrated Spectra 6 palette, automatic Natural tones, LAB and Floyd–Steinberg. Resets manual tones.',settings:{...photo,palette:'spectra6'}}];
  if(profile==='openpaper_l')presets.push({id:'measured',name:'Measured L photo preset',group:'Experimental',description:'Measured 13.3-inch palette, automatic Natural tones, LAB and Floyd–Steinberg. Resets manual tones; compare on your frame.',settings:{...photo,palette:'openpaper_l_measured'}});
  return presets;
}
