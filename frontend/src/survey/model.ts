import proj4 from 'proj4';

export type Point = [number, number, number, number, number, number];
export type Boat = [number, number, number, number, number];
export type Frame = { t: number; boat: Boat | null; points: Point[] };
export type Replay = { id: string; name: string; started_at: string; duration: number; crs: string; frames: Frame[]; point_count: number; warnings: string[]; reduction: string };
export type Block = { key: string; column: number; row: number; points: Point[]; coverage: number; last: number; samples: number };

export function converter(crs: string) {
  const epsg = Number(crs.split(':')[1]);
  const zone = epsg % 100;
  return proj4(`+proj=utm +zone=${zone} ${epsg >= 32700 ? '+south' : ''} +datum=WGS84 +units=m +no_defs`, 'EPSG:4326');
}

export function snapshot(replay: Replay, until: number, size: number) {
  const blocks = new Map<string, Block>();
  const bins = new Map<string, Map<string, Point>>();
  const track: Boat[] = [];
  let boat: Boat | null = null;
  let boatTime = 0;
  for (const frame of replay.frames) {
    if (frame.t > until) break;
    if (frame.boat) { boat = frame.boat; boatTime = frame.t; track.push(boat); }
    for (const point of frame.points) {
      const [x, y] = point;
      const column = Math.floor(x / size), row = Math.floor(y / size), key = `${column}:${row}`;
      if (!blocks.has(key)) {
        blocks.set(key, { key, column, row, points: [], coverage: 0, last: frame.t, samples: 0 });
        bins.set(key, new Map());
      }
      const block = blocks.get(key)!;
      block.last = frame.t; block.samples += point[5];
      const binKey = `${Math.floor(x)}:${Math.floor(y)}`;
      const previous = bins.get(key)!.get(binKey);
      if (!previous) bins.get(key)!.set(binKey, [...point]);
      else {
        const count = previous[5] + point[5];
        for (let i = 0; i < 5; i++) previous[i] = (previous[i] * previous[5] + point[i] * point[5]) / count;
        previous[5] = count;
      }
    }
  }
  for (const block of blocks.values()) {
    block.points = [...bins.get(block.key)!.values()];
    // Occupied 5 m cells, not a claim of full acoustic coverage of those cells.
    const occupied = new Set(block.points.map(p => `${Math.floor((p[0]-block.column*size)/5)}:${Math.floor((p[1]-block.row*size)/5)}`));
    block.coverage = Math.min(1, occupied.size / Math.ceil(size/5)**2);
  }
  return { blocks: [...blocks.values()], boat, boatTime, track };
}

export function canProcess(block: Block) {
  return block.points.length >= 4 && new Set(block.points.map(p => p[0])).size > 1 && new Set(block.points.map(p => p[1])).size > 1;
}

export function needsProcessing(block: Block, job: {status:string;samples:number}|undefined, cursor:number, duration:number) {
  if (!canProcess(block)) return false;
  const finished = cursor >= duration;
  // Flush every usable partial cell at EOF, including small revisions to earlier results.
  const ready = finished || (block.coverage >= .6 && cursor - block.last >= 10);
  if (!ready) return false;
  if (!job) return true;
  if (job.status !== 'completed') return false; // Failed cells require explicit reset/retry.
  return finished ? block.samples > job.samples : block.samples > job.samples * 1.1;
}

// Local contour segments only where all four adjacent measured bins exist.
export function contours(points: Point[], interval = 2): number[][][] {
  const bins = new Map<string, { x: number; y: number; z: number; n: number }>();
  for (const [x,y,z] of points) {
    const i=Math.floor(x/2), j=Math.floor(y/2), key=`${i}:${j}`;
    const bin = bins.get(key) || {x:i*2+1,y:j*2+1,z:0,n:0};
    bin.z += z; bin.n++; bins.set(key,bin);
  }
  const result: number[][][] = [];
  for (const [key,a] of bins) {
    const [i,j]=key.split(':').map(Number);
    const corners=[a,bins.get(`${i+1}:${j}`),bins.get(`${i+1}:${j+1}`),bins.get(`${i}:${j+1}`)];
    if (corners.some(c=>!c)) continue;
    const c=corners as typeof a[];
    const depths=c.map(p=>p.z/p.n);
    for(let level=Math.ceil(Math.min(...depths)/interval)*interval; level<=Math.max(...depths); level+=interval){
      const hits:number[][]=[];
      for(let e=0;e<4;e++){
        const next=(e+1)%4, u=depths[e],v=depths[next];
        if((u<level && v>=level)||(v<level && u>=level)){
          const f=(level-u)/(v-u); hits.push([c[e].x+f*(c[next].x-c[e].x),c[e].y+f*(c[next].y-c[e].y)]);
        }
      }
      for(let h=0;h+1<hits.length;h+=2) result.push([hits[h],hits[h+1]]);
    }
  }
  return result;
}
