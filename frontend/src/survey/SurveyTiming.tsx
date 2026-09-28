const DAY=86400000;
const dateLabel=(time:number)=>new Date(time).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
const monthLabel=(time:number)=>new Date(time).toLocaleDateString('en-GB',{month:'long',year:'numeric',timeZone:'UTC'});
const clockLabel=(time:number)=>new Date(time).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'UTC'});
export function surveyTiming(survey:any){
  const start=Date.parse(survey.started_at||'');
  if(!Number.isFinite(start))return null;
  const explicitEnd=Date.parse(survey.ended_at||'');
  const duration=survey.duration_seconds;
  const end=Number.isFinite(explicitEnd)&&explicitEnd>=start?explicitEnd:
    typeof duration==='number'&&Number.isFinite(duration)&&duration>=0?start+duration*1000:null;
  const firstDay=Math.floor(start/DAY)*DAY;
  const lastDay=Math.floor(Math.max(start,(end??start)-1)/DAY)*DAY;
  const spanDays=Math.round((lastDay-firstDay)/DAY)+1;
  // Show at least a fortnight; longer recordings use labelled date ranges.
  const step=Math.max(1,Math.ceil(spanDays/14));
  const windowStart=spanDays<=11?firstDay-3*DAY:firstDay;
  const days=Array.from({length:14},(_,i)=>{
    const from=windowStart+i*step*DAY,to=from+(step-1)*DAY;
    return {from,to,active:from<=lastDay&&to>=firstDay};
  });
  const hours=spanDays*24;
  return {start,end,firstDay,days,hours,left:100*(start-firstDay)/(spanDays*DAY),width:end===null?0:100*(end-start)/(spanDays*DAY)};
}

export default function SurveyTiming({survey}:{survey:any}){
  const data=surveyTiming(survey);
  if(!data)return <div className="archive-timing-unavailable">Survey date and time unavailable</div>;
  const {start,end,days,hours,firstDay,left,width}=data;
  const firstMonth=monthLabel(days[0].from),lastMonth=monthLabel(days[days.length-1].to);
  const calendarMonths=firstMonth===lastMonth?firstMonth:`${firstMonth} – ${lastMonth}`;
  const sameDay=end!==null&&Math.floor(start/DAY)===Math.floor(end/DAY);
  const range=end===null?`${dateLabel(start)} ${clockLabel(start)} UTC; end time unavailable`:
    `${dateLabel(start)} ${clockLabel(start)} – ${sameDay?'':`${dateLabel(end)} `}${clockLabel(end)} UTC`;
  return <div className="archive-timing" aria-label="Survey dates and recorded hours">
    <div className="archive-timing-dates">
      <div className="archive-timing-caption"><strong className="archive-calendar-month">{calendarMonths}</strong><span>Survey dates · UTC</span></div>
      <div className="archive-date-strip" role="img" aria-label={`Survey dates: ${range}`}>
        {days.map(day=><span key={day.from} className={`archive-date${day.active?' is-recorded':''}`} title={`${dateLabel(day.from)}${day.to!==day.from?` – ${dateLabel(day.to)}`:''}${day.active?' · Survey recorded':''}`}>
          <span className="archive-date-square">{day.active?'✓':''}</span>
          <span>{new Date(day.from).getUTCDate()}{day.to!==day.from?`–${new Date(day.to).getUTCDate()}`:''}</span>
        </span>)}
      </div>
    </div>
    <div className="archive-timing-hours">
      <div className="archive-timing-caption"><span>Recorded hours · UTC</span><span>{end===null?'End time unavailable':`${hours} hours`}</span></div>
      <div className="archive-hours-bar" role="img" aria-label={range} title={range}>
        {end!==null&&end>start&&<span className="archive-hours-recorded" style={{left:`${left}%`,width:`${width}%`}}/>}
        {hours===48&&<span className="archive-midnight"/>}
      </div>
      <div className="archive-hours-ticks">{[0,1,2,3,4].map(i=>{
        const h=hours*i/4;
        return <span key={i}>{hours===24?String(h).padStart(2,'0'):i===4?`00 +${hours/24}d`:`${clockLabel(firstDay+h*3600000)}${h>=24?` +${Math.floor(h/24)}d`:''}`}</span>;
      })}</div>
      <div className="archive-time-range">{range}</div>
    </div>
  </div>;
}
