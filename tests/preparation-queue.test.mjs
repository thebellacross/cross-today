import test from 'node:test';
import assert from 'node:assert/strict';
import {queuePreparation} from '../worker/src/studio.js';

test('preparation is incremental, batched, persistent and deduplicated',async()=>{
 const cfg={import:{channels:'preserve',preparation:{mode:'remove-digital-silence',minimum_gap_seconds:1,padding_seconds:.01}},engine_ref:'fixture'};
 const data=new Map();let dispatches=0;
 const c={store:{get:async k=>data.get(k),put:async(k,v)=>data.set(k,v)},atomic:fn=>fn(),config:async()=>structuredClone(cfg),list:async p=>[...data].filter(([k])=>k.startsWith(p)).map(([,v])=>v),dispatch:async()=>dispatches++};
 for(let n=0;n<10;n++)data.set('source:'+n,{hash:String(n),name:'Recording '+n+'.wav',enabled:true,status:'ready'});
 const first=await queuePreparation(c),again=await queuePreparation(c);assert.equal(first.id,again.id);assert.equal(first.sources.length,8);assert.equal(dispatches,1);
 for(const source of first.sources){const row=data.get('source:'+source.hash);row.preparation_settings={preparation:{padding_seconds:.01,minimum_gap_seconds:1,mode:'remove-digital-silence'},channels:'preserve'};}
 data.get('studio-task:'+first.id).status='ready';const next=await queuePreparation(c);assert.equal(next.sources.length,2);assert.equal(dispatches,2);
 for(const source of next.sources)data.get('source:'+source.hash).preparation_settings=structuredClone(cfg.import);
 data.get('studio-task:'+next.id).status='ready';assert.equal(await queuePreparation(c),null);
 cfg.import.preparation.minimum_gap_seconds=2;const revised=await queuePreparation(c);assert.equal(revised.sources.length,8);assert.notEqual(revised.id,first.id);
});
