import {getProcessingPreset} from './vendor/epdoptimize-1.4.1.mjs';
import {ditherOptions} from './processing.js';

// Resolve the real preset configuration, not getProcessingPresetOptions(),
// which returns menu entries and does not accept a preset name.
export function processingOptions(recipe,suggestion){
  let options={};
  const presetName=suggestion?.ditherOptions.processingPreset;
  const preset=presetName?getProcessingPreset(presetName):null;
  if(recipe.automatic&&suggestion){
    const presetOptions=Object.fromEntries(Object.entries(preset||{}).filter(([key])=>!['name','title','description'].includes(key)));
    options={...presetOptions,...suggestion.ditherOptions};
    delete options.processingPreset;
  }
  const overrides=Object.entries({exposure:recipe.brightness,contrast:recipe.contrast,saturation:recipe.saturation})
    .filter(([_key,value])=>Number.isFinite(value)&&value!==0);
  if(overrides.length){
    const tone={...options.toneMapping};
    if(!options.toneMapping||tone.mode==='off')tone.mode='contrast';
    for(const [key,value] of overrides)tone[key]=value/100;
    // An unspecified mode applies contrast and the S-curve
    // together; explicit scurve mode alone ignores the contrast control.
    if(tone.mode==='scurve'&&overrides.some(([key])=>key==='contrast'))delete tone.mode;
    options.toneMapping=tone;
  }
  Object.assign(options,{colorMatching:recipe.matching==='lab'?'lab':'rgb',processingEngine:'js',adjustmentEngine:'js',
    ...ditherOptions(recipe.dither),serpentine:true});
  return {options,analysis:{enabled:!!recipe.automatic,imageKind:recipe.automatic?suggestion?.imageKind:null,
    preset:recipe.automatic?preset?.title||presetName||null:null,
    intent:recipe.intent||(recipe.palette==='vivid'?'vivid':'natural'),
    manualOverrides:overrides.map(([key])=>key),toneMapping:options.toneMapping||null}};
}
