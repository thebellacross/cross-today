// All choices in this file are SIMULATED in an isolated local Durable Object.
// Nothing is submitted to the owner's deployed service or real preference history.
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {chromium,webkit,devices} from 'playwright';
import assert from 'node:assert/strict';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {githubFixture} from './github-fixture.mjs';
const github=githubFixture(),fixtureDir='.state/listening-ready',fixture=JSON.parse(readFileSync(fixtureDir+'/result.json'));
const headers={Authorization:'Bearer test-only-github','Content-Type':'application/json'};
const mf=new Miniflare(convertV4MiniflareOptions({workers:[{name:'studio-test',modules:true,scriptPath:'.state/worker.mjs',compatibilityDate:'2026-11-01',durableObjects:{COORDINATOR:{className:'Coordinator',useSQLite:true}},bindings:{STORAGE_BACKEND:'github-free',STORAGE_REPOSITORY:'thebellacross/private-fixture',ADMIN_TOKEN:'test-only-admin',SESSION_SECRET:'test-only-long-session-secret-1234567890',RUN_TOKEN:'test-only-run',GITHUB_TOKEN:'test-only-github',GITHUB_REPOSITORY:'thebellacross/cross-today'},serviceBindings:{ASSETS:async req=>{const path=new URL(req.url).pathname;try{return new Response(readFileSync('web'+path),{headers:{'Content-Type':path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'}});}catch{return new Response('not found',{status:404});}}},outboundService:github.fetch}]}));
const call=(path,method='GET',body,role='admin',extra={})=>mf.dispatchFetch('https://example.test'+path,{method,headers:{Authorization:'Bearer '+(role==='admin'?'test-only-admin':'test-only-run'),'Content-Type':'application/json',...extra},body:body===undefined?undefined:JSON.stringify(body)});
const get=async(...args)=>{const r=await call(...args);const j=await r.json();assert.ok(r.ok,JSON.stringify({path:args[0],status:r.status,error:j.error}));return j;};
async function retain(id,files){
 const release=await (await github.fetch(new Request('https://api.github.com/repos/thebellacross/private-fixture/releases',{method:'POST',headers,body:JSON.stringify({tag_name:'lab-'+id,draft:false})}))).json();const metas={};
 for(const [name,data]of Object.entries(files)){const asset=await (await github.fetch(new Request(`https://uploads.github.com/repos/thebellacross/private-fixture/releases/${release.id}/assets?name=${name}`,{method:'POST',headers,body:data}))).json();const meta={sha256:createHash('sha256').update(data).digest('hex'),bytes:data.length};await get('/internal/storage/register','POST',{key:`lab/${id}/${name}`,id:asset.id,...meta},'run');metas[name]=meta;}return metas;
}
let browser;
try{
 assert.equal((await mf.dispatchFetch('https://example.test/api/studio/state')).status,401);
 const data=readFileSync('C_SoundSource/Snaredrum.wav'),hash=createHash('sha256').update(data).digest('hex');
 const u=await get('/api/uploads/begin','POST',{hash,bytes:data.length,name:'Snaredrum.wav',extension:'.wav'});
 await mf.dispatchFetch(`https://example.test/api/uploads/${u.id}/part?n=1`,{method:'PUT',headers:{Authorization:'Bearer test-only-admin'},body:data});await get(`/api/uploads/${u.id}/complete`,'POST',{});
 const request={request_id:'render-fixture',profile_id:'open',seconds:24,source_hashes:[hash]};const t=await get('/api/studio/render','POST',request);assert.equal((await get('/api/studio/render','POST',request)).id,t.id);assert.equal(github.dispatches,1);
 const claimed=await get(`/internal/studio/tasks/${t.id}/claim`,'POST',{run:'fixture'},'run');assert.equal(claimed.config.engine_ref,JSON.parse(readFileSync('config.json')).engine_ref);assert.equal((await call(`/internal/studio/tasks/${t.id}/claim`,'POST',{run:'stale'},'run')).status,409);
 const files=Object.fromEntries(Object.keys(fixture.files).map(name=>[name,readFileSync(fixtureDir+'/'+name)]));const metas=await retain(t.id,files);
 await get(`/internal/studio/tasks/${t.id}/ready`,'POST',{run:'fixture',result:{...fixture,engine_ref:claimed.config.engine_ref,files:metas}},'run');
 assert.equal((await mf.dispatchFetch(`https://example.test/api/studio/media/${t.id}/c0.mp3`)).status,401);assert.equal((await mf.dispatchFetch(`https://example.test/media/${t.id}/c0.mp3`)).status,404);
 const audio=await call(`/api/studio/media/${t.id}/c0.mp3`,'GET',undefined,'admin',{Range:'bytes=0-31'});assert.equal(audio.status,206);assert.equal(audio.headers.get('Cache-Control'),'private, no-store');assert.equal((await audio.arrayBuffer()).byteLength,32);
 const comparison=await get('/api/studio/compare','POST',{task:t.id,first:fixture.candidates[0].id,second:fixture.candidates[1].id,scope:{kind:'whole'}});
 const inherited=await get('/api/studio/render','POST',{request_id:'inherited-locks',profile_id:'open',parent:{task:t.id,candidate:fixture.candidates[0].id}});const inheritedJob=await get(`/internal/studio/tasks/${inherited.id}/claim`,'POST',{run:'inheritance'},'run');assert.equal(Object.hasOwn(inheritedJob,'locks'),false);
 assert.equal((await call('/api/studio/feedback','POST',{comparison:comparison.id,choice:'A',confirmed:false})).status,400);
 const f=await get('/api/studio/feedback','POST',{comparison:comparison.id,choice:'A',confirmed:true,note:'SIMULATED local integration label'});assert.equal((await get('/api/studio/feedback','POST',{comparison:comparison.id,choice:'B',confirmed:true})).choice,'A');assert.equal(f.origin,'human');assert.equal(f.audio_hashes.length,2);
 const training=await get('/api/studio/train','POST',{request_id:'training-fixture',profile_id:'open'});const job=await get(`/internal/studio/tasks/${training.id}/claim`,'POST',{run:'trainer'},'run');assert.equal(job.feedback.length,1);assert.equal(job.feedback[0].note,'SIMULATED local integration label');
 const py=spawnSync('.venv/bin/python',['-c',"import sys,json;from music.preference import train;j=json.load(sys.stdin);print(json.dumps(train(j['feedback'],j['profile']['id'],j['dataset_revision'])))"],{input:JSON.stringify(job),env:{...process.env,PYTHONPYCACHEPREFIX:'.cache/pycache'},encoding:'utf8'});assert.equal(py.status,0,py.stderr);const model=JSON.parse(py.stdout);assert.equal(model.labels,1);
 const modelBytes=Buffer.from(JSON.stringify(model)),modelFiles=await retain(training.id,{'model.json':modelBytes});await get(`/internal/studio/tasks/${training.id}/ready`,'POST',{run:'trainer',result:{model,files:modelFiles}},'run');
 let state=await get('/api/studio/state');let profile=state.profiles[0];await get('/api/studio/profiles/open','PUT',{revision:profile.revision,model:model.id,daily:true});
 let ranking=await get('/api/studio/ranking/'+t.id);assert.equal(ranking.current_model,model.id);assert.notDeepEqual(ranking.current_ranking.map(r=>r.score),[0,0,0]);
 const evalTask=await get('/api/studio/render','POST',{request_id:'heldout-fixture',profile_id:'open',evaluation:true,source_hashes:[hash]});await get(`/internal/studio/tasks/${evalTask.id}/claim`,'POST',{run:'heldout'},'run');
 const evalFiles=await retain(evalTask.id,{'c0.mp3':files['c0.mp3']});await get(`/internal/studio/tasks/${evalTask.id}/ready`,'POST',{run:'heldout',result:{...fixture,engine_ref:claimed.config.engine_ref,files:evalFiles}},'run');
 const evalComparison=await get('/api/studio/compare','POST',{task:evalTask.id,first:fixture.candidates[0].id,second:fixture.candidates[1].id});
 let evalFeedback=await get('/api/studio/feedback','POST',{comparison:evalComparison.id,choice:'A',confirmed:true});assert.equal(evalFeedback.evaluation,true);
 await get('/api/studio/feedback/'+evalFeedback.id,'PUT',{revision:evalFeedback.revision,choice:'B',confirmed:true});state=await get('/api/studio/state');assert.equal(state.profiles[0].dataset_revision,1);assert.equal(state.profiles[0].active_model,model.id);
 await get('/api/studio/profiles/open','PUT',{revision:state.profiles[0].revision,model:model.id});
 const daily=await get('/api/generate','POST',{day:'2030-01-01'});const dailyJob=await get(`/internal/jobs/${daily.id}/claim`,'POST',{run:'daily-fixture'},'run');assert.equal(dailyJob.preference.model.id,model.id);
 assert.equal((await call('/api/studio/feedback/'+f.id,'PUT',{revision:0,choice:'B',confirmed:true})).status,409);
 await get('/api/studio/feedback/'+f.id,'PUT',{revision:f.revision,choice:'A',confirmed:true,revoked:true});state=await get('/api/studio/state');assert.equal(state.profiles[0].active_model,null);
 assert.equal((await call('/api/studio/profiles/open','PUT',{revision:state.profiles[0].revision,model:model.id})).status,409);await get('/api/studio/profiles/open','PUT',{revision:state.profiles[0].revision,model:model.id,confirm_historical:true});
 for(const choice of ['both','neither','unknown','technical']){const c=await get('/api/studio/compare','POST',{task:t.id,first:fixture.candidates[0].id,second:fixture.candidates[1].id});const f=await get('/api/studio/feedback','POST',{comparison:c.id,choice,confirmed:true});assert.equal(f.choice,choice);}
 state=await get('/api/studio/state');const beforeRules=state.profiles[0];
 const changedProfile=await get('/api/studio/profiles/open','PUT',{revision:beforeRules.revision,rules:{controls:{bit_damage:0},preserve_channels:true}});
 state=await get('/api/studio/state');assert.deepEqual(state.profile_history.find(p=>p.id==='open'&&p.revision===beforeRules.revision).rules,beforeRules.rules);
 assert.equal((await call('/api/studio/profiles/open','PUT',{revision:changedProfile.revision,restore_revision:beforeRules.revision})).status,409);
 const restored=await get('/api/studio/profiles/open','PUT',{revision:changedProfile.revision,restore_revision:beforeRules.revision,confirm_historical:true});assert.deepEqual(restored.rules,beforeRules.rules);assert.equal(restored.active_model,beforeRules.active_model);assert.ok(restored.revision>changedProfile.revision);
 const limited=await get('/api/studio/render','POST',{request_id:'rate-limit-fixture',profile_id:'open',source_hashes:[hash]});await get(`/internal/studio/tasks/${limited.id}/claim`,'POST',{run:'limited'},'run');await get(`/internal/studio/tasks/${limited.id}/failed`,'POST',{run:'limited',reason:'Storage temporarily limited',retry_after:1800},'run');
 state=await get('/api/studio/state');const waiting=state.tasks.find(t=>t.id===limited.id);assert.match(waiting.error,/免费存储/);assert.ok(waiting.retry_after>Date.now()+29*60000);assert.equal(waiting.status,'failed');
 const url=await mf.ready;mkdirSync('.state/qa-studio',{recursive:true});
 for(const [name,type,options]of [['chrome',chromium,{viewport:{width:1440,height:1100}}],['webkit-mobile',webkit,{...devices['iPhone 13']}]]){
   browser=await type.launch({headless:true,...(name==='chrome'?{channel:'chrome'}:{})});const ctx=await browser.newContext({...options,extraHTTPHeaders:{Authorization:'Bearer test-only-admin'}}),page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(new URL('/admin',url).href);await page.locator('#studio-tasks button').filter({hasText:'打开试听'}).last().click();await page.locator('#event-targets .studio-event').first().waitFor();
   await page.locator('#compare-A').evaluate(a=>{a.volume=0;return a.play();});await page.waitForFunction(()=>document.querySelector('#compare-A').currentTime>.15);await page.locator('#compare-A').evaluate(a=>a.pause());
   assert.equal(await page.locator('#event-targets .studio-event').count(),6);assert.equal(await page.locator('#studio-mix').evaluate(a=>a.error),null);
   assert.match(await page.locator('#locked-regions').innerText(),/23.00–24.00/);assert.equal(await page.locator('#event-targets label').filter({hasText:'保留事件'}).locator('input:checked').count(),1);
   await page.locator('#scope-start').fill(name==='chrome'?'1':'3');await page.locator('#scope-end').fill(name==='chrome'?'2':'4');await page.locator('#lock-region').check();await page.locator('#save-locks').click();await page.waitForFunction(()=>document.querySelector('#studio-message').textContent.includes('保留条件已保存'));
   const kept=(await get('/api/studio/state')).locks.find(v=>v.task===t.id&&v.candidate===fixture.candidates[0].id);assert.ok(kept.locks.regions.some(r=>r[0]===23&&r[1]===24));assert.ok(kept.locks.regions.length>=2);
   await page.locator('#event-targets input[type=checkbox]').nth(1).check();await page.screenshot({path:'.state/qa-studio/'+name+'.png',fullPage:true});const width=await page.evaluate(()=>({w:innerWidth,scroll:document.documentElement.scrollWidth}));if(width.scroll>width.w+1)console.log(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1||e.scrollWidth>e.clientWidth+2).map(e=>[e.id,e.tagName,e.clientWidth,e.scrollWidth,e.getBoundingClientRect().right]).slice(0,30)));assert.ok(width.scroll<=width.w+1,JSON.stringify(width));assert.deepEqual(errors,[]);await browser.close();browser=null;
 }
 console.log('PASS: isolated simulated labels; protected private audio/Range, immutable comparisons, task dedup/leases, actual Python training, model-to-daily snapshot, correction/CAS/revocation/rollback, no forced labels, Chrome and WebKit mobile listening interface.');
}finally{if(browser)await browser.close();await mf.dispose();}
