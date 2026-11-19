import {test} from 'node:test';import assert from 'node:assert/strict';
import {GitHubBucket} from '../worker/src/storage.js';import {githubFixture} from './github-fixture.mjs';
test('a historical private derived version remains retrievable by full hash',async()=>{
 const fixture=githubFixture(),saved=new Map();const store={get:async k=>saved.get(k),put:async(k,v)=>saved.set(k,v),transaction:async f=>f(store)};
 const c={env:{STORAGE_REPOSITORY:'thebellacross/private-fixture',GITHUB_REPOSITORY:'thebellacross/cross-today',GITHUB_TOKEN:'test-only-github'},store};const original=globalThis.fetch;globalThis.fetch=(input,options)=>fixture.fetch(new Request(input,options));
 try{const bucket=new GitHubBucket(c,'sources'),key='derived/test/clip.wav';const first=new Uint8Array([1,3,5,7]),second=new Uint8Array([2,4,6,8]);await bucket.put(key,first);const old=await bucket.head(key);await bucket.put(key,second);const latest=await bucket.head(key);assert.notEqual(old.sha256,latest.sha256);const historical=await bucket.version(key,old.sha256);const result=await historical.get(key,{});assert.deepEqual(new Uint8Array(await new Response(result.body).arrayBuffer()),first);assert.equal((await bucket.head(key)).sha256,latest.sha256);assert.equal((await historical.head(key)).sha256,old.sha256);}finally{globalThis.fetch=original;}
});
