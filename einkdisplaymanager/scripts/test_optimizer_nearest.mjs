import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import vm from 'node:vm';
let library=readFileSync(new URL('../web/vendor/epdoptimize-1.4.1.mjs',import.meta.url),'utf8');
library=library.slice(0,library.lastIndexOf('export {')).replaceAll('import.meta.url',JSON.stringify('https://example.invalid/optimizer.mjs'));
const adapter=readFileSync(new URL('../web/optimizer-nearest.js',import.meta.url),'utf8');
const context=vm.createContext({URL:globalThis.URL});
vm.runInContext(library+';globalThis.referenceNearest=it;',context);
vm.runInContext(adapter,context);
for(const matching of ['rgb','lab'])test(`QuickJS nearest-color adapter exactly matches reference ${matching}`,()=>{
  const result=vm.runInContext(`(()=>{
    const palettes=[[[0,0,0],[255,255,255]],
      Array.from({length:8},(_,i)=>{const v=Math.round(i*255/7);return [v,v,v]}),
      [[0,0,0],[0,0,255],[0,255,0],[255,0,0],[255,255,0],[255,255,255]],
      [[0,0,0],[0,0,0],[255,255,255]],
      [[30,30,30],[45,61,130],[53,86,58],[155,48,63],[209,190,71],[185,199,201]]];
    let seed=91231;
    for(const palette of palettes){
      const colors=[[0,0,0],[255,255,255],[127.5,127.5,127.5],[-10,270,0],
        [128,128,128],[0,255,0],[255,0,0],[0,0,255]];
      for(let i=0;i<5000;i++){
        seed=(1664525*seed+1013904223)>>>0;
        colors.push([seed&255,(seed>>>8)&255,(seed>>>16)&255]);
      }
      for(const rgb of colors){
        const original=referenceNearest(rgb,palette,'${matching}');
        const fast=it(rgb,palette,'${matching}');
        if(JSON.stringify(original)!==JSON.stringify(fast))return {rgb,palette,original,fast};
      }
    }
    return null;
  })()`,context);
  assert.equal(result,null,JSON.stringify(result));
});
test('empty palettes, alpha and unsupported matching keep reference behavior',()=>{
  const result=vm.runInContext(`(()=>{
    for(const matching of ['rgb','lab','chroma'])for(const palette of [[],[[1,2,3,90],[254,253,252,200]]]){
      const color=[100,120,130,140];
      if(JSON.stringify(it(color,palette,matching))!==JSON.stringify(referenceNearest(color,palette,matching)))return false;
    }return true;
  })()`,context);
  assert.equal(result,true);
});
