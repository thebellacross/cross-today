import {chromium,webkit,devices} from 'playwright';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
const target=process.env.TEST_SITE||'http://127.0.0.1:8768/';
const out=process.env.TEST_OUTPUT||'.state/fast-record-qa';mkdirSync(out,{recursive:true});
let proxy;const raw=process.env.TEST_PROXY||process.env.HTTPS_PROXY||process.env.https_proxy;
if(raw){const u=new URL(raw);proxy={server:u.origin,bypass:'127.0.0.1,localhost'};if(u.username)proxy.username=decodeURIComponent(u.username);if(u.password)proxy.password=decodeURIComponent(u.password);}
const results=[];
for(const [name,type,launch,context]of [
 ['chrome-desktop',chromium,{channel:'chrome'},{viewport:{width:1512,height:850}}],
 ['webkit-desktop',webkit,{}, {viewport:{width:1440,height:800}}],
 ['webkit-mobile',webkit,{}, {...devices['iPhone 13'],deviceScaleFactor:1}]
]){
 if(process.env.TEST_BROWSER&&process.env.TEST_BROWSER!==name)continue;
 const browser=await type.launch({headless:true,proxy,...launch});const errors=[],covers=[];let phase='startup',page;
 try{
  page=await browser.newPage(context);page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(new URL(r.url()).pathname.endsWith('/cover.png'))covers.push(r.url());});
  // The important image must not depend on album/configuration requests finishing.
  let releaseConfiguration;const configurationGate=new Promise(resolve=>releaseConfiguration=resolve);
  await page.route('**/public-config.json',async route=>{await configurationGate;await route.continue();});
  await page.goto(target,{waitUntil:'commit',timeout:60000});
  phase='early artwork';await page.waitForFunction(()=>{const i=document.querySelector('#grooves');return i?.dataset.previewId&&i.complete&&i.naturalWidth===1600;},{},{timeout:30000});
  assert.equal(await page.locator('#play').isDisabled(),true);
  const firstImageAt=await page.evaluate(()=>performance.now());
  releaseConfiguration();phase='prepared artwork';await page.locator('#grooves[data-ready=true]').waitFor({timeout:60000});
  assert.equal(await page.locator('#grooves').getAttribute('data-render-path'),'prepared');assert.equal(covers.length,0);
  await page.locator('#scores details').first().waitFor({timeout:60000});
  const layout=await page.evaluate(()=>({viewport:[innerWidth,innerHeight],artistBottom:document.querySelector('.artist-profile').getBoundingClientRect().bottom,discographyTop:document.querySelector('.discography-section').getBoundingClientRect().top,overflow:document.documentElement.scrollWidth>innerWidth}));
  assert.equal(layout.overflow,false);assert.ok(layout.artistBottom<=layout.viewport[1]+1,JSON.stringify(layout));
  if(!name.includes('mobile'))assert.ok(layout.discographyTop<layout.viewport[1],JSON.stringify(layout));
  const initial=await page.locator('#audio').evaluate(a=>a.src);
  phase='browse';const list=await page.locator('#tracks').boundingBox();
  if(name.includes('mobile'))await page.locator('#tracks').evaluate(e=>e.scrollBy({top:100,behavior:'auto'}));
  else{await page.mouse.move(list.x+list.width/2,list.y+list.height/2);await page.mouse.wheel(0,100);}
  await page.waitForTimeout(250);
  assert.ok(await page.locator('#tracks').evaluate(e=>e.scrollTop)>0);assert.equal(await page.locator('#audio').evaluate(a=>a.src),initial);assert.equal(await page.locator('#audio').evaluate(a=>a.paused),true);
  await page.locator('#audio').evaluate(a=>a.volume=0);await page.locator('.track-name').nth(2).click();
  phase='third track playback';await page.waitForFunction(()=>location.hash==='#3'&&!document.querySelector('#audio').paused,{},{timeout:45000});
  phase='third track centring';
  await page.waitForFunction(()=>{const l=document.querySelector('#tracks').getBoundingClientRect(),r=document.querySelector('#tracks .current').getBoundingClientRect();return Math.abs(r.top+r.height/2-l.top-l.height/2)<2;},{},{timeout:4000});
  await page.locator('#play').click();
  assert.equal(await page.locator('#tracks li[aria-current=true]').count(),1);
  await page.locator('#tracks').focus();await page.keyboard.press('End');
  assert.equal(await page.locator('#audio').evaluate(a=>a.paused),true);assert.equal(await page.evaluate(()=>location.hash),'#3');
  phase='keyboard selection';await page.keyboard.press('Enter');await page.waitForFunction(()=>{const list=document.querySelector('#tracks');return list.lastElementChild.classList.contains('current')&&!document.querySelector('#audio').paused;});
  await page.locator('#play').click();
  phase='return to third';await page.locator('.track-name').nth(2).click();await page.waitForFunction(()=>location.hash==='#3'&&!document.querySelector('#audio').paused);await page.locator('#play').click();
  await page.waitForTimeout(300);await page.locator('#tracks').evaluate(e=>e.blur());
  await page.screenshot({path:`${out}/${name}-viewport.png`});
  assert.deepEqual(errors,[]);assert.equal(await page.locator('#status').isVisible(),false);
  results.push({browser:name,status:'passed',firstImageAt,...layout,fullCoverRequests:covers.length,checks:['sharp record visible with configuration blocked','prepared artwork used without downloading full cover','list browsing does not change audio','selected track centres','keyboard browsing does not autoplay','keyboard activation selects last track','artist and discography visible in first viewport','no false playback error after track changes']});
 }catch(e){const diagnostic=await page?.evaluate(()=>{const l=document.querySelector('#tracks'),r=l?.querySelector('.current');return {list:l?.getBoundingClientRect().toJSON(),row:r?.getBoundingClientRect().toJSON(),scroll:l?.scrollTop,offset:r?.offsetTop,focus:document.activeElement?.textContent};});await page?.screenshot({path:`${out}/${name}-failure.png`});results.push({browser:name,status:'failed',phase,error:e.message,diagnostic,pageErrors:errors});}
 finally{await browser.close();}
 console.log(JSON.stringify(results.at(-1)));
}
writeFileSync(`${out}/record-loading-results.json`,JSON.stringify({target,results},null,2));if(results.some(r=>r.status!=='passed'))process.exitCode=1;
