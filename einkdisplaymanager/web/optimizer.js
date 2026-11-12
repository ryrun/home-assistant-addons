import {ditherImage, suggestCanvasProcessingOptions, spectra6OriginalPalette, spectra6Palette, aitjcizeSpectra6Palette} from './vendor/epdoptimize-1.4.1.mjs';
import {measuredOpenPaperLPalette} from './panel-palettes.js';
import {processingOptions} from './optimizer-options.js';
import {viewSize,transportRotated} from './profiles.js';

// Processing runs in a dedicated worker, always from the full normalized source.
const codes = {black:0, blue:1, green:2, red:3, yellow:5, white:6};
const deviceRGB = [[0,0,0],[0,0,255],[0,255,0],[255,0,0],null,[255,255,0],[255,255,255]];

function bmp(indices,W,H) {
  const output = new Uint8Array(118 + W * H / 2);
  const v = new DataView(output.buffer);
  output[0]=66; output[1]=77;
  v.setUint32(2,output.length,true); v.setUint32(10,118,true); v.setUint32(14,40,true);
  v.setInt32(18,W,true); v.setInt32(22,-H,true); v.setUint16(26,1,true);
  v.setUint16(28,4,true); v.setUint32(34,W*H/2,true);
  v.setInt32(38,2835,true); v.setInt32(42,2835,true); v.setUint32(46,16,true); v.setUint32(50,16,true);
  for(let i=0;i<deviceRGB.length;i++) {
    const rgb=deviceRGB[i]; if(!rgb) continue;
    output.set([rgb[2],rgb[1],rgb[0],0],54+i*4);
  }
  for(let i=0;i<W*H;i++) {
    const code=indices[i];
    if(i%2===0) output[118+(i>>1)]=code<<4; else output[118+(i>>1)]|=code;
  }
  return output;
}

