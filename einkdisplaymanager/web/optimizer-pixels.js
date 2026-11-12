// Trusted server-only pixel transport and final palette encoding. All output
// stays ASCII hex because the pinned Python wrapper truncates returned NULs.
(function(){
  const hex=Array.from({length:256},(_,i)=>i.toString(16).padStart(2,'0'));
  function decodeRGBA(raw,width,height){
    if(raw.length!==width*height*4)throw new Error('Invalid RGBA buffer length.');
    const data=new Uint8ClampedArray(raw.length);
    for(let i=0;i<data.length;i++)data[i]=raw.charCodeAt(i);
    return {width,height,data};
  }
  function encodeIndices(pixels,palette,gray,levels){
    const codes={black:0,blue:1,green:2,red:3,yellow:5,white:6};
    const colors=palette.map(p=>({code:gray?levels[Number(p.name.slice(4))]:codes[p.name],
      rgb:p.color.match(/[a-f0-9]{2}/gi).map(v=>parseInt(v,16))}));
    const exact=new Map(),fallback=new Map();
    for(const color of colors){
      const [r,g,b]=color.rgb,key=(r<<16)|(g<<8)|b;
      if(!exact.has(key))exact.set(key,color.code); // Reference tie rule: first color.
    }
    const chunks=[];let chunk='',lastKey=-1,lastHex='';
    for(let i=0;i<pixels.data.length;i+=4){
      const r=pixels.data[i],g=pixels.data[i+1],b=pixels.data[i+2],key=(r<<16)|(g<<8)|b;
      if(key!==lastKey){
        let code=exact.get(key);
        if(code===undefined){
          code=fallback.get(key);
          if(code===undefined){
            let best=colors[0],distance=Infinity;
            for(const color of colors){
              const d=(r-color.rgb[0])**2+(g-color.rgb[1])**2+(b-color.rgb[2])**2;
              if(d<distance){distance=d;best=color;}
            }
            code=best.code;
            if(fallback.size>=4096)fallback.clear();
            fallback.set(key,code);
          }
        }
        lastHex=hex[code];lastKey=key;
      }
      chunk+=lastHex;
      if(chunk.length>=8192){chunks.push(chunk);chunk='';}
    }
    chunks.push(chunk);return chunks.join('');
  }
  globalThis.einkPixels={decodeRGBA,encodeIndices};
})();
