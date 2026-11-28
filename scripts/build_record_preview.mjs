// Render the same browser-native artwork once per edition, ahead of visitors.
import {chromium} from 'playwright';
import {createServer} from 'node:http';
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
const directory=resolve(process.argv[2]||'.state/record-preview');
const album=JSON.parse(readFileSync(join(directory,'album.json')));
const identity=JSON.parse(readFileSync(join(directory,'identity.json')));
identity.renderer=createHash('sha256').update(readFileSync('web/record.js')).digest('hex').slice(0,16);
const routes=new Map([
 ['/',{type:'text/html',data:'<!doctype html><canvas id="record"></canvas>'}],
 ['/record.js',{type:'text/javascript',data:readFileSync('web/record.js')}],
 ['/cover.png',{type:'image/png',data:readFileSync(join(directory,'cover.png'))}]
]);
const server=createServer((request,response)=>{
 const file=routes.get(request.url);if(!file){response.writeHead(404).end();return;}
 response.writeHead(200,{'Content-Type':file.type});response.end(file.data);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
let browser;
try {
 browser=await chromium.launch({headless:true,...(process.env.RECORD_BROWSER_CHANNEL?{channel:process.env.RECORD_BROWSER_CHANNEL}:{})});
 const page=await browser.newPage();await page.goto(origin);
 const encoded=await page.evaluate(async album=>{
  const {drawGalaxy}=await import('/record.js');const canvas=document.getElementById('record');
  await drawGalaxy(canvas,{...album,cover:'/cover.png'});return canvas.toDataURL('image/webp',.86).split(',')[1];
 },album);
 const data=Buffer.from(encoded,'base64'),digest=createHash('sha256').update(data).digest('hex');
 const filename=`record-${album.id}-${digest.slice(0,12)}.webp`;
 writeFileSync(join(directory,filename),data);
 writeFileSync(join(directory,'record-preview.json'),JSON.stringify({...identity,file:filename,sha256:digest,bytes:data.length,width:1600,height:1600}));
 console.log(`Prepared ${album.id} record: ${data.length} bytes; original cover: ${album.assets['cover.png'].bytes} bytes.`);
}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
