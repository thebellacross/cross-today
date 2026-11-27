import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
const base=process.env.TEST_SITE||'http://127.0.0.1:8765/';
const out=process.env.TEST_OUTPUT||'.state/qa';mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
const checks=[];
try {
  await page.goto(base);await page.locator('#grooves[data-ready=true]').waitFor();
  const album=await page.evaluate(async()=>{const {loadAlbum}=await import('./client.js');return loadAlbum()});
  // Click a known groove in the projected plane and verify its album audio position.
  await page.locator('#record').scrollIntoViewIfNeeded();
  const rect=await page.locator('#record').boundingBox();
  const desired=.32,turn=album.turns*desired,r=.47-(turn+.45)*(.36/(album.turns+.9)),angle=turn*Math.PI*2;
  await page.mouse.click(rect.x+rect.width*(.5+Math.sin(angle)*r),rect.y+rect.height/2-rect.width*.3*Math.cos(angle)*r);
  await page.waitForFunction(()=>document.querySelector('#audio').readyState>=1);
  const actual=await page.locator('#audio').evaluate(a=>({src:a.src,time:a.currentTime,paused:a.paused}));
  const track=album.tracks.findIndex(t=>t.src===actual.src);
  const absolute=album.tracks.slice(0,track).reduce((s,t)=>s+t.duration,0)+actual.time;
  assert.ok(Math.abs(absolute/album.duration-desired)<.002);assert.equal(actual.paused,true);checks.push('projected groove click selects correct audio time while paused');
  await page.locator('#record').focus();await page.keyboard.press('ArrowRight');
  await page.waitForFunction(t=>document.querySelector('#audio').currentTime>t+4.9,actual.time);checks.push('record keyboard seeking');
  await page.locator('#enlarge').focus();await page.keyboard.press('Space');await page.locator('#zoom[open]').waitFor();assert.equal(await page.locator('#audio').evaluate(a=>a.paused),true);await page.keyboard.press('Escape');await page.locator('#zoom').waitFor({state:'hidden'});checks.push('keyboard zoom does not toggle playback');
  await page.goto(base+'?embed=1');await page.locator('#grooves[data-ready=true]').waitFor();assert.equal(await page.locator('.site-header').isVisible(),false);await page.locator('#audio').evaluate(a=>a.volume=0);await page.locator('#play').click();await page.waitForFunction(()=>document.querySelector('#audio').currentTime>.2);await page.locator('#play').click();checks.push('embedded player playback');
  await page.route('**/score.json',r=>r.fulfill({status:503,body:'{}'}));
  await page.goto(base);await page.locator('#play:not([disabled])').waitFor();await page.waitForFunction(()=>document.querySelector('#heard').textContent.includes('unavailable'));
  assert.notEqual(await page.locator('#track-title').textContent(),'No playable edition');await page.locator('#audio').evaluate(a=>a.volume=0);await page.locator('#play').click();await page.waitForFunction(()=>document.querySelector('#audio').currentTime>.2);await page.locator('#play').click();checks.push('source-detail failure does not disable or mislabel playable audio');
  await page.unroute('**/score.json');
  await page.route('**/cover.png',r=>r.fulfill({status:503,body:''}));
  await page.goto(base);await page.locator('#play:not([disabled])').waitFor();await page.locator('#status:not([hidden])').waitFor();assert.match(await page.locator('#status').innerText(),/record image/);
  await page.locator('#audio').evaluate(a=>a.volume=0);await page.locator('#play').click();await page.waitForFunction(()=>document.querySelector('#audio').currentTime>.2);checks.push('image failure leaves audio usable with clear status');
  assert.deepEqual(errors,[]);
  writeFileSync(`${out}/edge-results.json`,JSON.stringify({status:'passed',checks,errors},null,2));console.log(JSON.stringify({status:'passed',checks}));
} finally {await browser.close();}
