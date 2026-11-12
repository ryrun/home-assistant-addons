import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import vm from 'node:vm';
const ctx=vm.createContext({});
vm.runInContext(readFileSync(new URL('../web/optimizer-pixels.js',import.meta.url),'utf8'),ctx);
test('RGBA transport preserves every byte including NUL and high Latin-1 values',()=>{
  const bytes=Array.from({length:1024},(_,i)=>i%256),raw=String.fromCharCode(...bytes);
  ctx.raw=raw;
  const result=vm.runInContext('Array.from(einkPixels.decodeRGBA(raw,16,16).data)',ctx);
  assert.deepEqual(Array.from(result),bytes);
  assert.throws(()=>vm.runInContext('einkPixels.decodeRGBA(raw,1,1)',ctx),/buffer length/);
});
test('palette encoding preserves reference nearest results including post-filter colors and ties',()=>{
  const result=vm.runInContext(`(()=>{
    const levels=Array.from({length:8},(_,i)=>Math.round(i*255/7));
    const palettes=[{gray:false,palette:[{name:'black',color:'#000000'},{name:'white',color:'#ffffff'},{name:'red',color:'#ff0000'},{name:'blue',color:'#0000ff'}]},
      {gray:true,palette:levels.map((v,i)=>({name:'gray'+i,color:'#'+v.toString(16).padStart(2,'0').repeat(3)}))},
      {gray:false,palette:[{name:'black',color:'#808080'},{name:'red',color:'#808080'}]}];
    let seed=711;
    for(const {gray,palette} of palettes){
      const codes={black:0,white:6,red:3,blue:1};
      const colors=palette.map(p=>({code:gray?levels[Number(p.name.slice(4))]:codes[p.name],rgb:p.color.match(/[a-f0-9]{2}/gi).map(v=>parseInt(v,16))}));
      const data=new Uint8ClampedArray(24000);
      for(let p=0;p<data.length;p+=4){seed=(1664525*seed+1013904223)>>>0;data.set([seed&255,(seed>>>8)&255,(seed>>>16)&255,255],p);}
      data.set([0,0,0,255,255,255,255,255,255,0,0,255]);
      let expected='';
      for(let p=0;p<data.length;p+=4){let best=colors[0],distance=Infinity;
        for(const c of colors){const d=(data[p]-c.rgb[0])**2+(data[p+1]-c.rgb[1])**2+(data[p+2]-c.rgb[2])**2;if(d<distance){best=c;distance=d;}}
        expected+=best.code.toString(16).padStart(2,'0');
      }
      const actual=einkPixels.encodeIndices({data},palette,gray,levels);
      if(actual!==expected)return false;
    }return true;
  })()`,ctx);
  assert.equal(result,true);
});
