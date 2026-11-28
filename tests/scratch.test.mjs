import test from 'node:test';
import assert from 'node:assert/strict';
import {ScratchVoice} from '../web/scratch-voice.js';
import {decodePcm,wavFormat,SCRATCH_SECONDS_PER_TURN} from '../web/scratch-audio.js';

test('published extensible 24-bit WAV is decoded with exact stereo sample signs',()=>{
  const header=new ArrayBuffer(68),v=new DataView(header),text=(at,s)=>[...s].forEach((c,i)=>v.setUint8(at+i,c.charCodeAt(0)));
  text(0,'RIFF');text(8,'WAVE');text(12,'fmt ');v.setUint32(16,40,true);v.setUint16(20,65534,true);v.setUint16(22,2,true);v.setUint32(24,48000,true);v.setUint16(32,6,true);v.setUint16(34,24,true);v.setUint16(44,1,true);text(60,'data');v.setUint32(64,12,true);
  const format=wavFormat(header);assert.equal(format.dataOffset,68);assert.equal(format.frames,2);
  const pcm=new Uint8Array([0,0,128,255,255,127,0,0,64,0,0,192]);
  const [left,right]=decodePcm(pcm.buffer,format);assert.deepEqual([...left],[-1,.5]);assert.ok(right[0]>.9999);assert.equal(right[1],-.5);
  v.setUint16(32,2,true);assert.throws(()=>wavFormat(header));
});

function voice(rate=48000){const v=new ScratchVoice(rate);v.configure({sampleRate:48000,chunkFrames:48000,duration:4});for(let n=0;n<4;n++)v.chunk(n,[Float32Array.from({length:48000},(_,i)=>Math.sin(2*Math.PI*440*(i+n*48000)/48000)*.5)]);return v;}
function render(v,seconds){const out=new Float32Array(Math.round(v.outputRate*seconds));for(let at=0;at<out.length;at+=128)v.render([out.subarray(at,Math.min(at+128,out.length))]);return out;}
function crossings(data){let n=0;for(let i=1;i<data.length;i++)if(data[i-1]<0&&data[i]>=0)n++;return n;}

test('forward and backward movements produce the recording at hand-controlled speed',()=>{
  assert.equal(SCRATCH_SECONDS_PER_TURN,1.8);
  for(const outputRate of [44100,48000])for(const direction of [-1,1])for(const speed of [.5,1,2]){
    const v=voice(outputRate);v.start(2);v.move(2+direction*speed*.25,.25);const samples=render(v,.25);
    assert.ok(samples.some(x=>Math.abs(x)>.45));assert.ok(Math.abs(crossings(samples)-440*speed*.25)<2);
    assert.ok(Math.abs(v.position-(2+direction*speed*.25))<1e-9);
    // Compare samples with the original source evaluated in the requested direction.
    for(const i of [2000,4001,7003]){
      const expected=.5*Math.sin(2*Math.PI*440*(2+direction*speed*i/outputRate));
      assert.ok(Math.abs(samples[i]-expected)<.002);
    }
  }
});

test('reversal is continuous, held record becomes silent, chunks meet without a gap',()=>{
  const v=voice();v.start(.9);v.move(1.1,.2);const first=render(v,.2);v.move(.9,.2);const back=render(v,.2);
  assert.ok(Math.abs(first.at(-1)-back[0])<.04);assert.ok(first.slice(4700,4900).some(x=>Math.abs(x)>.4));
  const held=render(v,.06);assert.ok(held.slice(-100).every(x=>Math.abs(x)<.00001));
  v.move(1,.1);render(v,.02);v.stop();assert.ok(render(v,.06).slice(-100).every(x=>Math.abs(x)<.00001));
  v.configure({sampleRate:48000,chunkFrames:48000,duration:4});v.start(1);v.move(1.1,.1);assert.ok(render(v,.1).every(x=>x===0));
});

test('unconfigured or stopped worklets output finite silence',()=>{
  const v=new ScratchVoice(48000);assert.ok(render(v,.1).every(x=>x===0));
});
