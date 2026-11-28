// The spectral cover is the source of the visible grooves and their light.
// A fixed seed scatters dust over that image; no audio or source files are altered.
const TAU = Math.PI * 2;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
export const groovePitch = turns => .36 / (turns + .9);

export function recordPoint(clientX, clientY, bounds, tilt, centerY=bounds.height/2) {
  const x = (clientX - bounds.left - bounds.width / 2) / bounds.width;
  const y = (clientY - bounds.top - centerY) / (bounds.width * tilt);
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
  ctx.fillStyle='#050506';ctx.fillRect(0,0,side,side);
  // A continuous, evenly lit surface keeps the centre coplanar with the grooves.
  // No radial shadow or inner bloom: those made the label read as a deep well.
  ctx.fillStyle='#201d29';ctx.beginPath();ctx.arc(side/2,side/2,side*.475,0,TAU);ctx.fill();
  ctx.save();ctx.globalAlpha=.38;ctx.drawImage(source,0,0);ctx.restore();
  ctx.strokeStyle='rgba(177,171,191,.12)';ctx.lineWidth=.65;
  for(let radius=side*.116;radius<side*.474;radius+=5.5){ctx.beginPath();ctx.arc(side/2,side/2,radius,0,TAU);ctx.stroke();}
  const random = randomFor(album.seed), phase = random() * TAU;
  for (let i=0; i<520000; i++) {
    const x = Math.floor(random()*side), y = Math.floor(random()*side);
    const strength = strengths[y*side+x];
    if (!strength || random() > .13 + strength * .75) continue;
    const dx=x/side-.5, dy=y/side-.5, radius=Math.hypot(dx,dy);
    const arm=.45+.55*Math.pow(.5+.5*Math.cos(Math.atan2(dy,dx)*3-radius*23+phase),3);
    const offset=(y*side+x)*4;
    const alpha=(.25+random()*.75)*Math.sqrt(strength)*arm;
    ctx.fillStyle=`rgba(${values[offset]},${values[offset+1]},${values[offset+2]},${alpha})`;
    const size=.5+random()*1.35;
    const px=x+(random()-.5)*4,py=y+(random()-.5)*4;
    ctx.fillRect(px,py,size,size);
    if(strength>.4 && random()>.998) {
      ctx.fillStyle=`rgba(242,235,255,${alpha*.75})`;
      ctx.fillRect(x-2,y,5,.6);ctx.fillRect(x,y-2,.6,5);
    }
  }
  // A printed centre label and crisp rim, both in the very same projected plane.
  ctx.fillStyle='#b9b5bc';ctx.beginPath();ctx.arc(side/2,side/2,side*.113,0,TAU);ctx.fill();
  ctx.strokeStyle='rgba(210,204,218,.55)';ctx.lineWidth=1;
  ctx.beginPath();ctx.arc(side/2,side/2,side*.113,0,TAU);ctx.stroke();
  ctx.strokeStyle='rgba(166,164,185,.6)';ctx.lineWidth=1.2;
  ctx.beginPath();ctx.arc(side/2,side/2,side*.475,0,TAU);ctx.stroke();
  canvas.dataset.ready='true';
}

export async function loadRecord(image,album) {
  const checksum=album.assets?.['cover.png']?.sha256;
  if(image.dataset.previewId===album.id && image.dataset.previewHash===checksum) {
    try {
      await image.decode();image.dataset.ready='true';image.dataset.renderPath='prepared';return;
    }catch{/* An unavailable prepared image falls back to the release itself. */}
  }
  image.src=new URL('./assets/record-outline.svg',import.meta.url).href;
  image.dataset.ready='false';
  const canvas=document.createElement('canvas');
  await drawGalaxy(canvas,album);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.86));
  if(!blob)throw Error('The record image could not be prepared.');
  const url=URL.createObjectURL(blob);
  try { image.src=url;await image.decode();image.dataset.ready='true';image.dataset.renderPath='release'; }
  finally { URL.revokeObjectURL(url); }
}

export class RecordView {
  constructor(record, canvas, needle, reduced) {
    this.record=record;this.canvas=canvas;this.needle=needle;this.reduced=reduced;this.hub=record.querySelector('#hub');
    this.progress=0;this.turns=10;
    this.resize=new ResizeObserver(()=>this.measure());this.resize.observe(record);
    reduced.addEventListener('change',()=>this.update(this.progress,this.turns));
    this.measure();
  }
  measure() {
    this.width=this.record.clientWidth;this.height=this.record.clientHeight;
    const preferred=Number(getComputedStyle(this.record).getPropertyValue('--disc-tilt'))||.21;
    // Short windows still show the whole plane and its upright needle. The same
    // projection is used for drawing, pointer coordinates and progress location.
    const needleHeight=this.needle.getBoundingClientRect().height||38;
    this.tilt=Math.min(preferred,Math.max(.025,(this.height-needleHeight-12)/(this.width*.95)));
    this.centerY=(this.height+needleHeight)/2;
    this.record.style.setProperty('--disc-projection',this.tilt);
    this.record.style.setProperty('--disc-center',`${this.centerY}px`);
    this.update(this.progress,this.turns);
  }
  point(event) { return recordPoint(event.clientX,event.clientY,this.record.getBoundingClientRect(),this.tilt,this.centerY); }
  update(progress,turns) {
    this.progress=progress;this.turns=turns;
    const turn=progress*turns, angle=this.reduced.matches?turn*TAU:0;
    const radius=.47-turn*groovePitch(turns);
    this.canvas.style.transform=this.reduced.matches?'none':`rotate(${-360*turn}deg)`;
    if(this.hub)this.hub.style.transform=this.canvas.style.transform;
    this.needle.style.left=`${this.width*(.5+Math.sin(angle)*radius)}px`;
    this.needle.style.top=`${this.centerY-this.width*this.tilt*Math.cos(angle)*radius}px`;
  }
}
