import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {githubFixture} from './github-fixture.mjs';
const free=process.argv.includes('--free'),github=githubFixture();
const fixture=JSON.parse(readFileSync('output/validation/album.json'));
let dispatches=0;
const mf=new Miniflare(convertV4MiniflareOptions({workers:[{name:"test",modules:true,scriptPath:'.state/worker.mjs',compatibilityDate:'2026-11-01',durableObjects:{COORDINATOR:{className:'Coordinator',useSQLite:true}},r2Buckets:['SOURCES','PERMANENT'],bindings:{STORAGE_BACKEND:free?'github-free':'r2',STORAGE_REPOSITORY:'thebellacross/private-fixture',ADMIN_TOKEN:'test-only-admin',SESSION_SECRET:'test-only-long-session-secret-1234567890',RUN_TOKEN:'test-only-run',GITHUB_TOKEN:'test-only-github',GITHUB_REPOSITORY:'thebellacross/cross-today'},outboundService:async request=>{
  if(free){const response=await github.fetch(request);dispatches=github.dispatches;return response;}
  if(request.url.includes('/dispatches')){dispatches++;return new Response(null,{status:204});}
  const name=new URL(request.url).pathname.split('/').at(-1);let data=readFileSync('output/validation/'+name);let status=200;const headers={'Content-Length':String(data.length)};
  if(request.headers.has('Range')){const m=/bytes=(\d+)-(\d*)/.exec(request.headers.get('Range'));const start=Number(m[1]),end=m[2]?Number(m[2]):data.length-1;headers['Content-Range']=`bytes ${start}-${end}/${data.length}`;data=data.subarray(start,end+1);headers['Content-Length']=String(data.length);status=206;}
  return new Response(request.method==='HEAD'?null:data,{status,headers});
}}]}));
const call=async(path,method='GET',body,role='admin',headers={})=>{
  const h={...headers};if(role)h.Authorization='Bearer '+(role==='admin'?'test-only-admin':'test-only-run');
  let data=body;if(body&&!(body instanceof Uint8Array)){data=JSON.stringify(body);h['Content-Type']='application/json';}
  return mf.dispatchFetch('https://example.test'+path,{method,headers:h,body:data});
};
const jcall=async(...args)=>{const r=await call(...args);const j=await r.json();assert.ok(r.ok,JSON.stringify({path:args[0],status:r.status,data:j}));return j;};
try{
  assert.equal((await call('/api/state','GET',undefined,null)).status,401);
  assert.equal((await call('/api/login','POST',{password:'test-only-admin'},null,{Origin:'https://evil.example'})).status,403);
  const login=await call('/api/login','POST',{password:'test-only-admin'},null);assert.equal(login.status,200);const cookie=login.headers.get('Set-Cookie');assert.match(cookie,/HttpOnly/);assert.match(cookie,/Secure/);
  assert.equal((await call('/api/state','GET',undefined,null,{Cookie:cookie})).status,200);
  assert.equal((await call('/api/generate','POST',{},null,{Cookie:cookie})).status,403);
  assert.equal((await call('/api/state','GET',undefined,null,{Cookie:'bc_session=forged'})).status,401);
  const handoff=await jcall('/api/login-link','POST',{});const redeemed=await call('/api/redeem','POST',{code:handoff.code},null);assert.equal(redeemed.status,200);assert.match(redeemed.headers.get('Set-Cookie'),/HttpOnly/);assert.equal((await call('/api/redeem','POST',{code:handoff.code},null)).status,401);assert.equal((await call('/api/login-link','POST',{},null)).status,401);
  const empty=await call('/api/generate','POST',{day:'2026-11-18'});assert.equal(empty.status,400);assert.match((await empty.json()).error,/No valid selected materials/);
  const settings=await Promise.all([call('/api/config','PUT',{revision:0,generation:{form:'loops'}}),call('/api/config','PUT',{revision:0,generation:{form:'fusion'}})]);assert.deepEqual(settings.map(r=>r.status).sort(),[200,409]);
  const data=readFileSync('C_SoundSource/Snaredrum.wav');const sha=createHash('sha256').update(data).digest('hex');
  const u=await jcall('/api/uploads/begin','POST',{hash:sha,name:'Snaredrum.wav',extension:'.wav',bytes:data.length});
  assert.equal((await jcall('/api/uploads/begin','POST',{hash:sha,name:'Snaredrum.wav',extension:'.wav',bytes:data.length})).id,u.id);
  for(let off=0,part=1;off<data.length;off+=u.part_size,part++)await jcall(`/api/uploads/${u.id}/part?n=${part}`,'PUT',data.subarray(off,off+u.part_size));
  await jcall(`/api/uploads/${u.id}/complete`,'POST',{});await jcall(`/api/uploads/${u.id}/complete`,'POST',{});
  assert.ok((await jcall('/api/uploads/begin','POST',{hash:sha,name:'Snaredrum.wav',extension:'.wav',bytes:data.length})).exists);
  const downloaded=await call('/internal/sources/'+sha,'GET',undefined,'run',{Range:'bytes=0-31'});assert.equal(downloaded.status,206);assert.deepEqual(new Uint8Array(await downloaded.arrayBuffer()),new Uint8Array(data.subarray(0,32)));assert.equal(downloaded.headers.get('Cache-Control'),'private, no-store');
  const sourceHead=await call('/internal/sources/'+sha,'HEAD',undefined,'run');assert.equal(Number(sourceHead.headers.get('Content-Length')),data.length);
  assert.equal((await call('/originals/'+sha,'GET',undefined,null)).status,404);
  const first=await jcall('/api/generate','POST',{day:'2026-11-18'});await jcall('/api/generate','POST',{day:'2026-11-18'});assert.equal(dispatches,1);
  let job=await jcall(`/internal/jobs/${first.id}/claim`,'POST',{run:'one'},'run');
  assert.equal((await call(`/internal/jobs/${first.id}/claim`,'POST',{run:'two'},'run')).status,409);
  assert.equal((await call(`/internal/jobs/${first.id}/failed`,'POST',{run:'stale'},'run')).status,409);
  await jcall(`/internal/jobs/${first.id}/failed`,'POST',{run:'one'},'run');
  job=await jcall(`/internal/jobs/${first.id}/claim`,'POST',{run:'two'},'run');assert.equal(job.seed,first.seed);assert.deepEqual(job.sources,first.sources);
  assert.equal((await call('/public/current','GET',undefined,null)).status,404);
  const publish=async(day,existing)=>{
    const queued=existing||await jcall('/api/generate','POST',{day});const job=await jcall(`/internal/jobs/${queued.id}/claim`,'POST',{run:existing?'two':day},'run');const manifest={...fixture,id:job.id,day,seed:job.seed,final:false};
    await jcall(`/internal/permanent/catalog/${job.id}/cover-small.jpg`,'PUT',readFileSync('output/validation/cover-small.jpg'),'run');
    await jcall(`/internal/jobs/${job.id}/ready`,'POST',{run:job.run,album:manifest},'run');
    if(existing){await jcall(`/internal/jobs/${job.id}/failed`,'POST',{run:job.run},'run');const resumed=await jcall('/api/generate','POST',{day});assert.equal(resumed.status,'ready');assert.equal(resumed.seed,job.seed);assert.deepEqual(resumed.album,manifest);}
    await jcall(`/internal/jobs/${job.id}/publish`,'POST',{run:job.run},'run');return manifest;
  };
  await publish('2026-11-18',first);
  const current=await jcall('/public/current','GET',undefined,null);assert.equal(current.id,first.id);
  const media=await call(`/media/${first.id}/01.mp3`,'GET',undefined,null,{Range:'bytes=0-31'});assert.equal(media.status,206);assert.equal(media.headers.get('Content-Type'),'audio/mpeg');assert.equal(media.headers.get('Access-Control-Allow-Origin'),'*');assert.equal((await media.arrayBuffer()).byteLength,32);
  const s=await jcall('/api/select','POST',{album:first.id,track:1,note:'A private curation note'});
  const selectionDispatches=dispatches;
  assert.equal((await jcall('/api/select','POST',{album:first.id,track:1})).id,s.id);
  assert.equal(dispatches,selectionDispatches);
  await jcall(`/api/selections/${s.id}`,'PUT',{revision:0,note:'Updated private curation note'});
  assert.equal((await call(`/api/selections/${s.id}`,'PUT',{revision:0,note:'Stale note'})).status,409);
  await publish('2026-11-19');await publish('2026-11-20');
  const dailyFeedback={request_id:'full-track-fixture',profile_id:'open',album:'album-2026-11-20',track:1};
  const fullTrack=await jcall('/api/studio/from-daily','POST',dailyFeedback);assert.deepEqual(fullTrack.parent_daily,{album:'album-2026-11-20',track:1});assert.equal(fullTrack.source_manifest.assets['01.wav'].sha256,fixture.assets['01.wav'].sha256);assert.equal((await jcall('/api/studio/from-daily','POST',dailyFeedback)).id,fullTrack.id);
  assert.ok(!(await jcall('/internal/cleanup','GET',undefined,'run')).includes(first.id));
  for(const [from,to]of [['01.wav','track.wav'],['01.mp3','track.mp3'],['cover.png','cover.png'],['provenance.json','provenance.json'],['credits.txt','credits.txt']])await jcall(`/internal/permanent/selected/${s.id}/${to}`,'PUT',readFileSync('output/validation/'+from),'run');
  if(free){const asset=[...github.assets.values()].find(a=>a.tag==='kept-'+s.id&&a.name==='track.mp3');const body={key:`selected/${s.id}/track.mp3`,id:asset.id,bytes:asset.data.length,sha256:createHash('sha256').update(asset.data).digest('hex')};assert.equal((await call('/internal/storage/register','POST',{...body,sha256:'0'.repeat(64)},'run')).status,409);await jcall('/internal/storage/register','POST',body,'run');}
  await jcall(`/internal/selections/${s.id}`,'POST',{status:'ready'},'run');
  assert.equal((await jcall('/api/state')).selections[0].note,'Updated private curation note');
  assert.ok((await jcall('/internal/cleanup','GET',undefined,'run')).includes(first.id));
  await jcall('/internal/cleanup','POST',{id:first.id},'run');
  assert.equal((await call(`/media/${first.id}/01.mp3`,'GET',undefined,null)).status,404);
  const kept=await call(`/selected/${s.id}/track.mp3`,'GET',undefined,null,{Range:'bytes=0-31'});assert.equal(kept.status,206);assert.equal((await kept.arrayBuffer()).byteLength,32);
  const selected=await jcall('/public/selected','GET',undefined,null);assert.ok(!JSON.stringify(selected).includes('private curation'));
  const waveDownload=await call(new URL(selected[0].wav).pathname+'?download=1','HEAD',undefined,null);assert.equal(waveDownload.status,200);assert.match(waveDownload.headers.get('Content-Disposition'),/attachment/);
  const a=await call('/api/playlist','PUT',{revision:0,order:[s.id],title:'Test edition',notes:'Private note'});assert.equal(a.status,200);
  assert.equal((await call('/api/playlist','PUT',{revision:0,order:[],title:'stale',notes:''})).status,409);
  const edition=await jcall('/api/export','POST',{});const exportDispatches=dispatches;assert.equal((await jcall('/api/export','POST',{})).id,edition.id);assert.equal(dispatches,exportDispatches);
  await jcall(`/api/selections/${s.id}`,'PUT',{revision:1,note:'Another note after export snapshot'});
  assert.equal((await jcall(`/internal/exports/${edition.id}`,'GET',undefined,'run')).selections[0].note,'Updated private curation note');
  const exportBytes=new Uint8Array(8*1024*1024+123).fill(37);const object=await jcall('/internal/objects/begin','POST',{key:`exports/${edition.id}/release.zip`,bytes:exportBytes.length},'run');
  assert.equal((await call(`/internal/objects/${object.id}/complete`,'POST',{},'run')).status,409);
  for(let off=0,part=1;off<exportBytes.length;off+=object.part_size,part++)await jcall(`/internal/objects/${object.id}/part?n=${part}`,'PUT',exportBytes.subarray(off,off+object.part_size),'run');
  await jcall(`/internal/objects/${object.id}/complete`,'POST',{},'run');await jcall(`/internal/objects/${object.id}/complete`,'POST',{},'run');await jcall(`/internal/exports/${edition.id}`,'POST',{},'run');
  const exported=await call(`/api/exports/${edition.id}?download=1`,'GET',undefined,'admin',{Range:'bytes=-32'});assert.equal(exported.status,206);assert.equal((await exported.arrayBuffer()).byteLength,32);assert.equal(exported.headers.get('Cache-Control'),'private, no-store');
  assert.equal((await jcall('/api/state')).exports.find(e=>e.id===edition.id).status,'ready');
  const broken=await jcall('/api/generate','POST',{day:'2026-11-21'});await jcall(`/internal/jobs/${broken.id}/claim`,'POST',{run:'fail'},'run');await jcall(`/internal/jobs/${broken.id}/failed`,'POST',{run:'fail'},'run');assert.equal((await jcall('/public/current','GET',undefined,null)).day,'2026-11-20');
  const repaired=await jcall(`/api/jobs/${broken.id}/upgrade`,'POST',{});assert.equal(repaired.seed,broken.seed);assert.deepEqual(repaired.sources,broken.sources);assert.equal((await call(`/api/jobs/${first.id}/upgrade`,'POST',{})).status,409);
  const cachePath='/internal/cache/'+'b'.repeat(64)+'/'+'c'.repeat(64)+'.wav',cacheData=new Uint8Array([1,2,3,4]);
  await jcall(cachePath,'PUT',cacheData,'run');assert.equal((await call(cachePath,'PUT',new Uint8Array([4,3,2,1]),'run')).status,409);
  const cacheHash=createHash('sha256').update(cacheData).digest('hex');assert.equal((await call(cachePath+'?sha='+cacheHash,'HEAD',undefined,'run')).status,200);
  if(free){await publish('2026-11-21');await publish('2026-11-22');
  assert.ok(!(await jcall('/internal/cleanup','GET',undefined,'run')).includes('album-2026-11-20'));
  const copied=readFileSync('output/validation/01.mp3'),mockHeaders={Authorization:'Bearer test-only-github','Content-Type':'application/json'};
  const release=await(await github.fetch(new Request('https://api.github.com/repos/thebellacross/private-fixture/releases',{method:'POST',headers:mockHeaders,body:JSON.stringify({tag_name:'lab-'+fullTrack.id,draft:false})}))).json();
  const asset=await(await github.fetch(new Request(`https://uploads.github.com/repos/thebellacross/private-fixture/releases/${release.id}/assets?name=c0.mp3`,{method:'POST',headers:mockHeaders,body:copied}))).json();
  await jcall('/internal/storage/register','POST',{key:`lab/${fullTrack.id}/c0.mp3`,id:asset.id,bytes:copied.length,sha256:createHash('sha256').update(copied).digest('hex')},'run');
  const listeningJob=await jcall(`/internal/studio/tasks/${fullTrack.id}/claim`,'POST',{run:'retained-listening'},'run');
  await jcall(`/internal/studio/tasks/${fullTrack.id}/ready`,'POST',{run:'retained-listening',result:{engine_ref:listeningJob.config.engine_ref,files:{'c0.mp3':{bytes:copied.length,sha256:createHash('sha256').update(copied).digest('hex')}}}},'run');
  assert.ok((await jcall('/internal/cleanup','GET',undefined,'run')).includes('album-2026-11-20'));await jcall('/internal/cleanup','POST',{id:'album-2026-11-20'},'run');
  assert.equal((await call('/media/album-2026-11-20/01.mp3','GET',undefined,null)).status,404);
  const retainedListening=await call(`/api/studio/media/${fullTrack.id}/c0.mp3`,'GET',undefined,'admin',{Range:'bytes=0-31'});assert.equal(retainedListening.status,206);assert.deepEqual(new Uint8Array(await retainedListening.arrayBuffer()),new Uint8Array(copied.subarray(0,32)));}
  if(free){assert.ok(github.privateRedirects>0);const boundary=await call(`/api/exports/${edition.id}?download=1`,'GET',undefined,'admin',{Range:`bytes=${8*1024*1024-16}-${8*1024*1024+15}`});assert.equal(boundary.status,206);assert.deepEqual(new Uint8Array(await boundary.arrayBuffer()),new Uint8Array(32).fill(37));assert.ok(!JSON.stringify(await jcall('/public/selected','GET',undefined,null)).includes('private-fixture'));github.private=false;assert.equal((await call('/internal/cache/'+'a'.repeat(64)+'/manifest.json','PUT',new Uint8Array([1,2]),'run')).status,409);}
  console.log((free?'FREE GITHUB BACKEND ':'R2 BACKEND ')+ 'PASS: authentication, CSRF, explicit empty-source error, config/note/playlist concurrency, resumable upload identity, job and copy deduplication, retry snapshot, atomic publication, Range/CORS, permanent Selected after cleanup, multipart export with private cache policy, durable export history and failed-day recovery.');
}finally{await mf.dispose();}