self.onmessage = async ({data}) => {
  let image;
  let stage = 'decoding the source image';
  try {
    if(typeof createImageBitmap!=='function'||typeof OffscreenCanvas!=='function')throw new Error('This browser does not support image processing in a worker. Update your browser and try again.');
    const {source, recipe}=data;
    stage='loading the display profile';
    const response=await fetch(new URL('./profiles.json',import.meta.url),{cache:'no-store'});
    if(!response.ok)throw new Error('Could not load supported display models. Reload the add-on page and try again.');
    const profile=(await response.json()).find(p=>p.id===(recipe.profile||'openpaper_l'));
    if(!profile)throw new Error('Choose a supported display model.');
    const W=profile.width,H=profile.height,mounting=recipe.orientation||profile.native_orientation;
    if(!['portrait','landscape'].includes(mounting))throw new Error('Choose portrait or landscape.');
    const [viewW,viewH]=viewSize(profile,mounting),rotateTransport=transportRotated(profile,mounting);
    stage='decoding the source image';
    self.postMessage({progress:'Decoding source image…'});
    image=await createImageBitmap(source);
    const canvas=new OffscreenCanvas(viewW,viewH), ctx=canvas.getContext('2d',{willReadFrequently:true});
    if(!ctx)throw new Error('The browser could not allocate the image canvas. Close other image editors and try again.');
    stage='preparing the composition';
    ctx.fillStyle='#fff'; ctx.fillRect(0,0,viewW,viewH);
    const rotated=recipe.rotation===90||recipe.rotation===270;
    const vw=rotated?image.height:image.width, vh=rotated?image.width:image.height;
    const scale=(recipe.fit==='cover'?Math.max:Math.min)(viewW/vw,viewH/vh);
    const fx=recipe.fit==='cover'?(viewW-vw*scale)*((recipe.focusX??50)/100-.5):0;
    const fy=recipe.fit==='cover'?(viewH-vh*scale)*((recipe.focusY??50)/100-.5):0;
    ctx.save(); ctx.translate(viewW/2+fx,viewH/2+fy); ctx.rotate(recipe.rotation*Math.PI/180);
    ctx.drawImage(image,-image.width*scale/2,-image.height*scale/2,image.width*scale,image.height*scale); ctx.restore();
    image.close();image=null;
    const gray=profile.palette==='gray8',levels=Array.from({length:8},(_,i)=>Math.round(i*255/7));
    if(gray){
      const monochrome=ctx.getImageData(0,0,viewW,viewH);
      for(let p=0;p<monochrome.data.length;p+=4){const value=Math.round(.299*monochrome.data[p]+.587*monochrome.data[p+1]+.114*monochrome.data[p+2]);monochrome.data[p]=monochrome.data[p+1]=monochrome.data[p+2]=value;}
      ctx.putImageData(monochrome,0,0);
    }
    const grayPalette=levels.map((value,i)=>({name:`gray${i}`,color:'#'+value.toString(16).padStart(2,'0').repeat(3)}));
    const basePalette=gray?grayPalette:recipe.palette==='openpaper_l_measured'?measuredOpenPaperLPalette:recipe.palette==='spectra6'?spectra6Palette:recipe.palette==='aitjcize'?aitjcizeSpectra6Palette:spectra6OriginalPalette;
    let palette=basePalette.map(p=>({...p}));
    if(recipe.palette==='grayscale') palette=palette.filter(p=>gray?p.name==='gray0'||p.name==='gray7':p.name==='black'||p.name==='white');
    const invert=gray&&recipe.invert===true;
    const intent=recipe.intent||(recipe.palette==='vivid'?'vivid':'natural');
    let suggestion=null;
    if(recipe.automatic) {
      const sample=new OffscreenCanvas(viewW/4,viewH/4);
      sample.getContext('2d').drawImage(canvas,0,0,sample.width,sample.height);
      suggestion=suggestCanvasProcessingOptions(sample,palette,{intent});
    }
    const {options,analysis}=processingOptions(recipe,suggestion);
    options.palette=palette;
    stage='applying color matching and dithering';
    self.postMessage({progress:'Applying color matching and dithering…'});
    await ditherImage(canvas,canvas,options);
    const pixels=ctx.getImageData(0,0,viewW,viewH), indices=new Uint8Array(W*H);
    const colors=palette.map(p=>({code:gray?levels[Number(p.name.slice(4))]:codes[p.name],rgb:p.color.match(/[a-f0-9]{2}/gi).map(x=>parseInt(x,16))}));
    for(let i=0;i<indices.length;i++) {
      const p=i*4; let best=colors[0], distance=Infinity;
      for(const color of colors) {
        const d=(pixels.data[p]-color.rgb[0])**2+(pixels.data[p+1]-color.rgb[1])**2+(pixels.data[p+2]-color.rgb[2])**2;
        if(d<distance){distance=d;best=color;}
      }
      const value=invert?255-best.code:best.code;
      indices[i]=value;
      const rgb=gray?[value,value,value]:deviceRGB[value]; pixels.data[p]=rgb[0];pixels.data[p+1]=rgb[1];pixels.data[p+2]=rgb[2];pixels.data[p+3]=255;
    }
    ctx.putImageData(pixels,0,0);
    // A view mounted clockwise from native needs counter-clockwise transport.
    // Only pixel positions change: never run dithering a second time.
    let native=indices;
    if(rotateTransport){
      native=new Uint8Array(W*H);
      for(let y=0;y<viewH;y++)for(let x=0;x<viewW;x++)native[(H-1-x)*W+y]=indices[y*viewW+x];
    }
    stage='encoding the output';
    self.postMessage({progress:'Encoding display output…'});
    let output,mime='image/bmp';
    if(gray){
      const nativeCanvas=new OffscreenCanvas(W,H),nativeContext=nativeCanvas.getContext('2d');
      const raster=nativeContext.createImageData(W,H);
      for(let i=0;i<native.length;i++){const at=i*4;raster.data[at]=raster.data[at+1]=raster.data[at+2]=native[i];raster.data[at+3]=255;}
      nativeContext.putImageData(raster,0,0);
      output=new Uint8Array(await (await nativeCanvas.convertToBlob({type:'image/png'})).arrayBuffer());mime='image/png';
    }else output=bmp(native,W,H);
    const preview=await canvas.convertToBlob({type:'image/png'});
    self.postMessage({bmp:output.buffer,mime,preview,recipe:{...recipe,intent,invert,automaticAnalysis:analysis,orientation:mounting,nativeRotation:rotateTransport?270:0,nativeWidth:W,nativeHeight:H,viewWidth:viewW,viewHeight:viewH,resolvedOptions:options,optimizer:'epdoptimize@1.4.1',profile:profile.id,encoder:7}},[output.buffer]);
  } catch(error) { self.postMessage({error:`Image optimization failed while ${stage}. ${error.message||'Close other image editors and try again.'}`}); }
  finally { image?.close(); }
};
self.postMessage({ready:true});
