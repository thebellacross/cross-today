import {renderScore} from './score-view.js';
const status=document.getElementById('score-status'),retry=document.getElementById('score-retry');
async function load(){
  status.textContent='Loading the published score…';retry.hidden=true;document.getElementById('error').textContent='';
  try{
    const {$,get,loadAlbum}=await import('./client.js?score='+Date.now());
    const album=await loadAlbum(),score=await get(album.score);
    renderScore(document.querySelector('.document-panel'),album,score);
    $('title').textContent=album.catalog+' '+album.title;
    status.textContent=`${score.tracks.length} tracks loaded. Open a track to inspect its events.`;
  }catch(error){status.textContent='Score could not be loaded.';document.getElementById('error').textContent=error.message;retry.hidden=false;}
}
retry.onclick=load;load();
