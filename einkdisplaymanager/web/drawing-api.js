// Executed inside QuickJS, never in the browser. No Python callbacks or host handles.
(function(input, source){
  'use strict';
  const stringify=JSON.stringify, parse=JSON.parse, freeze=Object.freeze;
  const commands=[], limit=1000;
  function safe(value){
    if(value&&typeof value==='object'){
      for(const key of Object.keys(value))safe(value[key]);
      freeze(value);
    }
    return value;
  }
  const values=safe(input.states), warnings=[];
  const add=(type, options)=>{
    if(commands.length>=limit)throw new Error('At most 1000 drawing commands are allowed.');
    const plain=parse(stringify(options));
    commands.push({...plain,type});
  };
  const screen=freeze({width:input.width,height:input.height,
    clear(color='#ffffff'){add('clear',{color});},
    text(text,options={}){add('text',{...options,text:String(text)});},
    line(options){add('line',options);},rectangle(options){add('rectangle',options);},
    circle(options){add('circle',options);},image(id,options={}){add('image',{...options,id:String(id)});}
  });
  const ha=freeze({
    state(id,fallback=null){const s=values[id];return !s||['unknown','unavailable'].includes(s.state)?fallback:s.state;},
    number(id,fallback=null){const s=this.state(id);if(s===null||String(s).trim()==='')return fallback;const n=Number(s);return Number.isFinite(n)?n:fallback;},
    attribute(id,name,fallback=null){return values[id]?.attributes?.[name]??fallback;}
  });
  const palette=freeze(input.palette), now=safe(input.now);
  // A fresh runtime and scope per invocation; any source escaping this function
  // still has no privileged globals. Host independently validates every command.
  const run=new Function('screen','ha','palette','now','"use strict";\n'+source);
  run(screen,ha,palette,now);
  const result=stringify({commands,warnings});
  if(result.length>262144)throw new Error('Drawing output exceeds 256 KiB.');
  return result;
})(JSON.parse(__input),__source)
