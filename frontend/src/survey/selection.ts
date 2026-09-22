export const MAX_SELECTED_CELLS = 20;

export function toggleCell(keys: string[], key: string, completed: boolean): string[] {
  if (keys.includes(key)) return keys.filter(k => k !== key);
  if (!completed || keys.length >= MAX_SELECTED_CELLS) return keys;
  return [...keys, key];
}

export function tilePlacement(coordinates: any, reference?: {crs:string; origin:number[]; datum:string}) {
  const {projected_crs:crs, projected_origin:origin, vertical_datum:datum} = coordinates || {};
  if (typeof crs !== 'string' || !Array.isArray(origin) || origin.length !== 2 || !origin.every(Number.isFinite) || !datum)
    throw new Error('This tile has no reliable survey placement metadata.');
  if (reference && (crs !== reference.crs || datum !== reference.datum))
    throw new Error('Selected tiles use incompatible coordinate or depth references.');
  const anchor = reference || {crs,origin,datum};
  return {anchor, position:[origin[0]-anchor.origin[0],0,-(origin[1]-anchor.origin[1])] as [number,number,number]};
}
