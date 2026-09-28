import {expect,it} from 'vitest';
import {snapshot,Replay,Point} from './model';
import {createPlaybackSnapshot} from './playbackSnapshot';
const replay:Replay={id:'test',name:'test',started_at:'2026-08-21T20:15:00Z',duration:100,crs:'EPSG:32605',point_count:1000,warnings:[],reduction:'test',frames:Array.from({length:101},(_,t)=>({t,boat:t%3?[0,0,t,0,0]:null,points:Array.from({length:10},(_,i)=>[i*13+t%3,i*7,-t-i,-155,20,1+t%5] as Point)}))};
it('matches full reconstruction across advances, end-of-file and backwards seeks for every grid',()=>{
  for(const size of [25,50,100,200]){
    const read=createPlaybackSnapshot(replay,size);
    for(const time of [-1,0,1,3,50,50,99,100,20,0,60,100])expect(read(time)).toEqual(snapshot(replay,time,size));
  }
});
it('keeps old snapshots immutable when later soundings update their bins',()=>{
  const read=createPlaybackSnapshot(replay,50),first=read(4),copy=structuredClone(first);
  read(50);read(100);read(0);
  expect(first).toEqual(copy);
});
it('does not scan earlier frames again on forward playback or repeat renders',()=>{
  let visits=0;
  const observed={...replay,frames:replay.frames.map(f=>({...f,get points(){visits++;return f.points;}}))};
  const read=createPlaybackSnapshot(observed,50);
  read(50);expect(visits).toBe(51);const same=read(50);expect(read(50)).toBe(same);expect(visits).toBe(51);
  read(100);expect(visits).toBe(101);
});
