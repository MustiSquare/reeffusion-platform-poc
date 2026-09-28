import {expect,it} from 'vitest';
import {archiveAreas,thumbnailMembers} from './archiveAreas';
const a={id:'5N:20:220',zone:5,hemisphere:'N',column:20,row:220,crs:'EPSG:32605',block_column:2,block_row:22};
const b={...a,id:'5N:21:220',column:21};
it('references one crossing survey in both areas and keeps different recordings',()=>{
  const first={id:'one',area_memberships:[a,b]},second={id:'two',area_memberships:[a]};
  const groups=archiveAreas([first,second]);expect(groups).toHaveLength(2);
  expect(groups[0].surveys).toEqual([first,second]);expect(groups[1].surveys[0]).toBe(first);
});
it('keeps unlocated records accessible and highlights only the displayed 100 km block',()=>{
  expect(archiveAreas([{id:'unknown'}])[0].id).toBe('unlocated');
  expect(thumbnailMembers(a,[a,b,{...a,column:30,block_column:3}])).toEqual([a,b]);
});
