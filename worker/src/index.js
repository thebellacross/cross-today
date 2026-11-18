import {SignJWT, jwtVerify} from 'jose';
import defaults from '../../config.json';
import {GitHubBucket, reserveWrite} from './storage.js';
import {localClock,validDay,plan,retryable,safeHash,safeAsset,mime,eligibleForCleanup} from './logic.js';

const encoder=new TextEncoder();
const json=(data,status=200,headers={})=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
const id=()=>crypto.randomUUID();
class PublicError extends Error {constructor(message,status=400){super(message);this.publicMessage=message;this.status=status;}}
const hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
async function same(a,b) { return a&&b && (await hash(encoder.encode(a)))===(await hash(encoder.encode(b))); }
function publicAlbum(a,origin) {
  if (!a) return null;
  const base=`${origin}/media/${a.id}/`;
  return {...a,tracks:a.tracks.map(t=>({...t,src:base+t.src,wav:base+t.wav})),cover:base+a.cover,cover_small:base+a.cover_small,banner:base+a.banner,score:base+a.score,downloads:Object.fromEntries(Object.entries(a.downloads).map(([k,v])=>[k,base+v]))};
}
async function adminAuth(request,env) {
  const bearer=request.headers.get('Authorization')?.replace(/^Bearer /,'');
  if (bearer && await same(bearer,env.ADMIN_TOKEN)) return true;
  const cookie=request.headers.get('Cookie')?.match(/(?:^|; )bc_session=([^;]+)/)?.[1];
  if (!cookie || !env.SESSION_SECRET) return false;
  try { const v=await jwtVerify(cookie,encoder.encode(env.SESSION_SECRET),{issuer:'bellacross',audience:'admin',algorithms:['HS256']});return v.payload.sub==='owner'; } catch {return false;}
}
function cors(response,origin='*') {
  const r=new Response(response.body,response);r.headers.set('Access-Control-Allow-Origin',origin);
  r.headers.set('Access-Control-Allow-Headers','Range, Content-Type, X-Requested-With');r.headers.set('Access-Control-Expose-Headers','Content-Length, Content-Range, Accept-Ranges, ETag');
  r.headers.set('X-Content-Type-Options','nosniff');return r;
}
function secured(response) {
  const r=new Response(response.body,response);r.headers.set('X-Content-Type-Options','nosniff');r.headers.set('Referrer-Policy','same-origin');r.headers.set('X-Frame-Options','DENY');
  r.headers.set('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self' 'wasm-unsafe-eval'; img-src 'self' data: https://f4.bcbits.com; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");return r;
}
async function serveObject(bucket,key,request,filename) {
  const h=new Headers({'Content-Type':mime(filename),'Accept-Ranges':'bytes','Cache-Control':'public, max-age=31536000, immutable'});
  const head=await bucket.head(key);if(!head)return json({error:'Asset is unavailable'},404);
  h.set('ETag',head.httpEtag);
  if(request.headers.get('If-None-Match')===head.httpEtag)return new Response(null,{status:304,headers:h});
  if(request.method==='HEAD'){h.set('Content-Length',String(head.size));return new Response(null,{headers:h});}
  const range=request.headers.get('Range');let options={};let status=200;
  if(range){
    const m=/^bytes=(\d*)-(\d*)$/.exec(range);if(!m||(!m[1]&&!m[2]))return new Response(null,{status:416,headers:{'Content-Range':`bytes */${head.size}`}});
    const begin=m[1]?Number(m[1]):Math.max(0,head.size-Number(m[2]));const end=m[1]?(m[2]?Math.min(Number(m[2]),head.size-1):head.size-1):head.size-1;
    if(begin>end||begin>=head.size)return new Response(null,{status:416,headers:{'Content-Range':`bytes */${head.size}`}});
    options={range:{offset:begin,length:end-begin+1}};h.set('Content-Range',`bytes ${begin}-${end}/${head.size}`);h.set('Content-Length',String(end-begin+1));status=206;
  } else h.set('Content-Length',String(head.size));
  const obj=await bucket.get(key,options);return new Response(obj.body,{status,headers:h});
}
async function privateObject(bucket,key,request,filename) {
  const response=await serveObject(bucket,key,request,filename);
  response.headers.set('Cache-Control','private, no-store');return response;
}

export default {
  async fetch(request,env) {
    const url=new URL(request.url),path=url.pathname;const stub=env.COORDINATOR.get(env.COORDINATOR.idFromName('owner'));
    try {
      if(path.startsWith('/public/')||path.startsWith('/media/')||path.startsWith('/selected/')||path.startsWith('/catalog/')) {
        if(request.method==='OPTIONS')return cors(new Response(null,{status:204}));
        if(!['GET','HEAD'].includes(request.method))return cors(json({error:'Method not allowed'},405));
        return cors(await stub.fetch(request));
      }
      if(path.startsWith('/api/')) {
        const origin=request.headers.get('Origin');
        if(origin && origin!==url.origin)return json({error:'Origin rejected'},403);
        if(path==='/api/login'||path==='/api/redeem')return secured(await stub.fetch(request));
        if(!await adminAuth(request,env))return secured(json({error:'Sign in required'},401));
        if(request.method!=='GET' && request.headers.get('X-Requested-With')!=='bellacross' && !request.headers.has('Authorization'))return json({error:'Missing request verification'},403);
        return secured(await stub.fetch(request));
      }
      if(path.startsWith('/internal/')) {
        if(!await same(request.headers.get('Authorization')?.replace(/^Bearer /,''),env.RUN_TOKEN))return json({error:'Forbidden'},403);
        return stub.fetch(request);
      }
      if(path==='/'||path==='/admin')url.pathname='/admin.html';
      if(!['/admin.html','/admin.js','/admin.css','/artist.json','/vendor/hash.js'].includes(url.pathname)&&!url.pathname.startsWith('/assets/artist/'))return new Response('Not found',{status:404});
      return secured(await env.ASSETS.fetch(new Request(url,request)));
    } catch (error) { return json({error:error.publicMessage||'The service could not complete this request. Previous published audio is unchanged.'},error.status||500,error.retryAfter?{'Retry-After':String(error.retryAfter)}:{}); }
  },
  async scheduled(controller,env,ctx) {
    const stub=env.COORDINATOR.get(env.COORDINATOR.idFromName('owner'));
    ctx.waitUntil(stub.fetch(new Request('https://coordinator/internal/tick',{method:'POST',body:JSON.stringify({now:controller.scheduledTime})})));
  }
};

export class Coordinator {
  constructor(ctx,env){this.ctx=ctx;this.env=env;this.store=ctx.storage;this.sources=env.STORAGE_BACKEND==='r2'?env.SOURCES:new GitHubBucket(this,'sources');this.permanent=env.STORAGE_BACKEND==='r2'?env.PERMANENT:new GitHubBucket(this,'permanent');}
  async atomic(fn){let error;const result=await this.ctx.blockConcurrencyWhile(async()=>{try{return await fn();}catch(e){if(!e.publicMessage)throw e;error=e;}});if(error)throw error;return result;}
  async config(){return structuredClone(await this.store.get('config')||defaults);}
  async list(prefix){return [...(await this.store.list({prefix})).values()];}
  async dispatch(mode,jobId) {
    const job=await this.store.get('job:'+jobId);const ref=job?.config?.engine_ref||'main';
    const r=await fetch(`https://api.github.com/repos/${this.env.GITHUB_REPOSITORY}/actions/workflows/daily.yml/dispatches`,{method:'POST',headers:{Authorization:`Bearer ${this.env.GITHUB_TOKEN}`,Accept:'application/vnd.github+json','User-Agent':'bellacross-daily','Content-Type':'application/json'},body:JSON.stringify({ref,inputs:{mode,job:jobId}})});
    if(!r.ok)throw new Error('GitHub dispatch failed');
  }
  async ensure(day,publish=false,manual=false) {
    if(!validDay(day))throw new PublicError('Invalid generation date.');
    const config=await this.config();const jobId='album-'+day;let shouldDispatch=false;
    const job=await this.atomic(async()=>{
      let j=await this.store.get('job:'+jobId);const now=Date.now();
      if(j?.status==='ready') {if(publish){j.publish=true;await this.store.put('job:'+jobId,j);shouldDispatch=true;}return j;}
      if(j?.status==='published'||j?.status==='retired')return j;
      if(!j){
        const sources=(await this.list('source:')).filter(s=>s.enabled&&s.status!=='invalid').sort((a,b)=>a.hash.localeCompare(b.hash));
        if(!sources.length)throw new PublicError('No valid selected materials. Upload or enable recordings before generating.');
        const number=(await this.store.get('next-number'))??config.series.first_number;
        const seed=String(BigInt('0x'+crypto.randomUUID().replaceAll('-','').slice(0,15)));
        const odds=Math.max(1,config.series.last_odds+1-number);const endDraw=crypto.getRandomValues(new Uint32Array(1))[0]/2**32;
        j={id:jobId,day,number,seed,config,final_decision:config.series.random_end&&endDraw<1/odds,sources:sources.map(({hash,name,tags,extension,bytes})=>({hash,name,tags,extension,bytes})),status:'queued',attempts:0,publish,created:now};
        await this.store.put('next-number',number+1);
      }
      if(manual&&j.status==='failed'){j.attempts=0;j.retry_after=0;}
      if(retryable(j,now,config.schedule)) { j.status='queued';j.publish ||= publish;j.dispatched=now;j.lease_until=now+10*60*1000;shouldDispatch=true; }
      await this.store.put('job:'+jobId,j);return j;
    });
    if(shouldDispatch){try{await this.dispatch(job.status==='ready'?'publish':'render',jobId);}catch{await this.fail(jobId,'Could not start GitHub Actions. Check the GitHub connection.');}}
    return job;
  }
  async fail(jobId,message,run=null) {
    const cfg=await this.config();await this.atomic(async()=>{const j=await this.store.get('job:'+jobId);if(run&&j?.run!==run)throw new PublicError('Run lease mismatch',409);if(j&&!['published','retired'].includes(j.status)){j.status='failed';j.error=message;j.lease_until=0;j.retry_after=Date.now()+cfg.schedule.retry_minutes*60000;await this.store.put('job:'+jobId,j);}});
  }
  async dispatchSaved(kind,taskId,manual=false) {
    let send=false;const key=kind+':'+taskId;
    const task=await this.atomic(async()=>{const t=await this.store.get(key);if(!t||t.status==='ready')return t;const now=Date.now();if((t.lease_until||0)>now)return t;if(manual&&t.status==='failed')t.attempts=0;if((t.attempts||0)>=4||(!manual&&(t.retry_after||0)>now))return t;t.status='queued';t.attempts=(t.attempts||0)+1;t.lease_until=now+30*60000;await this.store.put(key,t);send=true;return t;});
    if(send)try{await this.dispatch(kind==='selection'?'select':'export',taskId);}catch{await this.atomic(async()=>{const t=await this.store.get(key);if(t.status==='ready')return;t.status='failed';t.error='Could not start the copy/export task. Retry after reconnecting GitHub.';t.lease_until=0;t.retry_after=Date.now()+15*60000;await this.store.put(key,t);});}
    return task;
  }
  async fetch(request) {
    try{return await this.handle(request);}catch(error){return json({error:error.publicMessage||'The service could not complete this request. Previous published audio is unchanged.'},error.status||500,error.retryAfter?{'Retry-After':String(error.retryAfter)}:{});}
  }
  async handle(request) {
    const url=new URL(request.url),p=url.pathname,method=request.method,origin=url.origin;
    const body=async()=>request.json();
    if(p==='/api/login-link'&&method==='POST') {
      const code=Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,'0')).join('');
      await this.store.put('handoff:'+await hash(encoder.encode(code)),{expires:Date.now()+120000});
      return json({code,expires_in:120});
    }
    if(p==='/api/redeem'&&method==='POST') {
      const {code}=await body();if(typeof code!=='string'||!/^[0-9a-f]{64}$/.test(code))return json({error:'Login link expired'},401);
      const accepted=await this.atomic(async()=>{const key='handoff:'+await hash(encoder.encode(code)),saved=await this.store.get(key);if(!saved)return false;await this.store.delete(key);return saved.expires>Date.now();});
      if(!accepted)return json({error:'Login link expired or already used'},401);
      const jwt=await new SignJWT({}).setProtectedHeader({alg:'HS256'}).setSubject('owner').setIssuer('bellacross').setAudience('admin').setIssuedAt().setExpirationTime('12h').sign(encoder.encode(this.env.SESSION_SECRET));
      return json({ok:true},200,{'Set-Cookie':`bc_session=${jwt}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=43200`});
    }
    if(p==='/api/login'&&method==='POST') {
      const ip=request.headers.get('CF-Connecting-IP')||'local';const key='login:'+await hash(encoder.encode(ip));
      const limit=await this.atomic(async()=>{let v=await this.store.get(key)||{time:Date.now(),count:0};if(Date.now()-v.time>900000)v={time:Date.now(),count:0};v.count++;await this.store.put(key,v);return v;});
      if(limit.count>12)return json({error:'Too many attempts. Try again in 15 minutes.'},429);
      const {password}=await body();if(!await same(password,this.env.ADMIN_TOKEN))return json({error:'Sign in failed'},401);
      const jwt=await new SignJWT({}).setProtectedHeader({alg:'HS256'}).setSubject('owner').setIssuer('bellacross').setAudience('admin').setIssuedAt().setExpirationTime('12h').sign(encoder.encode(this.env.SESSION_SECRET));
      return json({ok:true},200,{'Set-Cookie':`bc_session=${jwt}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=43200`});
    }
    if(p==='/api/logout'&&method==='POST')return json({ok:true},200,{'Set-Cookie':'bc_session=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0'});
    if(p==='/public/current'){const current=await this.store.get('current');return json(publicAlbum(current,origin),current?200:404);}
    if(p.startsWith('/public/album/')){const jobId=p.slice('/public/album/'.length);if(!/^album-\d{4}-\d{2}-\d{2}$/.test(jobId))return json({error:'Not found'},404);const j=await this.store.get('job:'+jobId);return j?.status==='published'?json(publicAlbum(j.album,origin)):json({error:'Edition unavailable'},404);}
    if(p==='/public/catalog')return json((await this.list('catalog:')).sort((a,b)=>b.day.localeCompare(a.day)).map(c=>({...c,cover:`${origin}/catalog/${c.id}/cover-small.jpg`})));
    if(p==='/public/selected')return json((await this.list('selection:')).filter(x=>x.status==='ready').map(x=>({id:x.id,title:x.track.title,duration:x.track.duration,src:`${origin}/selected/${x.id}/track.mp3`,wav:`${origin}/selected/${x.id}/track.wav`,cover:`${origin}/selected/${x.id}/cover.png`})));
    let match;
    if((match=p.match(/^\/catalog\/(album-\d{4}-\d{2}-\d{2})\/(cover-small\.jpg)$/)))return serveObject(this.permanent,`catalog/${match[1]}/${match[2]}`,request,match[2]);
    if((match=p.match(/^\/selected\/([0-9a-f-]{36})\/(track\.(?:mp3|wav)|cover\.png)$/))) {
      const selection=await this.store.get('selection:'+match[1]);if(selection?.status!=='ready')return json({error:'Not found'},404);
      return serveObject(this.permanent,`selected/${match[1]}/${match[2]}`,request,match[2]);
    }
    if((match=p.match(/^\/media\/(album-\d{4}-\d{2}-\d{2})\/([^/]+)$/))) {
      const [,jobId,name]=match;const j=await this.store.get('job:'+jobId);
      if(j?.status!=='published'||!safeAsset(name)||!j.album?.assets[name])return json({error:'This daily edition is no longer available.'},404);
      const range=request.headers.get('Range');if(range&&!/^bytes=\d*-\d*$/.test(range))return new Response(null,{status:416});
      const r=await fetch(`https://github.com/${this.env.GITHUB_REPOSITORY}/releases/download/${jobId}/${name}`,{method,headers:range?{Range:range}:{},redirect:'follow'});
      if(!r.ok)return new Response(null,{status:r.status===416?416:r.status===404?404:502,headers:r.status===416?{'Content-Range':r.headers.get('Content-Range')||''}:{}});
      const h=new Headers({'Content-Type':mime(name),'Accept-Ranges':'bytes','Cache-Control':'public,max-age=300'});for(const k of ['Content-Length','Content-Range','ETag','Last-Modified'])if(r.headers.has(k))h.set(k,r.headers.get(k));
      return new Response(method==='HEAD'?null:r.body,{status:r.status,headers:h});
    }
    if(p==='/api/state') {
      const cfg=await this.config();const jobs=(await this.list('job:')).sort((a,b)=>b.day.localeCompare(a.day));
      return json({config:cfg,config_revision:await this.store.get('config-revision')||0,sources:await this.list('source:'),jobs:jobs.map(({sources,config,...rest})=>rest),current:publicAlbum(await this.store.get('current'),origin),selections:await this.list('selection:'),exports:await this.list('export:'),playlist:await this.store.get('playlist')||{revision:0,order:[],notes:'',title:''},ended:!!await this.store.get('ended'),last_tick:await this.store.get('last-tick')||null});
    }
    if(p==='/api/config'&&method==='PUT') {
      const update=await body();return this.atomic(async()=>{const revision=await this.store.get('config-revision')||0;if(update.revision!==revision)return json({error:'Settings changed in another session. Refresh before saving.'},409);const cfg=await this.config();
      // Public-safe configurable musical parameters only; authentication secrets are never accepted here.
      if(update.project_name!==undefined)cfg.project_name=String(update.project_name).slice(0,100)||null;
      if(update.generation){const g=update.generation;if(!['chance','fusion','loops','baseline','fontana','automaton','drift'].includes(g.form))return json({error:'Invalid form'},400);cfg.generation.form=g.form;for(const key of ['garble','stereo_width'])if(g[key]!==undefined){if(!Number.isFinite(g[key])||g[key]<0||g[key]>1)return json({error:'Musical amounts must be between 0 and 1.'},400);cfg.generation[key]=g[key];}if(g.daily_parameters!==undefined)cfg.generation.daily_parameters=!!g.daily_parameters;}
      if(update.import){const s=update.import;if(!(s.segment_seconds>=1&&s.segment_seconds<=600&&s.overlap_seconds>=0&&s.overlap_seconds<s.segment_seconds))return json({error:'Invalid segment settings'},400);cfg.import.segment_seconds=s.segment_seconds;cfg.import.overlap_seconds=s.overlap_seconds;}
      if(update.schedule){for(const key of ['prepare_hour','publish_hour'])if(update.schedule[key]!==undefined){if(!Number.isInteger(update.schedule[key])||update.schedule[key]<0||update.schedule[key]>23)return json({error:'Schedule hours must be 0–23.'},400);cfg.schedule[key]=update.schedule[key];}}
      if(update.series){if(update.series.random_end!==undefined)cfg.series.random_end=!!update.series.random_end;if(update.series.keep_releases!==undefined){if(!Number.isInteger(update.series.keep_releases)||update.series.keep_releases<1||update.series.keep_releases>30)return json({error:'Retain between 1 and 30 daily editions.'},400);cfg.series.keep_releases=update.series.keep_releases;}}
      await this.store.put('config',cfg);await this.store.put('config-revision',revision+1);return json({ok:true,revision:revision+1});});
    }
    if(p==='/api/generate'&&method==='POST'){const b=await body();const cfg=await this.config();const day=b.day||localClock(new Date(),cfg.timezone).day;return json(await this.ensure(day,true,true));}
    if((match=p.match(/^\/api\/jobs\/(album-\d{4}-\d{2}-\d{2})\/resnapshot$/))&&method==='POST') {
      const jobId=match[1];await this.atomic(async()=>{const j=await this.store.get('job:'+jobId);if(j?.status!=='failed')throw new PublicError('Only a failed job can be restarted with new materials.',409);const sources=(await this.list('source:')).filter(s=>s.enabled&&s.status!=='invalid').sort((a,b)=>a.hash.localeCompare(b.hash));if(!sources.length)throw new PublicError('No valid selected materials.');await this.store.put(`job-history:${jobId}:${id()}`,j);j.sources=sources.map(({hash,name,tags,extension,bytes})=>({hash,name,tags,extension,bytes}));j.config=await this.config();j.seed=String(BigInt('0x'+crypto.randomUUID().replaceAll('-','').slice(0,15)));j.attempts=0;j.run=null;j.lease_until=0;j.retry_after=0;j.album=null;await this.store.put('job:'+jobId,j);});return json(await this.ensure(jobId.slice(6),true,true));
    }
    if(p==='/api/series/resume'&&method==='POST'){await this.store.put('ended',false);return json({ok:true});}
    if(p==='/api/uploads/begin'&&method==='POST') {
      const b=await body();if(!safeHash(b.hash)||!/^\.(wav|aiff?|mp3|m4a|flac)$/i.test(b.extension)||!Number.isSafeInteger(b.bytes)||b.bytes<=0||b.bytes>20*1024**3)return json({error:'Unsupported audio file'},400);
      return this.atomic(async()=>{
      const prior=await this.store.get('source:'+b.hash);if(prior)return json({exists:true,source:prior});
      const pendingId=await this.store.get('upload-source:'+b.hash);const pending=pendingId&&await this.store.get('upload:'+pendingId);if(pending&&!pending.done&&pending.bytes===b.bytes&&Date.now()-pending.created<6*86400000)return json({id:pending.id,part_size:8*1024*1024});
      const cfg=await this.config();const used=(await this.list('source:')).reduce((n,s)=>n+s.bytes,0)+(await this.list('upload:')).filter(u=>!u.done&&Date.now()-u.created<6*86400000).reduce((n,u)=>n+u.bytes,0);
      if(used+b.bytes>(cfg.storage?.max_source_bytes||5*1024**3))return json({error:'已达到当前免费方案的项目素材上限；原素材不受影响。请先调整存储方案。'},409);
      const uploadId=id();const upload=await this.sources.createMultipartUpload('originals/'+b.hash+'/'+uploadId,{httpMetadata:{contentType:'application/octet-stream'}});
      const name=String(b.name).split(/[\\/]/).pop().slice(0,180);
      await this.store.put('upload:'+uploadId,{id:uploadId,uploadId:upload.uploadId,key:upload.key,hash:b.hash,name,tags:[],extension:b.extension.toLowerCase(),bytes:b.bytes,parts:{},created:Date.now()});
      await this.store.put('upload-source:'+b.hash,uploadId);return json({id:uploadId,part_size:8*1024*1024});});
    }
    if((match=p.match(/^\/api\/uploads\/([0-9a-f-]{36})\/(part|complete)$/))) {
      const uploadId=match[1],u=await this.store.get('upload:'+uploadId);if(!u)return json({error:'Unknown upload'},404);
      if(u.done)return json({ok:true,hash:u.hash});
      const upload=this.sources.resumeMultipartUpload(u.key,u.uploadId);
      if(match[2]==='part'&&method==='PUT') {
        const n=Number(url.searchParams.get('n'));if(!Number.isInteger(n)||n<1||n>10000)return json({error:'Invalid part'},400);
        const data=await request.arrayBuffer();if(data.byteLength>8*1024*1024||!data.byteLength)return json({error:'Invalid part size'},413);
        const part=await upload.uploadPart(n,data);
        await this.store.put(`upload-part:${uploadId}:${String(n).padStart(5,'0')}`,{...part,bytes:data.byteLength});return json({ok:true});
      }
      if(match[2]==='complete'&&method==='POST') {
        return this.atomic(async()=>{
        if((await this.store.get('upload:'+uploadId)).done)return json({ok:true,hash:u.hash});
        const parts=(await this.list(`upload-part:${uploadId}:`)).sort((a,b)=>a.partNumber-b.partNumber);
        if(parts.reduce((n,p)=>n+p.bytes,0)!==u.bytes||parts.some((p,i)=>p.partNumber!==i+1))return json({error:'Upload incomplete'},409);
        if(!await this.sources.head(u.key))await upload.complete(parts.map(({partNumber,etag})=>({partNumber,etag})));
        if(!await this.store.get('source:'+u.hash))await this.store.put('source:'+u.hash,{hash:u.hash,object_key:u.key,name:u.name,tags:u.tags,extension:u.extension,bytes:u.bytes,status:'pending',enabled:true,uploaded:Date.now()});u.done=true;await this.store.put('upload:'+uploadId,u);
        return json({ok:true,hash:u.hash,status:'pending'});});
      }
    }
    if((match=p.match(/^\/api\/sources\/([0-9a-f]{64})$/))&&method==='PUT') {
      const b=await body();await this.atomic(async()=>{const s=await this.store.get('source:'+match[1]);if(!s)return;if(typeof b.enabled==='boolean')s.enabled=b.enabled;if(Array.isArray(b.tags))s.tags=b.tags.map(x=>String(x).slice(0,60)).slice(0,20);await this.store.put('source:'+match[1],s);});return json({ok:true});
    }
    if(p==='/api/select'&&method==='POST') {
      const b=await body();if(!/^album-\d{4}-\d{2}-\d{2}$/.test(b.album)||!Number.isInteger(b.track))return json({error:'Invalid selection'},400);
      let selection=await this.atomic(async()=>{
        const old=(await this.list('selection:')).find(s=>s.album===b.album&&s.track.n===b.track);if(old)return old;
        const j=await this.store.get('job:'+b.album);if(j?.status!=='published')throw new PublicError('Album unavailable',409);
        const track=j.album.tracks.find(t=>t.n===b.track);if(!track)throw new PublicError('Unknown track');
        const cfg=await this.config(),bytes=[track.wav,track.src,'cover.png','provenance.json','credits.txt'].reduce((n,k)=>n+(j.album.assets[k]?.bytes||0),0);
        const retained=(await this.list('selection:')).reduce((n,s)=>n+(s.bytes||0),0);if(retained+bytes>(cfg.storage?.max_selected_bytes||10*1024**3))throw new PublicError('已达到免费方案的 Selected 项目上限；已保存的曲目仍可播放。',409);
        const s={id:id(),album:b.album,track,bytes,status:'queued',note:String(b.note||'').slice(0,4000),revision:0,created:Date.now()};await this.store.put('selection:'+s.id,s);return s;
      });
      return json(await this.dispatchSaved('selection',selection.id,true));
    }
    if((match=p.match(/^\/api\/selections\/([0-9a-f-]{36})$/))&&method==='PUT'){const b=await body();return this.atomic(async()=>{const s=await this.store.get('selection:'+match[1]);if(!s)return json({error:'Unknown selection'},404);if(b.revision!==(s.revision||0))return json({error:'This note changed in another session. Refresh before saving.'},409);s.note=String(b.note||'').slice(0,4000);s.revision=(s.revision||0)+1;await this.store.put('selection:'+s.id,s);return json(s);});}
    if(p==='/api/playlist'&&method==='PUT') {
      const b=await body();return this.atomic(async()=>{const prior=await this.store.get('playlist')||{revision:0};if(prior.revision!==b.revision)return json({error:'The selection changed in another session. Refresh and try again.'},409);
        const available=new Set((await this.list('selection:')).filter(x=>x.status==='ready').map(x=>x.id));if(!Array.isArray(b.order)||new Set(b.order).size!==b.order.length||b.order.some(k=>!available.has(k)))return json({error:'Unknown selected track'},400);
        const next={order:b.order,notes:String(b.notes||'').slice(0,10000),title:String(b.title||'').slice(0,180),revision:prior.revision+1};if(JSON.stringify([prior.order,prior.notes,prior.title])===JSON.stringify([next.order,next.notes,next.title]))return json(prior);await this.store.put('playlist',next);return json(next);});
    }
    if(p==='/api/export'&&method==='POST') {const e=await this.atomic(async()=>{const playlist=await this.store.get('playlist');if(!playlist?.order.length)throw new PublicError('Choose and order tracks first');const selections=await Promise.all(playlist.order.map(k=>this.store.get('selection:'+k)));const fingerprint=await hash(encoder.encode(JSON.stringify({playlist,notes:selections.map(s=>[s.id,s.revision||0])})));const existing=(await this.list('export:')).find(x=>x.fingerprint===fingerprint);if(existing)return existing;const e={id:id(),playlist,selections,fingerprint,status:'queued',created:Date.now()};await this.store.put('export:'+e.id,e);return e;});return json(await this.dispatchSaved('export',e.id,true));}
    if((match=p.match(/^\/api\/exports\/([0-9a-f-]{36})\/retry$/))&&method==='POST')return json(await this.dispatchSaved('export',match[1],true));
    if((match=p.match(/^\/api\/exports\/([0-9a-f-]{36})$/))) {const e=await this.store.get('export:'+match[1]);if(!e)return json({error:'Not found'},404);if(url.searchParams.has('download')&&e.status==='ready'){const name=url.searchParams.get('file')||'release.zip';if(!(e.files||['release.zip']).includes(name))return json({error:'Unknown volume'},404);const r=await privateObject(this.permanent,`exports/${e.id}/${name}`,request,name);r.headers.set('Content-Disposition',`attachment; filename="${name}"`);return r;}return json(e);}
    if(p==='/internal/tick'&&method==='POST') {
      const cfg=await this.config(),input=await body();const now=new Date(input.now||Date.now());let errors=[];
      for(const todo of plan(now,cfg,await this.store.get('current'),await this.store.get('ended')))try{await this.ensure(todo.day,todo.publish);}catch(e){errors.push(e.message);}
      for(const kind of ['selection','export'])for(const t of await this.list(kind+':'))if(t.status!=='ready')await this.dispatchSaved(kind,t.id);
      await this.store.put('last-tick',{time:now.toISOString(),errors});return json({ok:!errors.length,errors});
    }
    if((match=p.match(/^\/internal\/jobs\/(album-\d{4}-\d{2}-\d{2})\/(claim|ready|publish|failed)$/))&&method==='POST') {
      const [,jobId,action]=match,b=await body();
      if(action==='failed'){await this.fail(jobId,'Generation failed. Retry uses the saved materials and seed. See the Actions run status.',b.run);return json({ok:true});}
      return this.atomic(async()=>{
        const j=await this.store.get('job:'+jobId);if(!j)return json({error:'Unknown job'},404);
        if(action==='claim') {
          if(['published','retired'].includes(j.status))return json({done:true});
          if(j.status==='rendering'&&j.lease_until>Date.now()&&j.run!==b.run)return json({error:'Already running'},409);
          if(j.status!=='ready'){j.status='rendering';j.attempts++;j.lease_until=Date.now()+j.config.schedule.lease_minutes*60000;}
          j.run=b.run;await this.store.put('job:'+jobId,j);return json(j);
        }
        if(b.run!==j.run)return json({error:'Run lease mismatch'},409);
        if(action==='ready') {
          if(b.album?.id!==j.id||String(b.album.seed)!==j.seed||!b.album.assets||!b.album.tracks?.length)return json({error:'Invalid album'},400);
          j.album=b.album;j.status='ready';j.lease_until=0;await this.store.put('job:'+jobId,j);return json({ok:true,publish:j.publish});
        }
        if(action==='publish') {
          if(j.status==='published')return json({ok:true});
          if(j.status!=='ready')return json({error:'Assets are not ready'},409);
          const current=await this.store.get('current');if(current&&current.day>j.day)return json({error:'Cannot replace a newer edition'},409);
          j.status='published';j.published=Date.now();j.final=j.album.final;
          await this.store.put('job:'+jobId,j);await this.store.put('current',j.album);
          await this.store.put('catalog:'+jobId,{id:j.id,day:j.day,catalog:j.album.catalog,title:j.album.title,number:j.number,available:true,final:j.final,seed:j.seed});
          if(j.final)await this.store.put('ended',true);return json({ok:true});
        }
      });
    }
    if((match=p.match(/^\/internal\/sources\/([0-9a-f]{64})$/))) {
      const s=await this.store.get('source:'+match[1]);if(!s)return json({error:'Unknown source'},404);
      if(['GET','HEAD'].includes(method))return privateObject(this.sources,s.object_key,request,s.name);
      if(method==='PUT'){const b=await body();await this.atomic(async()=>{const latest=await this.store.get('source:'+s.hash);latest.status=b.ok?'ready':'invalid';latest.clips=b.clips||0;await this.store.put('source:'+s.hash,latest);});return json({ok:true});}
    }
    if((match=p.match(/^\/internal\/cache\/([0-9a-f]{64})\/(manifest\.json|[0-9a-f]{64}\.wav)$/))) {
      const key=`derived/${match[1]}/${match[2]}`;
      if(method==='PUT'){await this.sources.put(key,request.body);return json({ok:true});}
      if(['GET','HEAD'].includes(method))return privateObject(this.sources,key,request,match[2]);
    }
    if(p==='/internal/storage/write'&&method==='POST'){await reserveWrite(this);return json({ok:true});}
    if(p==='/internal/storage/register'&&method==='POST') {
      const b=await body();if(!/^(selected\/[0-9a-f-]{36}\/(track\.(wav|mp3)|cover\.png|provenance\.json|credits\.txt)|catalog\/album-\d{4}-\d{2}-\d{2}\/cover-small\.jpg|exports\/[0-9a-f-]{36}\/release(?:-\d{2,4})?\.zip)$/.test(b.key)||!this.permanent.register)return json({error:'Invalid registration'},400);
      await this.permanent.register(b.key,b);return json({ok:true});
    }
    if(p==='/internal/objects/begin'&&method==='POST') {
      const b=await body();if(!/^(selected\/[0-9a-f-]{36}\/(track\.(wav|mp3)|cover\.png|provenance\.json|credits\.txt)|exports\/[0-9a-f-]{36}\/release(?:-\d{2,4})?\.zip)$/.test(b.key)||!Number.isSafeInteger(b.bytes)||b.bytes<=0)return json({error:'Invalid permanent object'},400);
      const upload=await this.permanent.createMultipartUpload(b.key,{httpMetadata:{contentType:mime(b.key)}});const uploadId=id();await this.store.put('object-upload:'+uploadId,{id:uploadId,key:b.key,bytes:b.bytes,uploadId:upload.uploadId});return json({id:uploadId,part_size:8*1024*1024});
    }
    if((match=p.match(/^\/internal\/objects\/([0-9a-f-]{36})\/(part|complete)$/))) {
      const u=await this.store.get('object-upload:'+match[1]);if(!u)return json({error:'Not found'},404);if(u.done)return json({ok:true});const upload=this.permanent.resumeMultipartUpload(u.key,u.uploadId);
      if(match[2]==='part'&&method==='PUT'){const n=Number(url.searchParams.get('n'));if(!Number.isInteger(n)||n<1||n>10000)return json({error:'Invalid part'},400);const data=await request.arrayBuffer();if(data.byteLength>8*1024*1024)return json({error:'Part too large'},413);const part=await upload.uploadPart(n,data);await this.store.put(`object-part:${u.id}:${String(n).padStart(5,'0')}`,{...part,bytes:data.byteLength});return json({ok:true});}
      if(match[2]==='complete'&&method==='POST'){const parts=(await this.list(`object-part:${u.id}:`)).sort((a,b)=>a.partNumber-b.partNumber);if(parts.reduce((n,p)=>n+p.bytes,0)!==u.bytes||parts.some((p,i)=>p.partNumber!==i+1))return json({error:'Object incomplete'},409);if(!await this.permanent.head(u.key))await upload.complete(parts.map(({partNumber,etag})=>({partNumber,etag})));u.done=true;await this.store.put('object-upload:'+u.id,u);return json({ok:true});}
    }
    if((match=p.match(/^\/internal\/permanent\/((?:catalog\/album-\d{4}-\d{2}-\d{2}\/cover-small\.jpg)|(?:selected\/[0-9a-f-]{36}\/(?:track\.(?:wav|mp3)|cover\.png|provenance\.json|credits\.txt))|(?:exports\/[0-9a-f-]{36}\/release(?:-\d{2,4})?\.zip)|(?:snapshots\/album-\d{4}-\d{2}-\d{2}\.json))$/))) {
      if(method==='PUT'){await this.permanent.put(match[1],request.body,{httpMetadata:{contentType:mime(match[1])}});return json({ok:true});}
      if(['GET','HEAD'].includes(method))return privateObject(this.permanent,match[1],request,match[1]);
    }
    if((match=p.match(/^\/internal\/selections\/([0-9a-f-]{36})$/))) {
      const s=await this.store.get('selection:'+match[1]);if(!s)return json({error:'Not found'},404);
      if(method==='GET'){const j=await this.store.get('job:'+s.album);return json({...s,manifest:j.album});}
      if(method==='POST') {
        const b=await body();if(b.status==='ready'){
          for(const name of ['track.wav','track.mp3','cover.png','provenance.json','credits.txt'])if(!await this.permanent.head(`selected/${s.id}/${name}`))return json({error:'Permanent files incomplete'},409);
        }
        return this.atomic(async()=>{const latest=await this.store.get('selection:'+s.id);if(latest.status==='ready')return json({ok:true});latest.status=b.status==='ready'?'ready':'failed';latest.lease_until=0;latest.retry_after=Date.now()+15*60000;if(latest.status==='ready'){latest.completed=Date.now();delete latest.error;}else latest.error='Permanent copy failed. The daily album is pinned until retry.';await this.store.put('selection:'+s.id,latest);return json({ok:true});});
      }
    }
    if((match=p.match(/^\/internal\/exports\/([0-9a-f-]{36})$/))) {const e=await this.store.get('export:'+match[1]);if(!e)return json({error:'Not found'},404);if(method==='GET')return json(e);if(method==='POST'){const b=await body();const files=b.files||['release.zip'];if(b.status!=='failed'){if(!Array.isArray(files)||!files.length||files.length>9999||new Set(files).size!==files.length||files.some(f=>!/^release(?:-\d{2,4})?\.zip$/.test(f)))return json({error:'Invalid export volumes'},400);for(const f of files)if(!await this.permanent.head(`exports/${e.id}/${f}`))return json({error:'Export incomplete'},409);}return this.atomic(async()=>{const latest=await this.store.get('export:'+e.id);if(latest.status==='ready')return json({ok:true});latest.status=b.status==='failed'?'failed':'ready';if(latest.status==='ready')latest.files=files;latest.lease_until=0;latest.retry_after=Date.now()+15*60000;await this.store.put('export:'+e.id,latest);return json({ok:true});});}}
    if(p==='/internal/cleanup') {
      return this.atomic(async()=>{
        const cfg=await this.config();const pins=new Set((await this.list('selection:')).filter(x=>x.status!=='ready').map(x=>x.album));
        if(method==='GET'){const jobs=await this.list('job:');return json([...eligibleForCleanup(jobs,await this.store.get('current'),pins,cfg.series.keep_releases),...jobs.filter(j=>j.status==='retired'&&!j.release_deleted)].map(j=>j.id));}
        if(method==='POST'){const {id:jobId,deleted}=await body();const j=await this.store.get('job:'+jobId);const eligible=eligibleForCleanup(await this.list('job:'),await this.store.get('current'),pins,cfg.series.keep_releases);if(!eligible.find(j=>j.id===jobId)&&j?.status!=='retired')return json({error:'Album is pinned or current'},409);j.status='retired';if(deleted)j.release_deleted=true;await this.store.put('job:'+jobId,j);const c=await this.store.get('catalog:'+jobId);if(c){c.available=false;await this.store.put('catalog:'+jobId,c);}return json({ok:true});}
      });
    }
    return json({error:'Not found'},404);
  }
}
