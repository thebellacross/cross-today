import {$,time,get,loadAlbum,artist,element,local} from './client.js';
import {loadRecord,grooveProgress} from './record.js?v=galaxy-3';
import {recordView,reduced} from './record-boot.js';
import {TrackPicker} from './track-picker.js';
import {renderScore} from './score-view.js?v=collapsed-1';
const audio=$('audio'),record=$('record');
const trackPicker=new TrackPicker($('tracks'),$('track-count'),reduced);
let album,score,index=0,starts=[],engaged=false,drag=null,seekPending=null,frame=0,wasPlaying=false,playerVisible=true;
const announce=(message,kind='general')=>{$('status').textContent=message;$('status').dataset.kind=kind;$('status').hidden=false;};
async function play(){const source=audio.src;try{await audio.play();engaged=true;record.classList.add('engaged');if($('status').dataset.kind==='playback')$('status').hidden=true;}catch(error){if(error.name==='AbortError'||source!==audio.src)return;announce('Playback was not started. Tap Play to try again.','playback');}}
function toggle(){audio.paused?play():audio.pause();}
function choose(i,position=0,resume=!audio.paused){
  if(!album)return;index=(i+album.tracks.length)%album.tracks.length;const t=album.tracks[index];seekPending=Math.min(position,t.duration-.001);
  audio.src=t.src;audio.load();$('track-title').textContent=t.title;$('sticky-title').textContent=t.title;
  history.replaceState(null,'','#'+(index+1));trackPicker.select(index,engaged);
  if('mediaSession' in navigator){navigator.mediaSession.metadata=new MediaMetadata({title:t.title,artist:album.artist,album:album.catalog+' '+album.title,artwork:[{src:album.cover_small,sizes:'350x350',type:'image/jpeg'}]});}
  if(resume)play();update();
}
function albumSeek(seconds,resume=!audio.paused){seconds=Math.max(0,Math.min(album.duration-.01,seconds));let k=starts.findLastIndex(s=>s<=seconds);k=Math.max(0,k);if(k!==index)choose(k,seconds-starts[k],resume);else{audio.currentTime=seconds-starts[k];seekPending=null;}engaged=true;record.classList.add('engaged');update();}
function update(){
  if(!album)return;const t=album.tracks[index],position=seekPending??audio.currentTime??0,absolute=starts[index]+position,progress=absolute/album.duration;
  $('time').textContent=`${time(position)} / ${time(t.duration)}`;$('seek').value=String(position/t.duration*1000);
  recordView.update(progress,album.turns);
  record.setAttribute('aria-valuenow',String(Math.round(progress*100)));record.setAttribute('aria-valuetext',`${t.title}, ${time(position)} of ${time(t.duration)}`);
  $('play').classList.toggle('playing',!audio.paused);$('play').setAttribute('aria-label',audio.paused?'Play':'Pause');$('sticky-play').textContent=audio.paused?'▶':'Ⅱ';
  $('sticky').hidden=playerVisible||!engaged;
  document.querySelectorAll('.track-play').forEach((e,k)=>{const playing=k===index&&!audio.paused;e.textContent=playing?'Ⅱ':'▶';e.setAttribute('aria-label',`${playing?'Pause':'Play'} ${album.tracks[k].title}`);});
  if(score&&engaged){$('hearing').hidden=false;const events=score.tracks[index]?.events.filter(e=>position>=e.start&&position<(e.active_until??e.start+e.duration)&&e.gain>=.0158).sort((a,b)=>b.gain-a.gain)||[];const labels=[...new Set(events.map(e=>`${e.name} · ${e.technique}`))].slice(0,5);const text=labels.join(' / ')||'between sounds';if($('heard').textContent!==text){$('heard').textContent=text;$('heard').title=text;}}
  if('mediaSession'in navigator&&audio.duration&&Number.isFinite(audio.duration)){try{navigator.mediaSession.setPositionState({duration:audio.duration,position:Math.min(audio.currentTime,audio.duration),playbackRate:1});}catch{}}
}
function loop(){update();if(!audio.paused||drag)frame=requestAnimationFrame(loop);}
audio.addEventListener('loadedmetadata',()=>{if(seekPending!==null){audio.currentTime=seekPending;seekPending=null;}update();});
audio.addEventListener('play',()=>{engaged=true;record.classList.add('engaged');cancelAnimationFrame(frame);loop();});
for(const event of ['pause','timeupdate','seeked'])audio.addEventListener(event,update);
audio.addEventListener('ended',()=>{if(index+1<album.tracks.length)choose(index+1,0,true);else update();});
audio.addEventListener('error',()=>announce('This audio could not be loaded. The edition may have expired; refresh to hear the current album.'));
$('play').onclick=toggle;$('sticky-play').onclick=toggle;$('previous').onclick=()=>choose(index-1);$('next').onclick=()=>choose(index+1);
$('seek').addEventListener('input',e=>{if(album){audio.currentTime=Number(e.target.value)/1000*album.tracks[index].duration;update();}});
function point(e){return recordView.point(e);}
record.addEventListener('pointerdown',e=>{
  if(!album||e.target.closest('button'))return;const p=point(e);if(p.r>.49)return;
  if(p.r<.085){toggle();return;}if(e.pointerType==='touch'&&!engaged)return;
  e.preventDefault();record.setPointerCapture(e.pointerId);wasPlaying=!audio.paused;audio.pause();
  drag={angle:p.a,start:starts[index]+audio.currentTime,x:e.clientX,y:e.clientY,moved:false,r:p.r};record.style.cursor='grabbing';
});
record.addEventListener('pointermove',e=>{if(!drag)return;const p=point(e);let delta=p.a-drag.angle;if(delta>Math.PI)delta-=2*Math.PI;if(delta< -Math.PI)delta+=2*Math.PI;drag.angle=p.a;drag.moved ||=Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>4;drag.start-=delta/(2*Math.PI*album.turns)*album.duration;drag.start=Math.max(0,Math.min(album.duration,drag.start));albumSeek(drag.start,false);});
function endDrag(e){if(!drag)return;if(!drag.moved){const progress=(starts[index]+(seekPending??audio.currentTime))/album.duration;albumSeek(grooveProgress(point(e),progress,album.turns,reduced.matches)*album.duration,false);}drag=null;record.style.cursor='grab';if(wasPlaying)play();}
record.addEventListener('pointerup',endDrag);record.addEventListener('pointercancel',()=>{if(!drag)return;drag=null;record.style.cursor='grab';if(wasPlaying)play();});
record.addEventListener('keydown',e=>{if(!album||e.target!==record)return;if(e.key===' '){e.preventDefault();toggle();}else if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const current=starts[index]+audio.currentTime;albumSeek(e.key==='Home'?0:e.key==='End'?album.duration:current+(e.key==='ArrowRight'?5:-5));}});
$('enlarge').onclick=e=>{e.stopPropagation();$('zoom-slot').append(record);$('zoom').showModal();$('enlarge').hidden=true;};
function unzoom(){if($('zoom').open)$('zoom').close();$('record-wrap').append(record);$('enlarge').hidden=false;}
$('close-zoom').onclick=unzoom;$('zoom').addEventListener('close',unzoom);$('zoom').addEventListener('click',e=>{if(e.target===$('zoom'))unzoom();});
$('share').onclick=()=>{const u=new URL(location.href);if(album&&!local)u.searchParams.set('album',album.id);$('share-url').value=u.href;u.searchParams.set('embed','1');$('embed-code').value=`<iframe src="${u.href}" title="CROSS record" width="100%" height="700" allow="autoplay" loading="lazy"></iframe>`;$('share-dialog').showModal();};
document.querySelector('.close-dialog').onclick=()=>$('share-dialog').close();
for(const [button,input]of [['copy-link','share-url'],['copy-embed','embed-code']])$(button).onclick=async()=>{try{await navigator.clipboard.writeText($(input).value);$('copy-status').textContent='Copied';}catch{$(input).select();$('copy-status').textContent='Select and copy the text above.';}};
new IntersectionObserver(([entry])=>{playerVisible=entry.isIntersecting;update();},{threshold:0}).observe($('main-player'));
if('mediaSession'in navigator){navigator.mediaSession.setActionHandler('play',play);navigator.mediaSession.setActionHandler('pause',()=>audio.pause());navigator.mediaSession.setActionHandler('previoustrack',()=>choose(index-1));navigator.mediaSession.setActionHandler('nexttrack',()=>choose(index+1));navigator.mediaSession.setActionHandler('seekto',e=>{audio.currentTime=e.seekTime;});}
async function initArtist(){
  const a=await artist();for(const work of [...a.albums].sort((x,y)=>y.released.localeCompare(x.released))){const link=element('a',{href:work.url,class:'disco-item',rel:'noopener'});link.append(element('img',{src:work.cover,alt:work.title,loading:'lazy',fetchpriority:'low'}),element('span',{},work.title),element('small',{},new Date(work.released+'T00:00:00').toLocaleDateString('en',{month:'short',year:'numeric'})));$('discography').append(link);}
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
