// Trusted QuickJS adapter for the hash-pinned epdoptimize 1.4.1 module.
// Keep the browser's reference implementation unchanged. Its it() allocates a
// palette-sized array and recalculates palette LAB for EVERY pixel. Reuse the
// library's own precomputed error-diffusion selector instead; distances and the
// first-color tie rule are identical for RGB/LAB. No color approximation occurs.
(function(){
  const reference=it, selectors=new WeakMap(), maximumEntries=4096;
  it=function(color,palette,matching='rgb',original=color){
    if(!palette.length||!['rgb','lab'].includes(matching))return reference(color,palette,matching,original);
    let modes=selectors.get(palette);
    if(!modes){modes=new Map();selectors.set(palette,modes);}
    let entry=modes.get(matching);
    if(!entry){entry={selector:zn(palette,matching),colors:new Map(),lastKey:-1,lastIndex:0};modes.set(matching,entry);}
    const r=color[0],g=color[1],b=color[2];
    // Memoize only exact byte-valued colors. Ordered dithering may pass floats
    // or out-of-range values; those must retain their original precision.
    const cacheable=Number.isInteger(r)&&Number.isInteger(g)&&Number.isInteger(b)&&r>=0&&r<=255&&g>=0&&g<=255&&b>=0&&b<=255;
    let index;
    if(cacheable){
      const key=(r<<16)|(g<<8)|b;
      if(key===entry.lastKey)index=entry.lastIndex;
      else{
        index=entry.colors.get(key);
        if(index===undefined){
          index=entry.selector.findIndex(r,g,b,r,g,b);
          if(entry.colors.size>=maximumEntries)entry.colors.clear();
          entry.colors.set(key,index);
        }
        entry.lastKey=key;entry.lastIndex=index;
      }
    }else index=entry.selector.findIndex(r,g,b,r,g,b);
    return rt(palette[index]);
  };
})();
