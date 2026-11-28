import {ScratchVoice} from './scratch-voice.js';
class VinylProcessor extends AudioWorkletProcessor {
  constructor() {
    super();this.voice=new ScratchVoice(sampleRate);
    this.port.onmessage=({data})=>{
      if(data.type==='configure')this.voice.configure(data);
      else if(data.type==='chunk')this.voice.chunk(data.id,data.channels);
      else if(data.type==='retain')this.voice.retain(data.ids);
      else if(data.type==='start')this.voice.start(data.position);
      else if(data.type==='move')this.voice.move(data.position,data.seconds);
      else if(data.type==='stop')this.voice.stop();
    };
  }
  process(inputs,outputs) { this.voice.render(outputs[0]);return true; }
}
registerProcessor('vinyl-scratch',VinylProcessor);
