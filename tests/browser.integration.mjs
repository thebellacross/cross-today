import {chromium,webkit,devices} from 'playwright';
import {mkdirSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const target=process.env.TEST_SITE||'http://127.0.0.1:8765/';
const out='.state/qa';mkdirSync(out,{recursive:true});const results=[];
let proxy;
if(!target.includes('127.0.0.1')&&process.env.HTTPS_PROXY){const u=new URL(process.env.HTTPS_PROXY);proxy={server:u.origin};if(u.username)proxy.username=decodeURIComponent(u.username);if(u.password)proxy.password=decodeURIComponent(u.password);}
for(const [name,type,options,context]of [
  ['chrome-desktop',chromium,{channel:'chrome'},{viewport:{width:1440,height:1100}}],
  ['webkit-desktop',webkit,{}, {viewport:{width:1440,height:1100}}],
  ['webkit-mobile',webkit,{}, {...devices['iPhone 13']}]
]){
  let browser;const errors=[];
  try{
    browser=await type.launch({headless:true,proxy,...options});const c=await browser.newContext(context),page=await c.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(target,{waitUntil:'domcontentloaded',timeout:60000});await page.locator('#play:not([disabled])').waitFor({timeout:60000});
    await page.waitForFunction(()=>document.querySelector('#grooves').complete&&document.querySelector('#grooves').naturalWidth>0);
    await page.locator('.disco-item img').first().waitFor();
    const dimensions=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,site:document.querySelector('.site').getBoundingClientRect().width,record:document.querySelector('#record').getBoundingClientRect().width,tracks:document.querySelectorAll('#tracks li').length,artist:document.querySelector('.artist h2').textContent}));
    assert.ok(dimensions.width<=dimensions.viewport+1,JSON.stringify(dimensions));assert.equal(dimensions.artist,'CROSS');assert.ok(dimensions.tracks>=3);
    if(!name.includes('mobile')){assert.equal(dimensions.site,975);assert.equal(dimensions.record,350);}
    const bandcamp=await page.locator('.disco-item').evaluateAll(a=>a.map(e=>e.href));assert.equal(bandcamp.length,4);assert.ok(bandcamp.every(url=>url.startsWith('https://bellacrossmusic.bandcamp.com/album/')));
    await page.screenshot({path:`${out}/${name}.png`,fullPage:true});
    await page.locator('#audio').evaluate(a=>a.volume=0);
    await page.locator('#play').click();await page.waitForFunction(()=>!document.querySelector('#audio').paused&&document.querySelector('#audio').currentTime>.2,{},{timeout:45000});
    await page.locator('#hearing:not([hidden])').waitFor();assert.ok((await page.locator('#heard').innerText()).length);
    const a=await page.locator('#grooves').evaluate(e=>e.style.transform);await page.waitForTimeout(450);const b=await page.locator('#grooves').evaluate(e=>e.style.transform);assert.notEqual(a,b);
    await page.locator('#play').click();const paused=await page.locator('#audio').evaluate(a=>a.currentTime);await page.waitForTimeout(350);assert.ok(Math.abs((await page.locator('#audio').evaluate(a=>a.currentTime))-paused)<.08);
    const seek=await page.locator('#seek').boundingBox();await page.mouse.click(seek.x+seek.width*.6,seek.y+seek.height/2);await page.waitForFunction(()=>{const a=document.querySelector('#audio');return a.currentTime>a.duration*.4;});
    await page.locator('.track-name').nth(1).click();await page.waitForFunction(()=>!document.querySelector('#audio').paused&&location.hash==='#2');
    await page.locator('#record').scrollIntoViewIfNeeded();const r=await page.locator('#record').boundingBox();const before=await page.locator('#audio').evaluate(a=>a.currentTime);await page.mouse.move(r.x+r.width*.2,r.y+r.height*.5);await page.mouse.down();await page.mouse.move(r.x+r.width*.3,r.y+r.height*.2,{steps:8});await page.mouse.up();await page.waitForFunction(()=>!document.querySelector('#audio').paused);
    const after=await page.locator('#audio').evaluate(a=>a.currentTime);assert.ok(Math.abs(after-before)>.1);
    await page.locator('#enlarge').click();await page.locator('#zoom[open]').waitFor();assert.equal(await page.locator('#record').evaluate(e=>e.parentElement.id),'zoom-slot');await page.locator('#close-zoom').click();assert.equal(await page.locator('#record').evaluate(e=>e.parentElement.id),'record-wrap');
    await page.locator('#share').click();await page.locator('#share-dialog[open]').waitFor();assert.match(await page.locator('#embed-code').inputValue(),/title="CROSS record"/);assert.ok((await page.locator('#share-url').inputValue()).startsWith(target.split('?')[0]));await page.locator('.close-dialog').click();
    await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.querySelector('#grooves').style.transform==='none');
    if(name.includes('mobile')){await page.evaluate(()=>scrollTo(0,0));await page.locator('#sticky:not([hidden])').waitFor();await page.locator('#sticky-play').click();await page.waitForFunction(()=>document.querySelector('#audio').paused);}
    else await page.locator('#play').click();
    assert.deepEqual(errors,[]);results.push({browser:name,status:'passed',...dimensions,checks:['play/pause','audio-synchronised rotation','seek','track change','record drag','zoom','share','reduced motion','Bandcamp destinations']});
  }catch(e){results.push({browser:name,status:'failed',error:e.message,pageErrors:errors});}
  finally{if(browser)await browser.close();}
  console.log(JSON.stringify(results.at(-1)));
}
writeFileSync(`${out}/browser-results.json`,JSON.stringify({target,results},null,2));if(results.some(r=>r.status!=='passed'))process.exitCode=1;
