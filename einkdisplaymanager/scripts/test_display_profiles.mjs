import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {viewSize,transportRotated,originalCompatible} from '../web/profiles.js';

const profiles=JSON.parse(readFileSync(new URL('../web/profiles.json',import.meta.url)));
const profile=id=>profiles.find(p=>p.id===id);
for(const [id,orientation,size,rotated] of [
  ['openpaper_l','portrait',[1200,1600],false],['openpaper_l','landscape',[1600,1200],true],
  ['openpaper_7','landscape',[800,480],false],['openpaper_7','portrait',[480,800],true],
  ['inkplate_6','landscape',[800,600],false],['inkplate_6','portrait',[600,800],true],
])test(`${id} ${orientation} preserves its native raster contract`,()=>{
  assert.deepEqual(viewSize(profile(id),orientation),size);
  assert.equal(transportRotated(profile(id),orientation),rotated);
});

test('Inkplate original delivery can convert PNG while OpenPaper still requires compatible originals',()=>{
  const png={mime:'image/png',width:123,height:234,bytes:100,original_supported:false};
  assert.equal(originalCompatible(png,'inkplate_6',profiles),true);
  assert.equal(originalCompatible(png,'openpaper_7',profiles),false);
  assert.equal(originalCompatible({...png,native_profile:'openpaper_7'},'inkplate_6',profiles),false);
});

test('prepared originals are model-specific, including old metadata without native_profile',()=>{
  const legacy={mime:'image/bmp',width:800,height:480,bytes:192118,original_supported:true};
  assert.equal(originalCompatible(legacy,'openpaper_7',profiles),true);
  assert.equal(originalCompatible(legacy,'openpaper_l',profiles),false);
  assert.equal(originalCompatible({...legacy,mime:'image/jpeg'},'openpaper_l',profiles),true);
});
