export const $=id=>document.getElementById(id);
export const time=s=>`${Math.floor((s||0)/60)}:${String(Math.floor((s||0)%60)).padStart(2,'0')}`;
export async function get(url){const r=await fetch(url,{cache:'no-cache'});if(!r.ok){const error=new Error(r.status===404?'No published edition is available yet.':'Unable to load this edition. Please try again.');error.status=r.status;throw error;}return r.json();}
export const settings=await get('public-config.json');
export const local=!settings.api && ['localhost','127.0.0.1'].includes(location.hostname);
export function endpoint(path){if(!settings.api)throw new Error('The cloud service is not connected yet.');return settings.api.replace(/\/$/,'')+path;}
export async function loadAlbum(){
  let a;
  if(local){const target=settings.local_album;a=await get(target);const base=new URL(target,location.href);const resolve=p=>new URL(p,base).href;a={...a,tracks:a.tracks.map(t=>({...t,src:resolve(t.src),wav:resolve(t.wav)})),cover:resolve(a.cover),cover_small:resolve(a.cover_small),banner:resolve(a.banner),score:resolve(a.score),downloads:Object.fromEntries(Object.entries(a.downloads).map(([k,v])=>[k,resolve(v)]))};}
  else{const album=new URLSearchParams(location.search).get('album');try{a=await get(endpoint(album?'/public/album/'+encodeURIComponent(album):'/public/current'));}catch(e){if(album&&e.status===404)e.message='This daily edition is no longer available. Open music to hear the current album.';throw e;}}
  return a;
}
export function element(tag,attributes={},text=''){const e=document.createElement(tag);for(const[k,v]of Object.entries(attributes))e.setAttribute(k,v);if(text)e.textContent=text;return e;}
export async function artist(){const a=await get('artist.json');document.querySelectorAll('.artist-name').forEach(e=>e.textContent=a.name);document.querySelectorAll('.artist-avatar').forEach(e=>e.src=a.avatar);document.querySelectorAll('.bandcamp-link').forEach(e=>{e.href=a.bandcamp;e.rel='noopener';});return a;}
