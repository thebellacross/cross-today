// A signed, sample-addressed turntable. Both directions read the same recording.
// This runs on the audio thread; pointer events only supply the next hand position.
export class ScratchVoice {
  constructor(outputRate) { this.outputRate=outputRate;this.reset(); }
  reset() { this.chunks=new Map();this.active=false;this.position=0;this.target=0;this.remaining=0;this.gain=0; }
  configure({sampleRate,chunkFrames,duration}) { this.reset();this.sourceRate=sampleRate;this.chunkFrames=chunkFrames;this.duration=duration; }
  chunk(id,channels) { this.chunks.set(id,channels); }
  retain(ids) { for(const id of this.chunks.keys())if(!ids.includes(id))this.chunks.delete(id); }
  start(position) { this.active=true;this.position=this.target=position;this.remaining=0;this.gain=0; }
  move(position,seconds) {
    this.target=Math.max(0,Math.min(this.duration-1/this.sourceRate,position));
    // A short continuous traversal between pointer samples, including reversal.
    this.remaining=Math.max(1,Math.round(Math.max(.006,seconds,Math.abs(this.target-this.position)/8)*this.outputRate));
  }
  stop() { this.active=false;this.remaining=0; }
  sample(channel,frame) {
    const id=Math.floor(frame/this.chunkFrames),data=this.chunks.get(id);
    if(!data)return 0;
    return data[Math.min(channel,data.length-1)][frame-id*this.chunkFrames]||0;
  }
  render(channels) {
    if(!this.sourceRate||(!this.active&&this.gain<.00001)){for(const channel of channels)channel.fill(0);return;}
    for(let i=0;i<channels[0].length;i++) {
      const moving=this.active&&this.remaining>0&&Math.abs(this.target-this.position)>1e-8;
      const frame=this.position*this.sourceRate,whole=Math.floor(frame),fraction=frame-whole;
      // Fade a held needle to silence instead of emitting a DC sample or a click.
      const wanted=moving?1:0;this.gain+=(wanted-this.gain)*Math.min(1,1/(this.outputRate*.002));
      for(let c=0;c<channels.length;c++) {
        const a=this.sample(c,whole),b=this.sample(c,whole+1);
        channels[c][i]=(a+(b-a)*fraction)*this.gain;
      }
      if(this.active&&this.remaining>0){this.position+=(this.target-this.position)/this.remaining;this.remaining--;}
    }
  }
}
