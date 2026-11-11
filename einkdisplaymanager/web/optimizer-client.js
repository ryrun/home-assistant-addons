// Own worker lifetime, startup handshake, cancellation, and bounded waits.
export async function optimizeImage({source,recipe,signal,onProgress=()=>{},startupTimeout=15000,processingTimeout=180000}){
  for(let attempt=0;attempt<2;attempt++){
    try{return await execute();}
    catch(error){if(signal.aborted||!error.startup||attempt)throw error;onProgress('Restarting optimizer…');}
  }

  function execute(){return new Promise((resolve,reject)=>{
    let worker,timer,ready=false,settled=false;
    const finish=(error,result)=>{if(settled)return;settled=true;clearTimeout(timer);worker?.terminate();signal.removeEventListener('abort',cancel);error?reject(error):resolve(result);};
    const cancel=()=>finish(new DOMException('Optimization cancelled.','AbortError'));
    const fail=message=>{const error=new Error(message);error.startup=!ready;finish(error);};
    if(signal.aborted){cancel();return;}
    signal.addEventListener('abort',cancel,{once:true});
    onProgress('Starting optimizer…');
    timer=setTimeout(()=>fail('Optimizer could not start within 15 seconds. Reload the add-on page and try again.'),startupTimeout);
    try{
      worker=new Worker(new URL('./optimizer.js',import.meta.url),{type:'module'});
      worker.onmessage=({data})=>{
        if(data.ready){if(ready)return;ready=true;clearTimeout(timer);timer=setTimeout(()=>fail('Image processing exceeded 3 minutes. Close other image editors and try again.'),processingTimeout);worker.postMessage({source,recipe});}
        else if(data.progress){onProgress(data.progress);}
        else if(data.error){fail(data.error);}
        else if(data.bmp instanceof ArrayBuffer&&data.preview instanceof Blob){finish(null,data);}
        else{fail('The optimizer returned an unreadable result. Reload the add-on page and try again.');}
      };
      worker.onerror=event=>{event.preventDefault();fail(ready?'The optimizer stopped while processing this image. Close other image editors and try again.':'Optimizer could not start. Its browser module could not load; reload the add-on page and check the connection.');};
      worker.onmessageerror=()=>fail('The browser could not read the optimizer result. Reload the add-on page and try again.');
    }catch(error){fail(`Optimizer could not start. ${error.message||'Check browser support and reload the add-on page.'}`);}
  });}
}
