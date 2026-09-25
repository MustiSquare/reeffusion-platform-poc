import { Block } from './model';
export const MAX_MAP_POINTS=6000;
// Only the map preview is sampled; source blocks remain untouched for processing.
export function mapDisplayBlocks(blocks:Block[],limit=MAX_MAP_POINTS):Block[]{
  const total=blocks.reduce((sum,b)=>sum+b.points.length,0);
  if(total<=limit)return blocks;
  const stride=Math.ceil(total/limit);
  let seen=0;
  return blocks.map(block=>{
    const points:Block['points']=[];
    for(let i=(stride-seen%stride)%stride;i<block.points.length;i+=stride)points.push(block.points[i]);
    seen+=block.points.length;
    return {...block,points};
  });
}
