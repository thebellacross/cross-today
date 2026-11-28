// Geometry is ready independently of configuration, album data and audio.
import {RecordView} from './record.js?v=galaxy-3';
export const reduced=matchMedia('(prefers-reduced-motion: reduce)');
export const recordView=new RecordView(document.getElementById('record'),document.getElementById('grooves'),document.getElementById('needle'),reduced);
const image=document.getElementById('grooves');
function outline(){
  const source=new URL('./assets/record-outline.svg',import.meta.url).href;
  image.dataset.ready='false';image.dataset.previewId='';
  if(image.src!==source)image.src=source;
}
image.addEventListener('error',outline);
if(image.complete&&!image.naturalWidth)outline();
