// Only methods supported by the vendored epdoptimize 1.2.0 build are offered.
export const DITHERS = {
  floyd:{name:'Floyd–Steinberg', type:'errorDiffusion', matrix:'floydSteinberg', use:'A useful baseline for photos and mixed content. Fine grain and good local detail; some areas may show directional patterns.'},
  atkinson:{name:'Atkinson', type:'errorDiffusion', matrix:'atkinson', use:'Try for high-contrast illustrations, line art, and text. Its lighter error spread can keep edges clear but may lose subtle tones.'},
  stucki:{name:'Stucki', type:'errorDiffusion', matrix:'stucki', use:'Try for photographic gradients, skin tones, and skies. A wider error spread smooths transitions; fine details can look softer.'},
  jarvis:{name:'Jarvis–Judice–Ninke', type:'errorDiffusion', matrix:'jarvis', use:'Try for smooth photographic gradients. Spreads error over more neighbors and may soften fine lines; processing can take longer.'},
  burkes:{name:'Burkes', type:'errorDiffusion', matrix:'burkes', use:'A smaller, faster relative of Stucki. Try when you want smoother gradients without as much processing or blur.'},
  sierra3:{name:'Sierra-3', type:'errorDiffusion', matrix:'sierra3', use:'Another photographic option balancing gradients and detail. Compare with Stucki on the actual frame; neither is universally better.'},
  ordered:{name:'Ordered Bayer · 4 × 4', type:'ordered', use:'A regular repeating pattern. Useful for graphics and consistent texture, but the grid may be visible in photos and smooth skies.'},
  blueNoise:{name:'Blue-noise style · experimental', type:'blueNoise', use:'Uses the bundled 64 × 64 high-frequency tile in optimizer 1.2.0. Try for a less directional texture; inspect gradients and color balance on the frame.'},
  none:{name:'None · nearest color', type:'quantizationOnly', use:'No simulated intermediate shades. Useful for icons, text, and artwork already using the target palette; photos may show banding.'},
};

export const PALETTES = {
  natural:{name:'Spectra 6 · original RGB', use:'Matches against ideal RGB primaries; useful as a reference, but reflective ink differs from a bright screen.'},
  spectra6:{name:'Spectra 6 · calibrated library palette', use:'Matches the library’s calibrated ink colors before exporting native codes. Try with Floyd–Steinberg or Stucki for photos. Not calibrated to your individual panel.'},
  aitjcize:{name:'Spectra 6 · alternative calibrated palette', use:'An alternative library palette inspired by epaper-image-convert. Compare color balance with the calibrated Spectra 6 palette on your frame.'},
  vivid:{name:'Spectra 6 · vivid automatic adjustment', use:'Uses the original RGB palette with a vivid automatic intent. Can help muted images; bright colors may be exaggerated.'},
  gray8:{name:'Inkplate · eight grayscale levels', use:'Uses all eight grayscale levels, including black and white. Set greyscale: true in ESPHome. Try Floyd–Steinberg or Stucki for photos, or None for crisp text and prepared graphics.'},
  grayscale:{name:'Black and white', use:'Restricts output to the black and white display codes. Useful for monochrome artwork, text, and intentional black/white photos.'},
};

export const MATCHING = {
  rgb:{name:'RGB · predictable baseline',use:'Compares distances between red, green, and blue values. A fast, predictable baseline for graphics, pure colors, and comparing palettes; equal RGB distances do not always look equally different to the eye.'},
  lab:{name:'Perceptual LAB · compare on frame',use:'Compares colors in a space that approximates human perception. Try for photos, skin tones, and subtle colors; processing can take longer and palette choices still matter. Compare the result on your frame.'},
};

export function ditherOptions(value){
  const method=DITHERS[value];
  if(!method)throw new Error('Choose a supported dithering method.');
  return {ditheringType:method.type,errorDiffusionMatrix:method.matrix||'floydSteinberg',orderedDitheringMatrix:[4,4]};
}
