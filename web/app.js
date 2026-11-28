import {$,time,get,loadAlbum,artist,element,local} from './client.js';
import {loadRecord,grooveProgress} from './record.js?v=scratch-1';
import {recordView,reduced} from './record-boot.js?v=scratch-1';
import {TrackPicker} from './track-picker.js';
import {renderScore} from './score-view.js?v=story-1';
import {ScratchAudio,SCRATCH_SECONDS_PER_TURN} from './scratch-audio.js';
const audio=$('audio'),record=$('record');
const scratch=new ScratchAudio(audio);
const trackPicker=new TrackPicker($('tracks'),$('track-count'),reduced);
let album,score,index=0,starts=[],engaged=false,drag=null,seekPending=null,frame=0,playerVisible=true,recordHovered=false,lastWarm=0;
const isPlaying=()=>drag?drag.wasPlaying:!audio.paused;
function warmScratch(){if(album)scratch.prepare(album.tracks[index],seekPending??audio.currentTime).catch(()=>{});}
const announce=(message,kind='general')=>{$('status').textContent=message;$('status').dataset.kind=kind;$('status').hidden=false;};
async function play(){warmScratch();const source=audio.src;try{await audio.play();engaged=true;record.classList.add('engaged');if($('status').dataset.kind==='playback')$('status').hidden=true;}catch(error){if(error.name==='AbortError'||source!==audio.src)return;announce('Playback was not started. Tap Play to try again.','playback');}}
function pause(){finishDrag(false);audio.pause();update();}
function toggle(){isPlaying()?pause():play();}
function choose(i,position=0,resume=isPlaying()){
  finishDrag(false);
  if(!album)return;index=(i+album.tracks.length)%album.tracks.length;const t=album.tracks[index];seekPending=Math.min(position,t.duration-.001);
  audio.src=t.src;audio.load();$('track-title').textContent=t.title;$('sticky-title').textContent=t.title;
  history.replaceState(null,'','#'+(index+1));trackPicker.select(index,engaged);
  if('mediaSession' in navigator){navigator.mediaSession.metadata=new MediaMetadata({title:t.title,artist:album.artist,album:album.catalog+' '+album.title,artwork:[{src:album.cover_small,sizes:'350x350',type:'image/jpeg'}]});}
  if(resume)play();update();
}
function albumSeek(seconds,resume=isPlaying()){finishDrag(false);seconds=Math.max(0,Math.min(album.duration-.01,seconds));let k=starts.findLastIndex(s=>s<=seconds);k=Math.max(0,k);if(k!==index)choose(k,seconds-starts[k],resume);else{audio.currentTime=seconds-starts[k];seekPending=null;if(resume&&audio.paused)play();}engaged=true;record.classList.add('engaged');update();}
function update(){
  if(!album)return;const t=album.tracks[index],position=drag?.active?drag.position:(seekPending??audio.currentTime??0),absolute=starts[index]+position,progress=absolute/album.duration;
  $('time').textContent=`${time(position)} / ${time(t.duration)}`;$('seek').value=String(position/t.duration*1000);
  recordView.update(progress,album.turns);
  record.setAttribute('aria-valuenow',String(Math.round(progress*100)));record.setAttribute('aria-valuetext',`${t.title}, ${time(position)} of ${time(t.duration)}`);
  $('play').classList.toggle('playing',isPlaying());$('play').setAttribute('aria-label',isPlaying()?'Pause':'Play');$('sticky-play').textContent=isPlaying()?'Ⅱ':'▶';
  $('sticky').hidden=playerVisible||!engaged;
  document.querySelectorAll('.track-play').forEach((e,k)=>{const playing=k===index&&isPlaying();e.textContent=playing?'Ⅱ':'▶';e.setAttribute('aria-label',`${playing?'Pause':'Play'} ${album.tracks[k].title}`);});
  if(score&&engaged){$('hearing').hidden=false;const events=score.tracks[index]?.events.filter(e=>position>=e.start&&position<(e.active_until??e.start+e.duration)&&e.gain>=.0158).sort((a,b)=>b.gain-a.gain)||[];const labels=[...new Set(events.map(e=>`${e.name} · ${e.technique}`))].slice(0,5);const text=labels.join(' / ')||'between sounds';if($('heard').textContent!==text){$('heard').textContent=text;$('heard').title=text;}}
  if('mediaSession'in navigator&&audio.duration&&Number.isFinite(audio.duration)){try{navigator.mediaSession.playbackState=isPlaying()?'playing':'paused';navigator.mediaSession.setPositionState({duration:audio.duration,position:Math.min(position,audio.duration),playbackRate:1});}catch{}}
}
function loop(){update();if(recordHovered&&!drag&&!audio.paused&&performance.now()-lastWarm>900){lastWarm=performance.now();warmScratch();}if(!audio.paused||drag)frame=requestAnimationFrame(loop);}
audio.addEventListener('loadedmetadata',()=>{if(seekPending!==null){audio.currentTime=seekPending;seekPending=null;}update();});
audio.addEventListener('play',()=>{engaged=true;record.classList.add('engaged');cancelAnimationFrame(frame);loop();});
for(const event of ['pause','timeupdate','seeked'])audio.addEventListener(event,update);
audio.addEventListener('seeked',()=>{if(engaged&&!audio.paused&&!drag)warmScratch();});
audio.addEventListener('ended',()=>{if(index+1<album.tracks.length)choose(index+1,0,true);else update();});
audio.addEventListener('error',()=>announce('This audio could not be loaded. The edition may have expired; refresh to hear the current album.'));
$('play').onclick=toggle;$('sticky-play').onclick=toggle;$('previous').onclick=()=>choose(index-1);$('next').onclick=()=>choose(index+1);
$('seek').addEventListener('input',e=>{if(album){const resume=isPlaying();finishDrag(false);seekPending=null;audio.currentTime=Number(e.target.value)/1000*album.tracks[index].duration;if(resume&&audio.paused)play();update();}});
function point(e){return recordView.point(e);}
record.addEventListener('pointerenter',()=>{recordHovered=true;if(engaged)warmScratch();});
record.addEventListener('pointerleave',()=>{recordHovered=false;});
record.addEventListener('pointerdown',e=>{
  if(!album||drag||!e.isPrimary||e.button!==0||e.target.closest('button'))return;const p=point(e);if(p.r>.49)return;
  if(e.pointerType==='touch'&&!engaged&&p.r>=.085)return;
  e.preventDefault();record.setPointerCapture(e.pointerId);
  const gesture=drag={pointer:e.pointerId,angle:p.a,rotation:recordView.rotation,origin:seekPending??audio.currentTime,position:seekPending??audio.currentTime,x:e.clientX,y:e.clientY,moved:false,center:p.r<.085,wasPlaying:!audio.paused,active:false,stamp:e.timeStamp};
  record.style.cursor='grabbing';record.dataset.scratching='preparing';
  scratch.prepare(album.tracks[index],gesture.position).then(ready=>{
    if(!ready||drag!==gesture)return;
    gesture.active=true;scratch.start(gesture.origin);audio.pause();
    scratch.move(gesture.position,.016);record.dataset.scratching='active';
    cancelAnimationFrame(frame);loop();
  }).catch(error=>{if(drag!==gesture||error.name==='AbortError')return;record.dataset.scratching='unavailable';announce('Scratching audio could not be prepared. Playback is still available; try dragging again.','scratch');});
});
record.addEventListener('pointermove',e=>{
  if(!drag||e.pointerId!==drag.pointer)return;const p=point(e);let delta=p.a-drag.angle;
  if(delta>Math.PI)delta-=2*Math.PI;if(delta< -Math.PI)delta+=2*Math.PI;
  const seconds=Math.min(.08,Math.max(.006,(e.timeStamp-drag.stamp)/1000));drag.angle=p.a;drag.stamp=e.timeStamp;
  drag.moved ||=Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>4;
  if(!drag.moved||p.r<.04)return;
  drag.rotation+=delta;recordView.handRotation=drag.rotation;
  drag.position=Math.max(0,Math.min(album.tracks[index].duration-.001,drag.position-delta/(2*Math.PI)*SCRATCH_SECONDS_PER_TURN));
  scratch.move(drag.position,seconds);scratch.prepare(album.tracks[index],drag.position).catch(()=>{});update();
});
function finishDrag(resume) {
  if(!drag)return;const gesture=drag;drag=null;scratch.cancel();
  recordView.finishDrag((starts[index]+gesture.position)/album.duration,album.turns);
  if(gesture.active||gesture.moved){audio.currentTime=gesture.position;seekPending=null;}
  if(record.hasPointerCapture(gesture.pointer))record.releasePointerCapture(gesture.pointer);
  record.style.cursor='grab';delete record.dataset.scratching;
  if($('status').dataset.kind==='scratch')$('status').hidden=true;
  if(resume&&gesture.wasPlaying)play();update();
}
function endDrag(e){
  if(!drag||e.pointerId!==drag.pointer)return;
  const gesture=drag,progress=(starts[index]+gesture.origin)/album.duration;
  finishDrag(gesture.moved);
  if(!gesture.moved){
    if(gesture.center){gesture.wasPlaying?pause():play();}
    else{albumSeek(grooveProgress(point(e),progress,album.turns,reduced.matches,recordView.rotationOffset)*album.duration,gesture.wasPlaying);}
  }
}
record.addEventListener('pointerup',endDrag);
record.addEventListener('pointercancel',()=>finishDrag(true));
record.addEventListener('lostpointercapture',()=>finishDrag(true));
window.addEventListener('blur',()=>finishDrag(true));
document.addEventListener('visibilitychange',()=>{if(document.hidden)finishDrag(true);});
record.addEventListener('keydown',e=>{if(!album||e.target!==record)return;if(e.key===' '){e.preventDefault();toggle();}else if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const current=starts[index]+audio.currentTime;albumSeek(e.key==='Home'?0:e.key==='End'?album.duration:current+(e.key==='ArrowRight'?5:-5));}});
$('enlarge').onclick=e=>{e.stopPropagation();$('zoom-slot').append(record);$('zoom').showModal();$('enlarge').hidden=true;};
function unzoom(){if($('zoom').open)$('zoom').close();$('record-wrap').append(record);$('enlarge').hidden=false;}
$('close-zoom').onclick=unzoom;$('zoom').addEventListener('close',unzoom);$('zoom').addEventListener('click',e=>{if(e.target===$('zoom'))unzoom();});
$('share').onclick=()=>{const u=new URL(location.href);if(album&&!local)u.searchParams.set('album',album.id);$('share-url').value=u.href;u.searchParams.set('embed','1');$('embed-code').value=`<iframe src="${u.href}" title="CROSS record" width="100%" height="700" allow="autoplay" loading="lazy"></iframe>`;$('share-dialog').showModal();};
document.querySelector('.close-dialog').onclick=()=>$('share-dialog').close();
for(const [button,input]of [['copy-link','share-url'],['copy-embed','embed-code']])$(button).onclick=async()=>{try{await navigator.clipboard.writeText($(input).value);$('copy-status').textContent='Copied';}catch{$(input).select();$('copy-status').textContent='Select and copy the text above.';}};
new IntersectionObserver(([entry])=>{playerVisible=entry.isIntersecting;update();},{threshold:0}).observe($('main-player'));
if('mediaSession'in navigator){navigator.mediaSession.setActionHandler('play',play);navigator.mediaSession.setActionHandler('pause',pause);navigator.mediaSession.setActionHandler('previoustrack',()=>choose(index-1));navigator.mediaSession.setActionHandler('nexttrack',()=>choose(index+1));navigator.mediaSession.setActionHandler('seekto',e=>{const resume=isPlaying();finishDrag(false);seekPending=null;audio.currentTime=e.seekTime;if(resume)play();});}
async function initArtist(){
  const a=await artist();for(const work of [...a.albums].sort((x,y)=>(y.released||'').localeCompare(x.released||'')).slice(0,4)){const link=element('a',{href:work.url,class:'disco-item',rel:'noopener'});link.append(element('img',{src:work.cover,alt:work.title,loading:'lazy',fetchpriority:'low'}),element('span',{},work.title),element('small',{},work.released?new Date(work.released+'T00:00:00').toLocaleDateString('en',{month:'short',year:'numeric'}):''));$('discography').append(link);}
  if(a.bio){$('bio').hidden=false;$('bio').textContent=a.bio;}
}
async function init(){
  album=await loadAlbum();document.title=`${album.catalog} ${album.title} | ${album.artist||'CROSS'}`;$('album-title').textContent=album.catalog+' '+album.title;
  $('sticky-cover').src=album.cover_small;
  loadRecord($('grooves'),album).catch(()=>announce('The record image could not be loaded. Audio playback is still available; refresh to try the image again.'));
  $('seed').textContent=`seed ${album.seed}`;$('credits').textContent=album.credits;$('release-date').textContent=`released ${album.day}`;
  $('rules').textContent=`Daily publication around ${String(album.rules.publish_hour).padStart(2,'0')}:00 (${album.rules.timezone}). The latest ${album.rules.keep_releases} editions stay available. Catalogue cards and Selected recordings remain. ${album.final?'Chance has ended this series. This final edition stays.':album.rules.random_end?`This edition had a 1 in ${album.last_odds} chance of ending the series.`:'The series continues daily.'}`;
  let offset=0;album.tracks.forEach((track,k)=>{starts.push(offset);offset+=track.duration;const row=element('li');const b=element('button',{class:'track-play','aria-label':`Play ${track.title}`},'▶');b.onclick=()=>k===index?toggle():choose(k,0,true);const label=element('button',{class:'track-name'},track.title);label.onclick=()=>choose(k,0,true);const line=element('div');line.append(label,element('span',{class:'track-duration'},time(track.duration)));row.append(b,element('span',{class:'track-number'},`${k+1}.`),line);$('tracks').append(row);});
  $('play').disabled=false;const trackNumber=Number(location.hash.slice(1));choose(Number.isInteger(trackNumber)&&trackNumber>=1&&trackNumber<=album.tracks.length?trackNumber-1:0,0,false);
  if(new URLSearchParams(location.search).has('embed')){document.querySelector('.site-header').hidden=true;document.querySelector('footer').hidden=true;}
  await loadScore();
}
async function loadScore(){
  if(!album)return;
  $('score-status').textContent='Loading the published score…';$('score-retry').hidden=true;$('score-error').textContent='';
  try{
    const loaded=await get(album.score);renderScore($('score-section'),album,loaded);score=loaded;
    $('score-status').textContent=`${score.tracks.length} tracks loaded. Open a track to inspect its events.`;
    if(!engaged)$('heard').textContent='Press play to listen.';update();
  }catch(e){
    $('heard').textContent='Live source details are unavailable. You can still listen to the album.';
    $('score-status').textContent='Score could not be loaded.';$('score-error').textContent=e.message;$('score-retry').hidden=false;
  }
}
$('score-retry').onclick=loadScore;
initArtist().catch(()=>{const link=element('a',{href:'https://bellacrossmusic.bandcamp.com/'},'Browse the discography on Bandcamp');$('discography').append(link);});
init().catch(e=>{announce(e.message);$('track-title').textContent='No playable edition';});
