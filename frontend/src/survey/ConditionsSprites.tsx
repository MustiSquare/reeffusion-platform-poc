export type MapConditions = {
  windFrom?:number|null; windSpeed?:number|null; windUnit?:string;
  waveHeight?:number|null;
};
const valid=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value)&&value>=0;

// Visual amplitude and crest sharpness increase continuously with significant wave height.
export function seaPath(height:number) {
  const amplitude=height<=.05?0:Math.min(19,Math.sqrt(height)*8);
  const sharpness=Math.min(1,height/4);
  const points=Array.from({length:57},(_,i)=>{
    const phase=i/56*Math.PI*6;
    const smooth=Math.sin(phase),pointed=2/Math.PI*Math.asin(smooth);
    const y=35-amplitude*(smooth*(1-sharpness)+pointed*sharpness);
    return `${i?'L':'M'}${i+4},${y.toFixed(2)}`;
  });
  return points.join(' ');
}

export default function ConditionsSprites({windFrom,windSpeed,windUnit='km/h',waveHeight}:MapConditions) {
  const seaKnown=valid(waveHeight),windKnown=valid(windFrom);
  const calm=valid(windSpeed)&&windSpeed===0;
  const from=windKnown?((windFrom%360)+360)%360:null;
  const compass=from===null?'':['N','NE','E','SE','S','SW','W','NW'][Math.round(from/45)%8];
  const windLabel=calm?'Calm wind':from===null?'Wind unavailable':`Wind from ${compass} ${Math.round(from)} degrees`;
  const waveLabel=seaKnown?`Significant wave height ${waveHeight.toFixed(2)} metres`:'Sea state unavailable';
  return <div className="survey-condition-sprites" aria-label="Conditions at survey playback time">
    <div className="survey-condition-sprite" title={`${waveLabel}. Historical hourly model estimate; graphic is illustrative.`}>
      <svg viewBox="0 0 64 64" role="img" aria-label={waveLabel}>
        <circle cx="32" cy="32" r="29" fill="#10334b" stroke="#9cdbef" strokeOpacity=".5"/>
        {seaKnown?<><path d={`${seaPath(waveHeight)} L60,52 L4,52 Z`} fill="#38bdf8" opacity=".16"/>
          <path d={seaPath(waveHeight)} fill="none" stroke="#7dd3fc" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round"/>
        </>:<text x="32" y="40" textAnchor="middle" fill="#cbd5e1" fontSize="24">?</text>}
      </svg>
      <strong>{seaKnown?`${waveHeight.toFixed(2)} m`:'Unavailable'}</strong>
      <span>{seaKnown&&waveHeight<=.05?'Calm sea':'Sea state'}</span>
    </div>
    <div className="survey-condition-sprite" title={`${windLabel}. Sock trails downwind; north is up. Historical hourly model estimate.`}>
      <svg viewBox="0 0 64 64" role="img" aria-label={windLabel}>
        <circle cx="32" cy="32" r="29" fill="#10334b" stroke="#9cdbef" strokeOpacity=".5"/>
        <text x="32" y="12" textAnchor="middle" fill="#e0f2fe" fontSize="8">N</text>
        {calm?<path d="M29 27h8l-2 23-5-4Z" fill="#fb923c" stroke="#fff"/>:from!==null?
          <g transform={`rotate(${(from+90)%360} 32 32)`} data-testid="windsock-bearing">
            <path d="M31 24 57 29v6L31 40Z" fill="#f97316" stroke="#fff" strokeWidth="1.2"/>
            <path d="m38 26 6 1v10l-6 1Z M49 28l5 1v6l-5 1Z" fill="#fff7ed"/>
            <ellipse cx="31" cy="32" rx="2.5" ry="8" fill="#9a3412" stroke="#fff"/>
          </g>:<text x="32" y="40" textAnchor="middle" fill="#cbd5e1" fontSize="24">?</text>}
        {(calm||from!==null)&&<circle cx="31" cy="32" r="2" fill="#e2e8f0"/>}
      </svg>
      <strong>{calm?'Calm':from===null?'Unavailable':`From ${compass}`}</strong>
      <span>{valid(windSpeed)?`${windSpeed.toFixed(1)} ${windUnit}`:'Wind speed unavailable'}</span>
    </div>
  </div>;
}
