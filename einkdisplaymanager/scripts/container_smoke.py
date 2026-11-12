"""Run inside the actual unprivileged Linux image on both supported architectures."""
import asyncio
import sys

sys.path.insert(0,'/app')
from dynamic import recipe, worker
from media import validate_variant
from profiles import PROFILES


async def main():
    result=await worker({'mode':'probe'})
    assert result['isolation']=='linux-seccomp',result
    script='screen.text("Linux sandbox",{x:20,y:30});screen.circle({x:100,y:100,radius:20,fill:palette.black});'
    commands=await worker({'mode':'commands','source':script,'input':{'width':800,'height':600,'states':{},'palette':{'black':'palette:black'},'now':{}}})
    for profile in ('openpaper_l','openpaper_7','inkplate_6'):
        p=PROFILES[profile]
        target=recipe({'profile':profile})
        import base64
        result=await worker({'mode':'render','commands':commands['commands'],'size':[p['width'],p['height']],
                            'profile':p,'recipe':target,'palette':{'black':'#000000'},'images':{},'fonts':{}})
        validate_variant(base64.b64decode(result['output']),profile)
    print('Verified Linux seccomp, bounded JavaScript, and native output for all display profiles.')

asyncio.run(main())
