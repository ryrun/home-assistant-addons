// Geometry is independent of the panel's native row orientation.
export function viewSize(profile,orientation){
  const short=Math.min(profile.width,profile.height),long=Math.max(profile.width,profile.height);
  return orientation==='landscape'?[long,short]:[short,long];
}

export function transportRotated(profile,orientation){return orientation!==profile.native_orientation;}

export function originalProfile(asset,profiles){
  return asset.native_profile||profiles.find(p=>asset.mime==='image/bmp'&&asset.width===p.width&&asset.height===p.height&&asset.bytes===118+p.width*p.height/2)?.id||null;
}

export function originalCompatible(asset,profileId,profiles){
  const native=originalProfile(asset,profiles);
  return asset.original_supported&&(!native||native===profileId);
}
