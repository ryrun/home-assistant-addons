import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {viewSize,transportRotated,originalCompatible} from '../web/profiles.js';

const profiles=JSON.parse(readFileSync(new URL('../web/profiles.json',import.meta.url)));
const profile=id=>profiles.find(p=>p.id===id);
for(const [id,orientation,size,rotated] of [
  ['openpaper_l','portrait',[1200,1600],false],['openpaper_l','landscape',[1600,1200],true],
  ['openpaper_7','landscape',[800,480],false],['openpaper_7','portrait',[480,800],true],
])test(`${id} ${orientation} preserves its native raster contract`,()=>{
  assert.deepEqual(viewSize(profile(id),orientation),size);
  assert.equal(transportRotated(profile(id),orientation),rotated);
});

test('prepared originals are model-specific, including old metadata without native_profile',()=>{
  const legacy={mime:'image/bmp',width:800,height:480,bytes:192118,original_supported:true};
  assert.equal(originalCompatible(legacy,'openpaper_7',profiles),true);
  assert.equal(originalCompatible(legacy,'openpaper_l',profiles),false);
  assert.equal(originalCompatible({...legacy,mime:'image/jpeg'},'openpaper_l',profiles),true);
});
