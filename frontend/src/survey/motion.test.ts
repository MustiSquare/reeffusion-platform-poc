import {expect,it} from 'vitest';
import {motionAt,MotionSample} from './motion';
const sample=(t:number):MotionSample=>({t,n:2,roll:12,pitch:4,roll_mean:10,pitch_mean:3,roll_m2:8,pitch_m2:2});
it('retains within-second variation and removes constant tilt',()=>{
  const motion=motionAt([sample(1),sample(2)],2)!;
  expect(motion.rollVariation).toBe(2);expect(motion.pitchVariation).toBe(1);expect(motion.n).toBe(4);
});
it('excludes future samples, expired samples and stale readings',()=>{
  expect(motionAt([sample(1)],0)).toBeNull();
  expect(motionAt([sample(1)],5)).toBeNull();
  const motion=motionAt([sample(1),sample(31),{...sample(32),roll_mean:99}],31)!;
  expect(motion.n).toBe(2);expect(motion.rollVariation).toBe(2);
});
