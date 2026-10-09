// Turbo polynomial coefficients: Copyright 2019 Google LLC.
// SPDX-License-Identifier: Apache-2.0
// Colormap: Anton Mikhailov; polynomial approximation: Ruofei Du.
// https://gist.github.com/mikhailov-work/0d177465a8151eb6ede1768d51d476c7
// Shared CPU/GPU implementation adapted to evaluate with Horner's method.
export const TURBO_COEFFICIENTS=[
  [.13572138,4.61539260,-42.66032258,132.13108234,-152.94239396,59.28637943],
  [.09140261,2.19418839,4.84296658,-14.18503333,4.27729857,2.82956604],
  [.10667330,12.64194608,-60.58204836,110.36276771,-89.90310912,27.34824973],
] as const;
export function turboColour(value:number){
  const t=Math.max(0,Math.min(1,value));
  return TURBO_COEFFICIENTS.map(c=>Math.max(0,Math.min(1,c.reduceRight((sum,v)=>v+t*sum,0))));
}
export function depthColour(z:number,range:readonly number[]){
  const t=Math.max(0,Math.min(1,(z-range[0])/Math.max(.001,range[1]-range[0])));
  return turboColour(t);
}
export const turboGLSL=`vec3 turboColour(float x){x=clamp(x,0.0,1.0);return clamp(vec3(${TURBO_COEFFICIENTS.map(c=>c.reduceRight((sum,v)=>`(${v.toFixed(8)}+x*${sum})`,'0.0')).join(',')}),0.0,1.0);}`;
export const depthPaletteGLSL='turboColour(depthColour)';
export const turboGradient=`linear-gradient(to right,${Array.from({length:17},(_,i)=>`rgb(${turboColour(i/16).map(v=>Math.round(v*255)).join(',')})`).join(',')})`;
