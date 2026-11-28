import {chromium,webkit,devices} from 'playwright';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
const target=process.env.TEST_SITE||'http://127.0.0.1:8767/';
const out=process.env.TEST_OUTPUT||'.state/scratching-2026-11-28/audio';mkdirSync(out,{recursive:true});
const results=[];
for(const [name,type,options,context]of [['chrome',chromium,{channel:'chrome'},{viewport:{width:1512,height:850}}],['webkit-mobile',webkit,{},devices['iPhone 13']]]){
 const browser=await type.launch({headless:true,...options});
 try{
  const page=await browser.newPage(context),errors=[],ranges=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   const Original=window.AudioWorkletNode;
   window.AudioWorkletNode=class extends Original{
    constructor(context,name,options){super(context,name,options);window.scratchNode=this;window.scratchContext=context;const meter=context.createAnalyser();meter.fftSize=2048;this.connect(meter);window.scratchMeter=meter;}
   };
  });
  page.on('request',r=>{if(new URL(r.url()).pathname.endsWith('.wav'))ranges.push(r.headers().range);});
  await page.goto(target,{waitUntil:'domcontentloaded'});await page.locator('#play:not([disabled])').waitFor();await page.locator('#grooves[data-ready=true]').waitFor();
  assert.equal(ranges.length,0,'No scratch audio downloads before interaction');
  await page.locator('#audio').evaluate(a=>{a.volume=0;});await page.locator('#play').click();
  await page.waitForFunction(()=>document.querySelector('#audio').currentTime>.1);await page.locator('#audio').evaluate(a=>a.currentTime=30);await page.waitForFunction(()=>document.querySelector('#audio').currentTime>30.1&&!document.querySelector('#audio').seeking);
  await page.locator('#record').scrollIntoViewIfNeeded();
  const g=await page.locator('#record').evaluate(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,tilt:+getComputedStyle(e).getPropertyValue('--disc-projection'),center:parseFloat(getComputedStyle(e).getPropertyValue('--disc-center'))};});
  const point=angle=>({x:g.x+g.w*(.5+Math.sin(angle)*.3),y:g.y+g.center-g.w*g.tilt*Math.cos(angle)*.3});
  let angle=-.9,p=point(angle);await page.mouse.move(p.x,p.y);await page.waitForTimeout(250);await page.mouse.down();
  await page.locator('#record[data-scratching=active]').waitFor({timeout:20000});
  assert.equal(await page.locator('#play').getAttribute('aria-label'),'Pause');
  const held=await page.locator('#audio').evaluate(a=>a.currentTime);
  const levels=[],positions=[];
  for(const direction of [1,-1,1,-1]){
   for(let i=0;i<20;i++){
    angle+=direction*.035;p=point(angle);await page.mouse.move(p.x,p.y);await page.waitForTimeout(12);
    levels.push(await page.evaluate(()=>{const data=new Float32Array(scratchMeter.fftSize);scratchMeter.getFloatTimeDomainData(data);return Math.sqrt(data.reduce((sum,x)=>sum+x*x,0)/data.length);}));
   }
   positions.push(await page.locator('#seek').inputValue());
  }
  assert.ok(Math.max(...levels)>.001,'The worklet must output actual audible samples during dragging');
  assert.ok(+positions[0]<+positions[1]&&+positions[2]<+positions[3],'Reverse hand direction must reverse the audio position');
  await page.waitForTimeout(140);
  const stopped=await page.evaluate(()=>{const data=new Float32Array(scratchMeter.fftSize);scratchMeter.getFloatTimeDomainData(data);return Math.max(...data.map(Math.abs));});
  assert.ok(stopped<.0001,'Holding still should silence the held groove');
  await page.mouse.up();await page.waitForFunction(()=>!document.querySelector('#audio').paused);const released=await page.locator('#audio').evaluate(a=>a.currentTime);
  assert.ok(Math.abs(released-held)<.5,'Back-and-forth scratching should release near the starting position');
  await page.waitForTimeout(180);assert.ok(await page.locator('#audio').evaluate(a=>a.currentTime)>released+.1);
  // A cancelled pointer must release the sound and resume playback as well.
  p=point(-.8);await page.mouse.move(p.x,p.y);await page.mouse.down();await page.locator('#record[data-scratching=active]').waitFor();await page.locator('#record').dispatchEvent('pointercancel');await page.mouse.up();await page.waitForFunction(()=>!document.querySelector('#audio').paused);
  assert.equal(await page.locator('#record').getAttribute('data-scratching'),null);
  await page.locator('#play').click();await page.waitForFunction(()=>document.querySelector('#audio').paused);
  // Scratching a paused recording auditions it, but release preserves pause.
  p=point(-.9);await page.mouse.move(p.x,p.y);await page.mouse.down();await page.locator('#record[data-scratching=active]').waitFor();p=point(-.5);await page.mouse.move(p.x,p.y,{steps:5});await page.mouse.up();assert.equal(await page.locator('#audio').evaluate(a=>a.paused),true);
  assert.ok(ranges.every(value=>/^bytes=\d+-\d+$/.test(value)));assert.ok(ranges.every(value=>{const [a,b]=value.slice(6).split('-').map(Number);return b-a+1<=1152000;}));
  assert.deepEqual(errors,[]);results.push({browser:name,status:'passed',peakRms:Math.max(...levels),heldPeak:stopped,rangeRequests:ranges.length,checks:['no audio prefetch before interaction','audible forward and reverse scratching','hand-speed playback and position','held record is silent','playing control stays active','release resumes from scratch position','pointer cancellation resumes','paused audition stays paused','bounded PCM requests'],errors});
 }catch(error){results.push({browser:name,status:'failed',error:error.stack});}
 finally{await browser.close();}
 console.log(JSON.stringify(results.at(-1)));
}
writeFileSync(`${out}/results.json`,JSON.stringify(results,null,2));if(results.some(r=>r.status!=='passed'))process.exitCode=1;
