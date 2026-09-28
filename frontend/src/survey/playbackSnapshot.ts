import type {Block,Boat,Point,Replay} from './model';

type State={blocks:Block[];boat:Boat|null;boatTime:number;track:Boat[]};
// Advance through each frame once. Published snapshots never share mutable bins.
export function createPlaybackSnapshot(replay:Replay,size:number){
  let next=0,last=-Infinity;
  let bins=new Map<string,Map<string,Point>>();
  let blocks=new Map<string,Block>();
  let state:State={blocks:[],boat:null,boatTime:0,track:[]};
  return (until:number):State=>{
    if(until<last){next=0;bins=new Map();blocks=new Map();state={blocks:[],boat:null,boatTime:0,track:[]};}
    last=until;
    const dirty=new Set<string>();let boat=state.boat,boatTime=state.boatTime;
    const additions:Boat[]=[];
    while(next<replay.frames.length&&replay.frames[next].t<=until){
      const frame=replay.frames[next++];
      if(frame.boat){boat=frame.boat;boatTime=frame.t;additions.push(boat);}
      for(const point of frame.points){
        const [x,y]=point,column=Math.floor(x/size),row=Math.floor(y/size),key=`${column}:${row}`;
        if(!blocks.has(key)){blocks.set(key,{key,column,row,points:[],coverage:0,last:frame.t,samples:0});bins.set(key,new Map());}
        if(!dirty.has(key)){blocks.set(key,{...blocks.get(key)!});dirty.add(key);}
        const block=blocks.get(key)!;block.last=frame.t;block.samples+=point[5];
        const cell=bins.get(key)!,binKey=`${Math.floor(x)}:${Math.floor(y)}`,previous=cell.get(binKey);
        if(!previous)cell.set(binKey,[...point]);
        else{
          const count=previous[5]+point[5];
          for(let i=0;i<5;i++)previous[i]=(previous[i]*previous[5]+point[i]*point[5])/count;
          previous[5]=count;
        }
      }
    }
    for(const key of dirty){
      const block=blocks.get(key)!;
      block.points=[...bins.get(key)!.values()].map(p=>[...p] as Point);
      const occupied=new Set(block.points.map(p=>`${Math.floor((p[0]-block.column*size)/5)}:${Math.floor((p[1]-block.row*size)/5)}`));
      block.coverage=Math.min(1,occupied.size/Math.ceil(size/5)**2);
    }
    if(dirty.size||additions.length)state={blocks:dirty.size?[...blocks.values()]:state.blocks,boat,boatTime,track:additions.length?[...state.track,...additions]:state.track};
    return state;
  };
}
