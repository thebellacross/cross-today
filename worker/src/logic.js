export function localClock(date, timezone) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone: timezone, year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'}).formatToParts(date).map(x=>[x.type,x.value]));
  return {day:`${p.year}-${p.month}-${p.day}`,hour:Number(p.hour)};
}
export function nextDay(day) { const d = new Date(day+'T12:00:00Z'); d.setUTCDate(d.getUTCDate()+1); return d.toISOString().slice(0,10); }
export function validDay(day) { return /^\d{4}-\d{2}-\d{2}$/.test(day) && !isNaN(Date.parse(day+'T00:00:00Z')) && new Date(day+'T00:00:00Z').toISOString().startsWith(day); }
export function plan(now, config, current, ended) {
  if (ended) return [];
  const t=localClock(now,config.timezone), result=[];
  if (t.hour>=config.schedule.publish_hour && (!current || current.day<t.day)) result.push({day:t.day,publish:true});
  if (t.hour>=config.schedule.prepare_hour) result.push({day:nextDay(t.day),publish:false});
  return result;
}
export function retryable(job, now, settings) {
  if (!job) return true;
  if (['published','ready','retired'].includes(job.status)) return false;
  if (job.lease_until && job.lease_until>now) return false;
  return (job.attempts||0)<settings.max_attempts && (!job.retry_after || job.retry_after<=now);
}
export function safeAsset(name) { return /^(\d{2}\.(mp3|wav)|cover\.png|cover-small\.jpg|banner\.jpg|score\.(json|txt)|provenance\.json|credits\.txt|album-(wav|mp3)(-\d{2})?\.zip)$/.test(name); }
export function safeHash(value) { return typeof value==='string' && /^[0-9a-f]{64}$/.test(value); }
export const MIME={mp3:'audio/mpeg',wav:'audio/wav',png:'image/png',jpg:'image/jpeg',json:'application/json',txt:'text/plain; charset=utf-8',zip:'application/zip'};
export function mime(name) { return MIME[name.split('.').pop()]||'application/octet-stream'; }
export function eligibleForCleanup(jobs,current,pins,keep) {
  const done=jobs.filter(j=>j.status==='published').sort((a,b)=>b.day.localeCompare(a.day));
  const retained=new Set(done.slice(0,keep).map(j=>j.id));
  return done.filter(j=>j.id!==current?.id&&!j.final&&!pins.has(j.id)&&!retained.has(j.id));
}
