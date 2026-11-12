import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ditherImage} from '../web/vendor/epdoptimize-1.4.1.mjs';
import {measuredOpenPaperLPalette as palette} from '../web/panel-palettes.js';
import {paletteKeys} from '../web/processing.js';

test('measured L profile is offered only for its display model',()=>{
  assert.ok(paletteKeys('openpaper_l').includes('openpaper_l_measured'));
  assert.ok(!paletteKeys('openpaper_7').includes('openpaper_l_measured'));
  assert.ok(!paletteKeys('inkplate_6').includes('openpaper_l_measured'));
});
for(const matching of ['rgb','lab'])test(`new gamut-aware diffusion preserves a sharp black/white layout (${matching})`,async()=>{
  const width=64,height=64,data=new Uint8ClampedArray(width*height*4);
  const input=[];
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const black=x>=20&&x<=22&&y>=10&&y<=54;
    input.push(black?'black':'white');const at=(y*width+x)*4;
    data.set([black?0:255,black?0:255,black?0:255,255],at);
  }
  let pixels={width,height,data};
  const canvas={width,height,getContext(){return {getImageData(){return pixels;},putImageData(value){pixels=value;}};}};
  await ditherImage(canvas,canvas,{palette,ditheringType:'errorDiffusion',errorDiffusionMatrix:'floydSteinberg',colorMatching:matching,processingEngine:'js',adjustmentEngine:'js',serpentine:true});
  const colors=Object.fromEntries(palette.map(p=>[p.name,p.color.match(/\w{2}/g).map(h=>parseInt(h,16))]));
  for(let i=0;i<input.length;i++)assert.deepEqual([...pixels.data.slice(i*4,i*4+3)],colors[input[i]],`pixel ${i}`);
});
