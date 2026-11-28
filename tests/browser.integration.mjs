import {chromium,webkit,devices} from 'playwright';
import {mkdirSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const target=process.env.TEST_SITE||'http://127.0.0.1:8765/';
const out=process.env.TEST_OUTPUT||'.state/qa';mkdirSync(out,{recursive:true});const results=[];
let proxy;const proxyUrl=process.env.TEST_PROXY||process.env.HTTPS_PROXY||process.env.https_proxy;
if(!target.includes('127.0.0.1')&&proxyUrl){const u=new URL(proxyUrl);proxy={server:u.origin};if(u.username)proxy.username=decodeURIComponent(u.username);if(u.password)proxy.password=decodeURIComponent(u.password);}
for(const [name,type,options,context]of [
  ['chrome-desktop',chromium,{channel:'chrome'},{viewport:{width:1440,height:800}}],
  ['webkit-desktop',webkit,{}, {viewport:{width:1440,height:800}}],
  ['webkit-mobile',webkit,{}, {...devices['iPhone 13']}]
]){
  let browser;const errors=[];
  try{
    browser=await type.launch({headless:true,proxy,...options});const c=await browser.newContext(context),page=await c.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(target,{waitUntil:'domcontentloaded',timeout:60000});await page.locator('#play:not([disabled])').waitFor({timeout:60000});
    await page.waitForFunction(()=>document.querySelector('#grooves').dataset.ready==='true'&&document.querySelector('#hub').naturalWidth>0);
    await page.locator('.disco-item img').first().waitFor();
    const dimensions=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,site:document.querySelector('.site').getBoundingClientRect().width,record:document.querySelector('#record').getBoundingClientRect().width,tracks:document.querySelectorAll('#tracks li').length,artist:document.querySelector('.artist h2').textContent}));
    assert.ok(dimensions.width<=dimensions.viewport+1,JSON.stringify(dimensions));assert.equal(dimensions.artist,'CROSS');assert.ok(dimensions.tracks>=3);
    assert.equal(dimensions.site,dimensions.viewport);assert.equal(dimensions.record,dimensions.viewport);
    assert.deepEqual(await page.locator('nav a').allTextContents(),['Music','Bandcamp']);assert.equal(await page.locator('a[download],#downloads,a[href*="score.html"],a[href*="catalog.html"]').count(),0);
    assert.equal(await page.locator('#admin-link,a[href*="/admin"]').count(),0);assert.equal(await page.locator('.edition-notes').evaluate(e=>e.tagName),'SECTION');
    await page.locator('#scores details').first().waitFor();assert.equal(await page.locator('#scores details').count(),dimensions.tracks);assert.equal(await page.locator('#scores details[open]').count(),0);await page.locator('#scores summary').first().click();assert.equal(await page.locator('#scores details[open]').count(),1);await page.locator('#scores summary').first().click();await page.evaluate(()=>scrollTo(0,0));
    const picker=await page.locator('#tracks').evaluate(list=>{const r=list.getBoundingClientRect(),current=list.querySelector('.current').getBoundingClientRect();return {height:r.height,visible:[...list.children].filter(row=>{const x=row.getBoundingClientRect();return Math.min(x.bottom,r.bottom)-Math.max(x.top,r.top)>10;}).length,centred:Math.abs(current.top+current.height/2-r.top-r.height/2)<2};});assert.equal(picker.height,112);assert.ok(picker.visible>=2&&picker.visible<=5);assert.ok(picker.centred);assert.equal(await page.locator('.byline').count(),0);
    const artistTop=await page.locator('.artist-profile').evaluate(e=>e.getBoundingClientRect().top);assert.ok(artistTop<await page.evaluate(()=>innerHeight));
    const order=await page.evaluate(()=>['.album-intro','#record','.listening-strip','.track-list','.artist-profile','.discography-section'].map(s=>document.querySelector(s).getBoundingClientRect().top));assert.deepEqual(order,[...order].sort((a,b)=>a-b));
    const profile=await page.locator('.artist .photo').boundingBox();assert.ok(Math.abs(profile.x+profile.width/2-dimensions.viewport/2)<1);
    const navStyle=await page.locator('nav a').first().evaluate(e=>{const s=getComputedStyle(e);return [s.borderTopWidth,s.borderBottomWidth]});assert.deepEqual(navStyle,['0px','0px']);
    const bandcamp=await page.locator('.disco-item').evaluateAll(a=>a.map(e=>e.href));assert.equal(bandcamp.length,4);assert.ok(bandcamp.every(url=>url.startsWith('https://bellacrossmusic.bandcamp.com/album/')));
    await page.locator('#discography').scrollIntoViewIfNeeded();await page.waitForFunction(()=>[...document.querySelectorAll('.disco-item img')].every(e=>e.complete&&e.naturalWidth));await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:`${out}/${name}.png`,fullPage:true});
    await page.locator('#audio').evaluate(a=>a.volume=0);
    await page.locator('#play').click();await page.waitForFunction(()=>!document.querySelector('#audio').paused&&document.querySelector('#audio').currentTime>.2,{},{timeout:45000});
    await page.locator('#hearing:not([hidden])').waitFor();assert.ok((await page.locator('#heard').innerText()).length);
    const a=await page.locator('#grooves').evaluate(e=>e.style.transform);await page.waitForTimeout(450);const b=await page.locator('#grooves').evaluate(e=>e.style.transform);assert.notEqual(a,b);
    await page.locator('#play').click();await page.waitForFunction(()=>document.querySelector('#audio').paused);await page.waitForTimeout(100);const paused=await page.locator('#audio').evaluate(a=>a.currentTime);const pausedTransform=await page.locator('#grooves').evaluate(e=>e.style.transform);await page.waitForTimeout(350);assert.equal(await page.locator('#grooves').evaluate(e=>e.style.transform),pausedTransform);assert.ok(Math.abs((await page.locator('#audio').evaluate(a=>a.currentTime))-paused)<.08);
    const seek=await page.locator('#seek').boundingBox();await page.mouse.click(seek.x+seek.width*.6,seek.y+seek.height/2);await page.waitForFunction(()=>{const a=document.querySelector('#audio');return a.currentTime>a.duration*.4;});
    await page.locator('.track-name').nth(1).click();await page.waitForFunction(()=>!document.querySelector('#audio').paused&&location.hash==='#2');
    await page.waitForFunction(()=>document.querySelector('#audio').currentTime>.1);await page.locator('#audio').evaluate(a=>a.currentTime=20);await page.waitForFunction(()=>document.querySelector('#audio').currentTime>=20&&!document.querySelector('#audio').seeking);await page.locator('#record').scrollIntoViewIfNeeded();const r=await page.locator('#record').boundingBox();const before=await page.locator('#audio').evaluate(a=>a.currentTime);await page.mouse.move(r.x+r.width*.2,r.y+r.height*.5);await page.mouse.down();await page.locator('#record[data-scratching=active]').waitFor();assert.equal(await page.locator('#play').getAttribute('aria-label'),'Pause');const tilt=await page.locator('#record').evaluate(e=>Number(getComputedStyle(e).getPropertyValue('--disc-projection')));await page.mouse.move(r.x+r.width*.3,r.y+r.height*.5-r.width*tilt*.18,{steps:8});await page.mouse.up();await page.waitForFunction(()=>!document.querySelector('#audio').paused);
    const after=await page.locator('#audio').evaluate(a=>a.currentTime);assert.ok(after>19&&after<21,JSON.stringify({before,after,track:await page.locator('#track-title').textContent()}));
    await page.locator('#enlarge').click();await page.locator('#zoom[open]').waitFor();assert.equal(await page.locator('#record').evaluate(e=>e.parentElement.id),'zoom-slot');await page.locator('#close-zoom').click();assert.equal(await page.locator('#record').evaluate(e=>e.parentElement.id),'record-wrap');
    await page.locator('#share').click();await page.locator('#share-dialog[open]').waitFor();assert.match(await page.locator('#embed-code').inputValue(),/title="CROSS record"/);assert.ok((await page.locator('#share-url').inputValue()).startsWith(target.split('?')[0]));await page.locator('.close-dialog').click();
    await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.querySelector('#grooves').style.transform==='none');
    if(name.includes('mobile')){await page.locator('.artist').scrollIntoViewIfNeeded();await page.locator('#sticky:not([hidden])').waitFor();await page.locator('#sticky-play').click();await page.waitForFunction(()=>document.querySelector('#audio').paused);}
    else await page.locator('#audio').evaluate(a=>a.pause());
    const range=await page.evaluate(async()=>{const r=await fetch(document.querySelector('#audio').src,{headers:{Range:'bytes=0-1023'},signal:AbortSignal.timeout(20000)});const bytes=(await r.arrayBuffer()).byteLength;return {status:r.status,type:r.headers.get('Content-Type'),bytes};});assert.equal(range.status,206);assert.match(range.type,/audio\//);assert.equal(range.bytes,1024);
    assert.deepEqual(errors,[]);results.push({browser:name,status:'passed',...dimensions,picker,checks:['play/pause','audio-synchronised rotation','seek','track change','record drag','zoom','share','reduced motion','Bandcamp destinations','elliptical hit testing','centred profile and new content order','no download/score/catalogue entry','Range 206','compact scrolling tracks and artist visible','complete score collapsed until opened','expanded edition notes','no public management link']});
  }catch(e){results.push({browser:name,status:'failed',error:e.message,pageErrors:errors});}
  finally{if(browser)await browser.close();}
  console.log(JSON.stringify(results.at(-1)));
}
writeFileSync(`${out}/browser-results.json`,JSON.stringify({target,results},null,2));if(results.some(r=>r.status!=='passed'))process.exitCode=1;
