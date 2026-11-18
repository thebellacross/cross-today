import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {plan,localClock,nextDay,validDay,retryable,safeAsset,eligibleForCleanup} from '../worker/src/logic.js';
const cfg=JSON.parse(readFileSync(new URL('../config.json',import.meta.url)));
test('Shanghai preparation, cross-day publication and late catchup',()=>{
  assert.deepEqual(localClock(new Date('2026-11-17T16:01:00Z'),'Asia/Shanghai'),{day:'2026-11-18',hour:0});
  assert.deepEqual(plan(new Date('2026-11-17T13:00:00Z'),cfg,{day:'2026-11-17'},false),[{day:'2026-11-18',publish:false}]);
  assert.deepEqual(plan(new Date('2026-11-17T16:01:00Z'),cfg,{day:'2026-11-17'},false),[{day:'2026-11-18',publish:true}]);
  assert.equal(plan(new Date('2026-11-18T03:00:00Z'),cfg,{day:'2026-11-18'},false).length,0);
  assert.equal(plan(new Date(),cfg,null,true).length,0);
  assert.equal(nextDay('2028-02-28'),'2028-02-29');assert.ok(!validDay('2026-02-30'));assert.ok(!validDay('../../secret'));
});
test('duplicate dispatch and stale lease recovery',()=>{
  const s=cfg.schedule,now=10000;
  assert.ok(!retryable({status:'rendering',attempts:1,lease_until:now+1},now,s));
  assert.ok(retryable({status:'rendering',attempts:1,lease_until:now-1},now,s));
  assert.ok(!retryable({status:'published'},now,s));assert.ok(!retryable({status:'failed',attempts:s.max_attempts},now,s));
  assert.ok(!retryable({status:'failed',attempts:1,retry_after:now+1},now,s));
});
test('cleanup cannot touch current, pinned, final, originals or Selected',()=>{
  const jobs=[1,2,3,4,5].map(n=>({id:'album-'+n,day:'2026-11-'+(10+n),status:'published',final:n===2}));
  const eligible=eligibleForCleanup(jobs,jobs[4],new Set(['album-1']),2);
  assert.deepEqual(eligible.map(x=>x.id),['album-3']);assert.ok(!eligible.some(x=>x.id.startsWith('selected')));
});
test('media proxy asset allowlist rejects private or arbitrary paths',()=>{
  for(const p of ['01.mp3','01.wav','cover.png','album-wav.zip','album-wav-02.zip','score.json'])assert.ok(safeAsset(p));
  for(const p of ['../secrets','originals/a.wav','https://other.example/a.mp3','admin.json','01.mp3?token=secret'])assert.ok(!safeAsset(p));
});
