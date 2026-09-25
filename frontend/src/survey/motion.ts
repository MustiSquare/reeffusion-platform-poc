export type MotionSample={t:number;n:number;roll:number;pitch:number;roll_mean:number;pitch_mean:number;roll_m2:number;pitch_m2:number};
export function motionAt(samples:MotionSample[],cursor:number){
  const rows=samples.filter(s=>s.t<=cursor&&s.t>cursor-30&&s.n>0);
  const last=rows[rows.length-1];
  if(!last||cursor-last.t>3)return null;
  const n=rows.reduce((sum,s)=>sum+s.n,0);
  const variation=(key:'roll'|'pitch')=>{
    const mean=rows.reduce((sum,s)=>sum+s.n*s[`${key}_mean`],0)/n;
    return Math.sqrt(Math.max(0,rows.reduce((sum,s)=>sum+s[`${key}_m2`]+s.n*(s[`${key}_mean`]-mean)**2,0)/n));
  };
  return {roll:last.roll,pitch:last.pitch,rollVariation:variation('roll'),pitchVariation:variation('pitch'),seconds:rows.length,n};
}
