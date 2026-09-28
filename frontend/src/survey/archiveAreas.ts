import {converter} from './model';
export type Area={id:string;zone:number;hemisphere:string;column:number;row:number;crs:string;block_column:number;block_row:number};
export function archiveAreas(surveys:any[]){
  const areas=new Map<string,{id:string;area:Area|null;surveys:any[]}>();
  for(const survey of surveys){
    const members: (Area|null)[]=survey.area_memberships?.length?survey.area_memberships:[null];
    for(const area of members){
      const id=area?.id||'unlocated';
      if(!areas.has(id))areas.set(id,{id,area,surveys:[]});
      const group=areas.get(id)!;if(!group.surveys.some(s=>s.id===survey.id))group.surveys.push(survey);
    }
  }
  return [...areas.values()].sort((a,b)=>a.id==='unlocated'?1:b.id==='unlocated'?-1:a.id.localeCompare(b.id));
}
export function areaLabel(area:Area|null){return area?`UTM ${area.zone}${area.hemisphere} · E ${area.column*10}–${(area.column+1)*10} km · N ${area.row*10}–${(area.row+1)*10} km`:'Location unavailable';}
export function thumbnailMembers(area:Area,members:Area[]){return members.filter(m=>m.crs===area.crs&&m.block_column===area.block_column&&m.block_row===area.block_row);}

export function areaLocation(area:Area|null){
  if(!area)return null;
  const [longitude,latitude]=converter(area.crs).forward([area.column*10000+5000,area.row*10000+5000]);
  return {longitude,latitude};
}
