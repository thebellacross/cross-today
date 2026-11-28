const CHUNK_SECONDS=2,MAX_CHUNKS=9;
export const SCRATCH_SECONDS_PER_TURN=1.8; // 33⅓ rpm, independent of the drawn groove spacing.

export function wavFormat(buffer) {
  const view=new DataView(buffer),text=(at,n)=>String.fromCharCode(...new Uint8Array(buffer,at,n));
  if(buffer.byteLength<44||text(0,4)!=='RIFF'||text(8,4)!=='WAVE')throw Error('Unsupported recording format');
  let format;
  for(let offset=12;offset+8<=view.byteLength;) {
    const kind=text(offset,4),size=view.getUint32(offset+4,true),at=offset+8;
    if(kind==='fmt '&&at+size<=view.byteLength) {
      let code=view.getUint16(at,true);
      if(code===65534&&size>=40)code=view.getUint16(at+24,true);
      format={code,channels:view.getUint16(at+2,true),sampleRate:view.getUint32(at+4,true),blockAlign:view.getUint16(at+12,true),bits:view.getUint16(at+14,true)};
    }
    if(kind==='data'&&format) {
      if(![1,3].includes(format.code)||![16,24,32].includes(format.bits)||(format.code===3&&format.bits!==32)||format.sampleRate<8000||format.sampleRate>192000||format.channels<1||format.channels>2||format.blockAlign!==format.channels*format.bits/8)throw Error('Unsupported PCM recording');
      return {...format,dataOffset:at,frames:Math.floor(size/format.blockAlign)};
    }
    offset=at+size+(size%2);
  }
  throw Error('Recording header unavailable');
}

export function decodePcm(buffer,format) {
  const view=new DataView(buffer),frames=Math.floor(buffer.byteLength/format.blockAlign);
  const channels=Array.from({length:format.channels},()=>new Float32Array(frames)),bytes=format.bits/8;
  for(let f=0;f<frames;f++)for(let c=0;c<channels.length;c++) {
    const at=f*format.blockAlign+c*bytes;
    channels[c][f]=format.code===3?view.getFloat32(at,true):format.bits===16?view.getInt16(at,true)/32768:format.bits===24?((view.getUint8(at)|view.getUint8(at+1)<<8|view.getUint8(at+2)<<16)<<8>>8)/8388608:view.getInt32(at,true)/2147483648;
  }
  return channels;
}

// Only a few seconds around the needle are fetched, never the whole WAV.
// Preparation starts after a listening gesture, so the artwork loads first.
export class ScratchAudio {
  constructor(audio) {
    this.audio=audio;this.ready=new Set();this.pending=new Map();this.generation=0;this.active=false;
    audio.addEventListener('volumechange',()=>this.volume());
  }
  async unlock() {
    const Context=window.AudioContext||window.webkitAudioContext;
    if(!Context)throw Error('Scratching is not supported in this browser');
    this.context??=new Context({latencyHint:'interactive'});
    await this.context.resume();
    if(!this.loading)this.loading=this.context.audioWorklet.addModule(new URL('./scratch-worklet.js',import.meta.url)).then(()=>{
      this.node=new AudioWorkletNode(this.context,'vinyl-scratch',{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[2]});
      this.gain=this.context.createGain();this.node.connect(this.gain).connect(this.context.destination);this.volume();
    }).catch(error=>{this.loading=null;throw error;});
    await this.loading;
  }
  volume() { if(this.gain)this.gain.gain.setTargetAtTime(this.audio.muted?0:this.audio.volume,this.context.currentTime,.005); }
  async range(start,end,signal) {
    const request=new AbortController(),abort=()=>request.abort();
    signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();
    const timeout=setTimeout(abort,12000);
    try{
      const response=await fetch(this.url,{headers:{Range:`bytes=${start}-${end}`},signal:request.signal});
      if(response.status!==206){await response.body?.cancel();throw Error('Partial recording unavailable');}
      const returned=response.headers.get('Content-Range');
      if(returned&&!returned.startsWith(`bytes ${start}-${end}/`)){await response.body?.cancel();throw Error('Incorrect recording fragment');}
      const buffer=await response.arrayBuffer();
      if(buffer.byteLength!==end-start+1)throw Error('Incomplete recording fragment');
      return buffer;
    }catch(error){if(error.name==='AbortError'&&!signal.aborted)throw Error('Scratch preparation timed out');throw error;}
    finally{clearTimeout(timeout);signal.removeEventListener('abort',abort);}
  }
  setTrack(track) {
    if(this.url===track.wav)return;
    this.cancel();this.generation++;this.controller?.abort();this.controller=new AbortController();
    this.url=track.wav;this.ready.clear();this.pending.clear();this.format=null;this.header=null;
  }
  async prepare(track,position) {
    this.setTrack(track);const generation=this.generation;
    await this.unlock();if(generation!==this.generation)return false;
    if(!this.header)this.header=this.range(0,4095,this.controller.signal).then(buffer=>{
      if(generation!==this.generation)return;
      this.format=wavFormat(buffer);this.chunkFrames=Math.round(this.format.sampleRate*CHUNK_SECONDS);
      this.node.port.postMessage({type:'configure',...this.format,chunkFrames:this.chunkFrames,duration:this.format.frames/this.format.sampleRate});
    }).catch(error=>{if(generation===this.generation)this.header=null;throw error;});
    await this.header;if(generation!==this.generation)return false;
    const id=Math.floor(position/CHUNK_SECONDS),last=Math.ceil(this.format.frames/this.chunkFrames)-1;
    const wanted=[id,id-1,id+1].filter(n=>n>=0&&n<=last);
    const jobs=wanted.map(n=>this.loadChunk(n,generation));
    // Load the current position first; neighbours continue preparing in parallel.
    jobs.slice(1).forEach(job=>job.catch(()=>{}));
    await jobs[0];return generation===this.generation&&this.ready.has(id);
  }
  async loadChunk(id,generation) {
    if(this.ready.has(id))return;
    if(this.pending.has(id))return this.pending.get(id);
    const format=this.format,start=id*this.chunkFrames,end=Math.min(format.frames,start+this.chunkFrames);
    const task=this.range(format.dataOffset+start*format.blockAlign,format.dataOffset+end*format.blockAlign-1,this.controller.signal).then(buffer=>{
      if(generation!==this.generation)return;
      const channels=decodePcm(buffer,format);
      this.node.port.postMessage({type:'chunk',id,channels},channels.map(channel=>channel.buffer));this.ready.add(id);
      if(this.ready.size>MAX_CHUNKS){const ids=[...this.ready].sort((a,b)=>Math.abs(a-id)-Math.abs(b-id)).slice(0,MAX_CHUNKS);this.ready=new Set(ids);this.node.port.postMessage({type:'retain',ids});}
    }).finally(()=>{if(generation===this.generation)this.pending.delete(id);});
    this.pending.set(id,task);return task;
  }
  start(position) { this.active=true;this.position=position;this.node.port.postMessage({type:'start',position}); }
  move(position,seconds) { if(this.active){this.position=position;this.node.port.postMessage({type:'move',position,seconds});} }
  cancel() { this.active=false;this.node?.port.postMessage({type:'stop'}); }
}
