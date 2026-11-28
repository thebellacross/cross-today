// Shared by the standalone score and the listening page. Only public release
// metadata is rendered here; no management or preference-history requests.
function element(tag,attributes={},text='') {
  const node=document.createElement(tag);
  for(const [key,value]of Object.entries(attributes))node.setAttribute(key,value);
  node.textContent=text;return node;
}
const time=value=>`${Math.floor((value||0)/60)}:${String(Math.floor((value||0)%60)).padStart(2,'0')}`;
const seconds=value=>Number.isFinite(value)?value.toFixed(2):'?';

export function renderScore(root,album,score) {
  if(!Array.isArray(score.tracks)||!score.tracks.length)throw Error('The score contains no tracks.');
  const tracks=root.querySelector('[data-score="tracks"]');
  const provenance=root.querySelector('[data-score="provenance"]');
  tracks.replaceChildren();provenance.replaceChildren();
  root.querySelector('[data-score="edition"]').textContent=`${album.day} · seed ${album.seed} · engine ${(album.engine_hash||'').slice(0,12)}`;
  provenance.append(element('a',{href:new URL('provenance.json',album.score).href},'Download reproduction record'));
  const dark=root.classList.contains('inline-score');
  for(const [index,track]of score.tracks.entries()) {
    const details=element('details');details.open=index===0;
    details.append(element('summary',{},`${track.n}. ${track.title} · ${track.form} · ${time(track.duration)}`));
    if(!track.plan)details.append(element('p',{},'Legacy event summary: this engine did not capture every loop offset or apply every named transition. This is not a complete replay plan.'));
    const lanes=track.lanes||5;
    const canvas=element('canvas',{class:'score-chart',width:'900',height:String(Math.max(100,lanes*18)),role:'img','aria-label':`Event timeline for ${track.title}, including effect tails. Event times and source names follow below.`});
    details.append(canvas);const ctx=canvas.getContext('2d');
    for(const event of track.events) {
      const lane=event.lane||0,y=lane/lanes*(canvas.height-10)+5,height=Math.max(5,(canvas.height-20)/lanes-4);
      let color=album.palette[lane%album.palette.length];
      if(dark&&/^#[\da-f]{6}$/i.test(color)) {
        const channels=color.match(/[\da-f]{2}/gi).map(c=>Math.round(parseInt(c,16)*.7+255*.3));
        color=`rgb(${channels.join(',')})`;
      }
      ctx.fillStyle=color;ctx.globalAlpha=.8;
      ctx.fillRect(event.start/track.duration*900,y,Math.max(2,event.duration/track.duration*900),height);
      if(event.tail_seconds){ctx.globalAlpha=.25;ctx.fillRect((event.start+event.duration)/track.duration*900,y,event.tail_seconds/track.duration*900,height);}
      details.append(element('div',{class:'score-event'},`${time(event.start)} +${seconds(event.duration)}s${event.tail_seconds?' + tail '+seconds(event.tail_seconds)+'s':''} · ${event.name} [${seconds(event.segment_start)}–${seconds(event.segment_end)}s] · ${event.technique}${event.role?' · '+event.role:''}`));
    }
    if(track.plan) {
      if(track.plan.development) {
        details.append(element('p',{},`Development: ${track.plan.development.arc}. Voices persist across scenes; source read positions do not restart at section boundaries. Level, frequency and spatial trajectories are saved in the plan.`));
        for(const section of track.plan.sections)details.append(element('p',{},`${time(section.start)}–${time(section.end)} · ${section.purpose} · planned foreground: ${track.plan.events.find(e=>e.event_id===section.foreground)?.source.name||'none'}`));
      }
      const download=element('button',{type:'button'},'Download composition plan');
      download.onclick=()=>{
        const url=URL.createObjectURL(new Blob([JSON.stringify(track.plan,null,2)],{type:'application/json'}));
        element('a',{href:url,download:`${album.id}-track-${track.n}-plan.json`}).click();
        setTimeout(()=>URL.revokeObjectURL(url),1000);
      };
      details.append(download);
    }
    tracks.append(details);
  }
}
