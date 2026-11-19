// Auth is enforced by index.js before either /api or /internal reaches this module.
const uuid=()=>crypto.randomUUID(), validId=x=>typeof x==='string'&&/^[a-zA-Z0-9_-]{1,80}$/.test(x);
export async function profile(c,name='open') {
  let p=await c.store.get('taste-profile:'+name);
  if(!p&&name==='open'){p={id:'open',name:'开放实验',context:'open',rules:{},revision:0,active_model:null};await c.store.put('taste-profile:open',p);}
  return p;
}
export async function preferenceSnapshot(c) {
  const cfg=await c.config(),p=await profile(c,cfg.preference_profile||'open');
  const model=p?.active_model?await c.store.get('taste-model:'+p.active_model):null;
  return {profile:p,model:model?.model||null};
}
export async function dispatchStudio(c,id,manual=false) {
  let send=false;
  const t=await c.atomic(async()=>{const t=await c.store.get('studio-task:'+id);if(!t||t.status==='ready'||t.lease_until>Date.now())return t;if(!manual&&(t.attempts>=4||t.retry_after>Date.now()))return t;if(manual&&t.status==='failed')t.attempts=0;t.status='queued';t.attempts=(t.attempts||0)+1;t.lease_until=Date.now()+120*60000;await c.store.put('studio-task:'+id,t);send=true;return t;});
  if(send)try{await c.dispatch('studio',id);}catch{await c.atomic(async()=>{const t=await c.store.get('studio-task:'+id);t.status='failed';t.error='后台未能启动，请重试。';t.lease_until=0;t.retry_after=Date.now()+900000;await c.store.put('studio-task:'+id,t);});}
  return await c.store.get('studio-task:'+id);
}
export async function handleStudio(c,request,{json,privateObject,PublicError}) {
  const url=new URL(request.url),path=url.pathname,method=request.method;if(!path.startsWith('/api/studio/')&&!path.startsWith('/internal/studio/'))return null;
  const fail=(message,status=400)=>{throw new PublicError(message,status);};const read=async()=>{const text=await request.text();if(text.length>200000)fail('请求过大。',413);return JSON.parse(text||'{}');};let m;
  const stateTask=t=>{const {config,sources,model,feedback_refs,...safe}=t;return safe;};
  if((m=path.match(/^\/internal\/studio\/task\/([\w-]+)$/))&&method==='GET'){const t=await c.store.get('studio-task:'+m[1]);if(!t)fail('Unknown task',404);return json(t);}
  if(path==='/internal/studio/import'&&method==='POST')return c.atomic(async()=>{
    const b=await read();if(!/^[0-9a-f-]{36}$/.test(b.id))fail('Invalid task identity');const old=await c.store.get('studio-task:'+b.id);if(old)return json(old);
    const p=await profile(c,b.profile_id||'open'),cfg=await c.config();if(b.engine_ref!==cfg.engine_ref)fail('Imported replay engine differs from active engine.',409);
    const t={id:b.id,kind:'render',profile:p,config:cfg,model:null,seed:String(b.seed),created:Date.now(),status:'rendering',attempts:1,run:'local-verified-import',lease_until:Date.now()+120*60000,scope:{kind:'whole'},origin:'locally replayed controlled listening; original audio hashes retained'};
    await c.store.put('studio-task:'+t.id,t);return json(t);
  });
  if(path==='/internal/studio/import-comparison'&&method==='POST')return c.atomic(async()=>{
    const b=await read(),t=await c.store.get('studio-task:'+b.task);if(t?.status!=='ready'||!Array.isArray(b.order)||b.order.length!==2||b.order[0]===b.order[1]||b.order.some(id=>!t.result.candidates.some(c=>c.id===id)))fail('Completed candidates required.');
    const comparison={id:uuid(),task:t.id,profile_id:t.profile.id,model_id:null,model_version:0,family_id:t.result.candidates[0].family_id,order:b.order,scope:b.scope||{kind:'whole'},presentation:'Order preserved from explicit chat audition; not a blind evaluation',created:Date.now()};await c.store.put('taste-comparison:'+comparison.id,comparison);return json(comparison);
  });
  if(path==='/api/studio/state'&&method==='GET'){
    await profile(c);return json({profiles:await c.list('taste-profile:'),models:(await c.list('taste-model:')).map(({model,...v})=>({...v,labels:model.labels,families:model.families,dataset_revision:model.dataset_revision,evaluation:model.evaluation,uncertainty_method:model.uncertainty_method})),tasks:(await c.list('studio-task:')).sort((a,b)=>b.created-a.created).slice(0,50).map(stateTask),locks:await c.list('studio-lock:'),feedback:await c.list('taste-feedback:'),comparisons:await c.list('taste-comparison:'),dataset_revision:await c.store.get('taste-revision')||0,daily_profile:(await c.config()).preference_profile||'open'});
  }
  if((m=path.match(/^\/api\/studio\/ranking\/([\w-]+)$/))&&method==='GET'){
    const t=await c.store.get('studio-task:'+m[1]),p=await profile(c,url.searchParams.get('profile')||'open');if(t?.status!=='ready'||!t.result.candidates)fail('候选尚未就绪。');const saved=p.active_model?await c.store.get('taste-model:'+p.active_model):null,model=saved?.model;
    const rows=t.result.candidates.map(a=>({id:a.id,change:a.changes.action||'parent',score:a.features.reduce((n,x,i)=>n+x*(model?.weights[i]||0),0)})).sort((a,b)=>b.score-a.score);
    return json({frozen_model:t.model?.id||null,frozen_ranking:t.result.decision.ranking,current_model:model?.id||null,current_ranking:rows,labels:model?.labels||0,uncertainty:model&&model.families>=3?'parent-family bootstrap ensemble':'insufficient independent families; not estimated',notice:'Ranking changes verify the software connection; they do not prove better music.'});
  }
  if(path==='/api/studio/profiles'&&method==='POST')return c.atomic(async()=>{const b=await read(),id=uuid();if(!String(b.name||'').trim())fail('请输入档案名称。');const p={id,name:String(b.name).slice(0,80),context:String(b.context||b.name).slice(0,300),rules:{},revision:0,active_model:null};await c.store.put('taste-profile:'+id,p);return json(p);});
  if((m=path.match(/^\/api\/studio\/profiles\/([\w-]+)$/))&&method==='PUT')return c.atomic(async()=>{
    const b=await read(),p=await profile(c,m[1]);if(!p)fail('档案不存在。',404);if(b.revision!==p.revision)fail('档案已在另一窗口修改，请刷新。',409);
    if(b.model!==undefined){const model=b.model&&await c.store.get('taste-model:'+b.model);if(b.model&&model?.profile_id!==p.id)fail('模型不属于此档案。');if(model&&model.model.dataset_revision!==(await c.store.get('taste-revision')||0)&&!b.confirm_historical)fail('这是旧反馈版本。请确认回退，或重新训练。',409);p.active_model=b.model||null;}
    if(b.rules!==undefined){const rules=b.rules;if(!rules||typeof rules!=='object'||Array.isArray(rules))fail('规则格式错误。');const keys=['structure_randomness','processing_intensity','bit_damage','bus_intervention','loop_activity','space_motion','dropout_probability','stereo_width'];if(Object.keys(rules).some(k=>!['controls','preserve_channels','max_events'].includes(k)))fail('未知规则。');if(rules.controls&&Object.entries(rules.controls).some(([k,v])=>!keys.includes(k)||!Number.isFinite(v)||v<0||v>1))fail('控制值必须在 0–1 之间。');if(rules.max_events!==undefined&&(!Number.isInteger(rules.max_events)||rules.max_events<2||rules.max_events>100))fail('事件上限范围为 2–100。');p.rules=rules;}
    await c.store.put(`taste-profile-history:${p.id}:${p.revision}`,await profile(c,p.id));p.revision++;await c.store.put('taste-profile:'+p.id,p);
    if(b.daily===true){const cfg=await c.config();cfg.preference_profile=p.id;await c.store.put('config',cfg);await c.store.put('config-revision',(await c.store.get('config-revision')||0)+1);}return json(p);
  });
  if((path==='/api/studio/render'||path==='/api/studio/train')&&method==='POST'){
    const b=await read();if(!validId(b.request_id))fail('缺少请求去重标识。');const key='studio-request:'+b.request_id;
    const task=await c.atomic(async()=>{const old=await c.store.get(key);if(old)return c.store.get('studio-task:'+old);const p=await profile(c,b.profile_id||'open');if(!p)fail('档案不存在。');const cfg=await c.config();if(cfg.generation.renderer!=='composition')fail('请先完成引擎升级。',409);
      let t={id:uuid(),kind:path.endsWith('/train')?'train':'render',evaluation:!!b.evaluation,profile:p,config:cfg,model:p.active_model?(await c.store.get('taste-model:'+p.active_model))?.model:null,seed:String(BigInt('0x'+uuid().replaceAll('-','').slice(0,15))),created:Date.now(),status:'queued',attempts:0,lease_until:0};
      if(t.kind==='train'){const feedback=(await c.list('taste-feedback:')).filter(f=>f.profile_id===p.id&&!f.evaluation);t.feedback_refs=feedback.map(f=>[f.id,f.revision]);t.dataset_revision=await c.store.get('taste-revision')||0;}
      else {
        t.seconds=Number(b.seconds||36);if(t.seconds<8||t.seconds>120)fail('试听段落长度为 8–120 秒。');t.actions=b.actions||null;if(t.actions&&(!Array.isArray(t.actions)||t.actions.length>12||t.actions.some(x=>!['delay-entry','earlier-entry','continue','withdraw','depth','space','processing','replace-material','repeat','return-later','swap-sections'].includes(x))))fail('未知变体动作。');
        t.locks=b.locks||{events:[],regions:[],relations:[]};if(!Array.isArray(t.locks.events)||!Array.isArray(t.locks.regions)||!Array.isArray(t.locks.relations)||JSON.stringify(t.locks).length>12000||t.locks.regions.some(x=>!Array.isArray(x)||x.length!==2||!x.every(Number.isFinite)||x[0]<0||x[1]<=x[0]))fail('锁定范围无效。');
        t.targets=Array.isArray(b.targets)?b.targets.map(String).slice(0,100):null;t.scope=b.scope||{kind:'whole'};t.intent=String(b.intent||'').slice(0,2000);t.intent_is_label=false;
        if(b.parent&&t.evaluation)fail('盲听评估从新的未训练素材开始。');if(b.parent){const parent=await c.store.get('studio-task:'+b.parent.task);const candidate=parent?.result?.candidates?.find(x=>x.id===b.parent.candidate);if(parent?.status!=='ready'||!candidate)fail('父计划尚未就绪。');if(parent.config.engine_ref!==cfg.engine_ref)fail('此计划使用另一冻结引擎。请先切回同版本，避免声称跨版本精确比较。',409);t.parent={task:parent.id,prefix:candidate.prefix,candidate:candidate.id};}
        else {const available=(await c.list('source:')).filter(s=>s.enabled&&s.status!=='invalid');if(b.source_hashes&&(!Array.isArray(b.source_hashes)||b.source_hashes.some(h=>!available.some(s=>s.hash===h))))fail('素材选择无效。');t.sources=available.filter(s=>!b.source_hashes?.length||b.source_hashes.includes(s.hash)).sort((a,b)=>a.hash.localeCompare(b.hash)).map(({hash,name,tags,extension,bytes})=>({hash,name,tags,extension,bytes}));if(!t.sources.length)fail('需要至少一个有效素材。');if(t.evaluation){const trainingFeedback=(await c.list('taste-feedback:')).filter(f=>f.profile_id===p.id&&!f.evaluation&&!f.revoked&&['A','B'].includes(f.choice));const trainingTasks=await Promise.all(trainingFeedback.map(f=>c.store.get('studio-task:'+f.task)));const used=new Set(trainingTasks.flatMap(t=>t?.result?.source_hashes||[]));if(t.sources.some(s=>used.has(s.hash)))fail('评估素材与本档案的训练素材重复。请只选未参与训练的材料。');}}
      }
      await c.store.put('studio-task:'+t.id,t);await c.store.put(key,t.id);return t;});return json(stateTask(await dispatchStudio(c,task.id,true)));
  }
  if((m=path.match(/^\/api\/studio\/tasks\/([\w-]+)\/retry$/))&&method==='POST')return json(stateTask(await dispatchStudio(c,m[1],true)));
  if((m=path.match(/^\/api\/studio\/media\/([\w-]+)\/([a-z0-9.-]+)$/))&&['GET','HEAD'].includes(method)){
    const t=await c.store.get('studio-task:'+m[1]);if(t?.status!=='ready'||!t.result?.files?.[m[2]])fail('文件尚未准备好。',404);return privateObject(c.permanent,`lab/${t.id}/${m[2]}`,request,m[2]);
  }
  if(path==='/api/studio/locks'&&method==='PUT')return c.atomic(async()=>{
    const b=await read(),t=await c.store.get('studio-task:'+b.task);if(t?.status!=='ready'||!t.result.candidates.some(c=>c.id===b.candidate))fail('候选不存在。');const key='studio-lock:'+b.task+':'+b.candidate,old=await c.store.get(key)||{revision:0};if(old.revision!==b.revision)fail('锁定条件已改变，请刷新。',409);
    if(!b.locks||!Array.isArray(b.locks.events)||!Array.isArray(b.locks.regions)||!Array.isArray(b.locks.relations)||JSON.stringify(b.locks).length>12000)fail('锁定格式无效。');const saved={task:b.task,candidate:b.candidate,revision:old.revision+1,locks:b.locks};await c.store.put(key,saved);return json(saved);
  });
  if(path==='/api/studio/compare'&&method==='POST')return c.atomic(async()=>{const b=await read(),t=await c.store.get('studio-task:'+b.task);const candidates=t?.result?.candidates;const a=candidates?.find(x=>x.id===b.first),d=candidates?.find(x=>x.id===b.second);if(t?.status!=='ready'||!a||!d||a.id===d.id)fail('请选择两个已完成候选。');const order=crypto.getRandomValues(new Uint32Array(1))[0]%2?[a,d]:[d,a];const comparison={id:uuid(),task:t.id,profile_id:t.profile.id,evaluation:t.evaluation||false,model_id:t.model?.id||null,model_version:t.model?.dataset_revision||0,family_id:a.family_id,order:order.map(x=>x.id),scope:b.scope||t.scope,created:Date.now()};await c.store.put('taste-comparison:'+comparison.id,comparison);return json(comparison);});
  if((path==='/api/studio/feedback'||(m=path.match(/^\/api\/studio\/feedback\/([\w-]+)$/)))&&['POST','PUT'].includes(method))return c.atomic(async()=>{
    const b=await read(),comparison=await c.store.get('taste-comparison:'+(m?m[1]:b.comparison));if(!comparison)fail('比较不存在。');const old=await c.store.get('taste-feedback:'+comparison.id);
    if(method==='POST'&&old)return json(old);if(method==='PUT'&&(!old||b.revision!==old.revision))fail('反馈版本已改变，请刷新。',409);
    if(b.scope){if(!['whole','section','range','event','relationship'].includes(b.scope.kind))fail('反馈范围无效。');if(['event','relationship'].includes(b.scope.kind)&&!b.scope.events?.length)fail('请选择反馈对应的事件。');if(['range','section'].includes(b.scope.kind)&&!(Number.isFinite(b.scope.start)&&Number.isFinite(b.scope.end)&&b.scope.end>b.scope.start&&b.scope.start>=0))fail('反馈时间范围无效。');}if(b.confirmed!==true)fail('需要明确确认这条听后反馈。');if(!['A','B','both','neither','unknown','technical'].includes(b.choice))fail('选择无效。');
    const t=await c.store.get('studio-task:'+comparison.task),[a,d]=comparison.order.map(id=>t.result.candidates.find(x=>x.id===id));
    const f={...comparison,id:comparison.id,origin:'human',scope:b.scope||comparison.scope,choice:b.choice,revoked:!!b.revoked,revision:(old?.revision||0)+1,note:String(b.note||'').slice(0,4000),confirmed:true,features_A:a.features,features_B:d.features,audio_hashes:[a.audio_hash,d.audio_hash],audition_hashes:[a.audition_hash,d.audition_hash],audition_gains:[a.audition_gain,d.audition_gain],source_snapshots:[a.snapshot,d.snapshot],parent_plans:[a.parent_id,d.parent_id],changes:[a.changes,d.changes],engine_ref:t.config.engine_ref,updated:Date.now()};
    await c.store.put(`taste-feedback-history:${f.id}:${f.revision}`,f);await c.store.put('taste-feedback:'+f.id,f);await c.store.put('taste-revision',(await c.store.get('taste-revision')||0)+1);if(old){const p=await profile(c,f.profile_id);if(p.active_model){await c.store.put(`taste-profile-history:${p.id}:${p.revision}`,p);p.active_model=null;p.revision++;p.invalidated_by_feedback=f.id;await c.store.put('taste-profile:'+p.id,p);}}return json(f);
  });
  if((m=path.match(/^\/internal\/studio\/tasks\/([\w-]+)\/(claim|ready|failed)$/))&&method==='POST'){
    const b=await read(),id=m[1],action=m[2];
    if(action==='ready'){
      const t=await c.store.get('studio-task:'+id);if(!t||b.run!==t.run)fail('任务租约不匹配。',409);if(!b.result?.files||!Object.keys(b.result.files).length)fail('资产清单缺失。');
      for(const [name,meta]of Object.entries(b.result.files)){if(!/^[a-z0-9.-]+$/.test(name))fail('文件名无效。');const head=await c.permanent.head(`lab/${id}/${name}`);if(!head||head.sha256!==meta.sha256||head.size!==meta.bytes)fail('私有文件校验未完成。',409);}
    }
    return c.atomic(async()=>{const t=await c.store.get('studio-task:'+id);if(!t)fail('任务不存在。',404);if(action==='claim'){
      if(t.status==='ready')return json({done:true});if(t.status==='rendering'&&t.lease_until>Date.now()&&t.run!==b.run)fail('已有后台任务执行中。',409);t.run=b.run;t.status='rendering';t.lease_until=Date.now()+120*60000;await c.store.put('studio-task:'+id,t);
      if(t.kind==='train')t.feedback=await Promise.all(t.feedback_refs.map(([id,revision])=>c.store.get(`taste-feedback-history:${id}:${revision}`)));return json(t);
    }
    if(t.run!==b.run)fail('任务租约不匹配。',409);if(t.status==='ready')return json({ok:true});t.lease_until=0;
    if(action==='failed'){t.status='failed';t.error=b.reason==='Cross-runtime replay mismatch'?'父计划跨运行环境重放未通过字节校验，已停止受控比较。请从同一批素材建立新的云端父计划；旧音频仍保留。':b.reason==='No audible sample difference'?'参数改变后音频没有发生有效差异。请选择另一个事件或决定；没有创建偏好标签。':b.reason==='No allowed variation'?'锁定条件阻止了所有变体。请选择未锁定事件，或调整允许变化的范围。':'试听或训练未完成；原计划、反馈与公开专辑未改变。可保留输入重试。';t.retry_after=Date.now()+900000;}
    else {t.status='ready';t.completed=Date.now();t.result=b.result;delete t.error;if(t.kind==='train'){const model=b.result.model;if(model?.label_origin!=='human'||model.profile_id!==t.profile.id||model.dataset_revision!==t.dataset_revision||!Array.isArray(model.weights)||model.weights.some(x=>!Number.isFinite(x)))fail('模型版本或标签来源不一致。');await c.store.put('taste-model:'+model.id,{id:model.id,task:t.id,profile_id:t.profile.id,created:Date.now(),model});}}
    await c.store.put('studio-task:'+id,t);return json({ok:true});});
  }
  return json({error:'Not found'},404);
}
