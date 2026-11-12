import assert from 'node:assert/strict';
import {test} from 'node:test';
import {processingOptions} from '../web/optimizer-options.js';
import {getProcessingPreset} from '../web/vendor/epdoptimize-1.4.1.mjs';

const base={automatic:true,brightness:0,contrast:0,saturation:0,matching:'rgb',dither:'floyd',palette:'spectra6',intent:'natural'};

test('automatic preset resolution applies real tone/range defaults, not menu entries',()=>{
  const result=processingOptions(base,{imageKind:'unknown',ditherOptions:{processingPreset:'balanced'}});
  assert.deepEqual(result.options.toneMapping,getProcessingPreset('balanced').toneMapping);
  assert.deepEqual(result.options.dynamicRangeCompression,{mode:'display',strength:1});
  assert.equal(Object.keys(result.options).some(key=>/^\d+$/.test(key)),false);
  assert.equal(result.analysis.enabled,true);
  assert.equal(result.analysis.preset,'Balanced');
});

const suggestion={imageKind:'photo',ditherOptions:{processingPreset:'dynamic',toneMapping:{mode:'scurve',exposure:.1,saturation:.45,strength:.72,shadowBoost:.08,highlightCompress:-1.3,midpoint:.5}}};
test('adjusting brightness preserves automatic saturation and S-curve',()=>{
  const {options,analysis}=processingOptions({...base,brightness:20},suggestion);
  assert.deepEqual(options.toneMapping,{...suggestion.ditherOptions.toneMapping,exposure:.2});
  assert.deepEqual(analysis.manualOverrides,['exposure']);
  assert.equal(suggestion.ditherOptions.toneMapping.exposure,.1);
});

test('contrast remains active alongside the automatic S-curve without erasing other channels',()=>{
  const {options}=processingOptions({...base,contrast:15},suggestion);
  assert.equal(options.toneMapping.mode,undefined);
  assert.equal(options.toneMapping.contrast,.15);
  assert.equal(options.toneMapping.strength,.72);
  assert.equal(options.toneMapping.exposure,.1);
  assert.equal(options.toneMapping.saturation,.45);
});

test('zero sliders preserve automatic settings and explicit matching/dither choices',()=>{
  const {options}=processingOptions({...base,matching:'lab',dither:'stucki'},suggestion);
  assert.deepEqual(options.toneMapping,suggestion.ditherOptions.toneMapping);
  assert.equal(options.colorMatching,'lab');
  assert.equal(options.errorDiffusionMatrix,'stucki');
});

test('automatic off excludes all inferred adjustments; manual controls still work',()=>{
  const {options,analysis}=processingOptions({...base,automatic:false},suggestion);
  assert.equal(options.toneMapping,undefined);
  assert.equal(options.dynamicRangeCompression,undefined);
  assert.equal(analysis.enabled,false);
  assert.equal(analysis.imageKind,null);
  assert.deepEqual(processingOptions({...base,automatic:false,saturation:25},null).options.toneMapping,{mode:'contrast',saturation:.25});
});

test('a vivid intent works with a calibrated palette independently of legacy vivid RGB',()=>{
  const {analysis}=processingOptions({...base,intent:'vivid'},suggestion);
  assert.equal(analysis.intent,'vivid');
  const legacy={...base,palette:'vivid'};delete legacy.intent;
  assert.equal(processingOptions(legacy,suggestion).analysis.intent,'vivid');
});
