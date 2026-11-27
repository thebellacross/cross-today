// The spectral cover is the source of the visible grooves and their light.
// A fixed seed scatters dust over that image; no audio or source files are altered.
const TAU = Math.PI * 2;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
export const groovePitch = turns => .36 / (turns + .9);

export function recordPoint(clientX, clientY, bounds, tilt) {
  const x = (clientX - bounds.left - bounds.width / 2) / bounds.width;
  const y = (clientY - bounds.top - bounds.height / 2) / (bounds.width * tilt);
  return {r: Math.hypot(x, y), a: Math.atan2(x, -y)};
}

export function grooveProgress(point, progress, turns, reduced) {
  const rotation = reduced ? 0 : -progress * turns;
  const phase = ((point.a / TAU - rotation) % 1 + 1) % 1;
  const turn = Math.floor((.47 - point.r) / groovePitch(turns) - phase + 1e-7) + phase;
  return clamp(turn / turns, 0, 1);
}

function randomFor(seed) {
  let state = 2166136261;
  for (const char of String(seed)) state = Math.imul(state ^ char.charCodeAt(0), 16777619) >>> 0;
  return () => { state = (Math.imul(1664525, state) + 1013904223) >>> 0; return state / 4294967296; };
}

export async function drawGalaxy(canvas, album) {
  const image = new Image();
  image.crossOrigin = 'anonymous';
  image.src = album.cover;
  await image.decode();
  const side = 1600, source = document.createElement('canvas');
  source.width = source.height = side;
  const sample = source.getContext('2d', {willReadFrequently:true});
  sample.drawImage(image, 0, 0, side, side);
  const pixels = sample.getImageData(0, 0, side, side), values = pixels.data;
  const paper = album.palette.at(-1).match(/[\da-f]{2}/gi).map(c => parseInt(c,16));
  const strengths = new Float32Array(side * side);
  // Remove the original paper, retain spectral intensity, and lift its own hues.
  for (let y = 0; y < side; y++) for (let x = 0; x < side; x++) {
    const i = (y * side + x) * 4, radius = Math.hypot(x / side - .5, y / side - .5);
    if (radius < .109 || radius > .477) { values[i+3] = 0; continue; }
    const strength = clamp(Math.max(paper[0]-values[i], paper[1]-values[i+1], paper[2]-values[i+2]) / 220 - .035, 0, 1);
    strengths[y * side + x] = strength;
    const peak = Math.max(values[i], values[i+1], values[i+2], 1);
    for (let k=0; k<3; k++) values[i+k] = Math.round(255 * (.28 + .72 * values[i+k] / peak));
    values[i+3] = Math.round(220 * Math.pow(strength, .8));
  }
  sample.putImageData(pixels, 0, 0);
  canvas.width = canvas.height = side;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0,0,side,side);
  // Low, static light around the actual spiral. It never pulses with the music.
  ctx.save();ctx.filter='blur(12px)';ctx.globalAlpha=.55;ctx.drawImage(source,0,0);ctx.restore();
  ctx.save();ctx.globalAlpha=.24;ctx.drawImage(source,0,0);ctx.restore();
  const random = randomFor(album.seed), phase = random() * TAU;
  for (let i=0; i<520000; i++) {
    const x = Math.floor(random()*side), y = Math.floor(random()*side);
    const strength = strengths[y*side+x];
    if (!strength || random() > .13 + strength * .75) continue;
    const dx=x/side-.5, dy=y/side-.5, radius=Math.hypot(dx,dy);
    const arm=.2+.8*Math.pow(.5+.5*Math.cos(Math.atan2(dy,dx)*3-radius*23+phase),3);
    const offset=(y*side+x)*4;
    const alpha=(.25+random()*.75)*Math.sqrt(strength)*arm;
    ctx.fillStyle=`rgba(${values[offset]},${values[offset+1]},${values[offset+2]},${alpha})`;
    const size=.65+random()*1.6;
    const px=x+(random()-.5)*4,py=y+(random()-.5)*4;
    ctx.fillRect(px,py,size,size);
    if(strength>.4 && random()>.998) {
      ctx.fillStyle=`rgba(242,235,255,${alpha*.75})`;
      ctx.fillRect(x-2,y,5,.6);ctx.fillRect(x,y-2,.6,5);
    }
  }
  // A shallow rim makes the record read as a plane, without adding a player frame.
  ctx.strokeStyle='rgba(153,163,210,.16)';ctx.lineWidth=.7;
  ctx.beginPath();ctx.arc(side/2,side/2,side*.475,0,TAU);ctx.stroke();
  canvas.dataset.ready='true';
}

export class RecordView {
  constructor(record, canvas, needle, reduced) {
    this.record=record;this.canvas=canvas;this.needle=needle;this.reduced=reduced;
    this.progress=0;this.turns=10;
    this.resize=new ResizeObserver(()=>this.measure());this.resize.observe(record);
    reduced.addEventListener('change',()=>this.update(this.progress,this.turns));
    this.measure();
  }
  measure() {
    this.width=this.record.clientWidth;this.height=this.record.clientHeight;
    this.tilt=Number(getComputedStyle(this.record).getPropertyValue('--disc-tilt'))||.3;
    this.update(this.progress,this.turns);
  }
  point(event) { return recordPoint(event.clientX,event.clientY,this.record.getBoundingClientRect(),this.tilt); }
  update(progress,turns) {
    this.progress=progress;this.turns=turns;
    const turn=progress*turns, angle=this.reduced.matches?turn*TAU:0;
    const radius=.47-turn*groovePitch(turns);
    this.canvas.style.transform=this.reduced.matches?'none':`rotate(${-360*turn}deg)`;
    this.needle.style.left=`${this.width*(.5+Math.sin(angle)*radius)}px`;
    this.needle.style.top=`${this.height/2-this.width*this.tilt*Math.cos(angle)*radius}px`;
  }
}
