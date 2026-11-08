const {chromium}=require('playwright');
const http=require('http'),crypto=require('crypto'),fs=require('fs'),path=require('path');
function sampleStream(url,ms){return new Promise((resolve,reject)=>{
 let buffer=Buffer.alloc(0),frames=[];let timer;
 const request=http.get(url,response=>{
  if(!response.headers['content-type']?.includes('multipart/x-mixed-replace'))return reject(new Error('Not an MJPEG stream'));
  response.on('data',chunk=>{
   buffer=Buffer.concat([buffer,chunk]);
   while(true){
    const end=buffer.indexOf('\r\n\r\n');if(end<0)break;
    const header=buffer.subarray(0,end).toString();const length=Number(header.match(/Content-Length: (\d+)/)?.[1]);
    if(!length)return reject(new Error('Invalid JPEG frame header'));
    if(buffer.length<end+4+length+2)break;
    const jpeg=buffer.subarray(end+4,end+4+length);
    if(jpeg[0]!==255||jpeg[1]!==216)return reject(new Error('Invalid JPEG data'));
    frames.push({time:Date.now(),seq:Number(header.match(/X-Frame-Sequence: (\d+)/)?.[1]),hash:crypto.createHash('sha256').update(jpeg).digest('hex')});
    buffer=buffer.subarray(end+4+length+2);
   }
  });
 });
 request.on('error',reject);
 timer=setTimeout(()=>{request.destroy();const seconds=frames.length>1?(frames.at(-1).time-frames[0].time)/1000:1;
  const gaps=frames.slice(1).map((frame,i)=>frame.time-frames[i].time);
  resolve({frames:frames.length,fps:(frames.length-1)/seconds,unique_images:new Set(frames.map(f=>f.hash)).size,max_gap_ms:Math.max(0,...gaps),strict_sequence:frames.every((f,i)=>i===0||f.seq>frames[i-1].seq)});
 },ms);
 request.on('close',()=>clearTimeout(timer));
})}
(async()=>{
 const url=process.env.WORKSHOP_URL||'http://127.0.0.1:8876/';
 const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage();const errors=[];let snapshots=0;
 page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(new URL(r.url()).pathname==='/wrist.jpg')snapshots++});
 try{
  await page.goto(url,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.workshopState?.tabletop&&window.workshopWristPreviewStats?.fps>0,{},{timeout:60000});
  await page.waitForTimeout(4000);
  const local=await page.evaluate(()=>window.workshopWristPreviewStats);
  if(local.fps<15||await page.locator('#wrist-image').getAttribute('src'))throw new Error('Local preview too slow or fetching RGB');
  await page.screenshot({path:path.resolve(__dirname,'../outputs/wrist-smooth-preview.png')});
  await page.selectOption('#wrist-mode','rgb');
  await page.waitForFunction(()=>document.getElementById('wrist-image').naturalWidth===320);
  await page.locator('#pause').click();await page.waitForFunction(()=>window.workshopState.mode==='paused');
  const before=await page.evaluate(()=>window.workshopState.sim_time);
  const paused=await sampleStream(new URL('/wrist.mjpeg',url),8000);
  const after=await page.evaluate(()=>window.workshopState.sim_time);
  if(Math.abs(after-before)>1e-8)throw new Error('Preview advanced paused physics');
  await page.locator('#start').click();await page.waitForFunction(()=>window.workshopState.mode==='robot');
  const moving=await sampleStream(new URL('/wrist.mjpeg',url),8000);
  if(paused.fps<2.5||moving.fps<2.5||!paused.strict_sequence||!moving.strict_sequence||moving.unique_images<5)throw new Error('Stream stale, unordered or stalled: '+JSON.stringify({paused,moving}));
  await page.selectOption('#wrist-mode','local');
  await page.waitForTimeout(2500);
  const localMoving=await page.evaluate(()=>window.workshopWristPreviewStats);
  if(localMoving.fps<15||await page.locator('#wrist-image').getAttribute('src'))throw new Error('Local moving preview failed to stop RGB stream');
  await page.waitForFunction(()=>['human','paused'].includes(window.workshopState.mode),{},{timeout:180000});
  const state=await page.evaluate(()=>window.workshopState);
  if(!state.success)throw new Error(state.message);
  if(state.camera_preview.error||state.camera_preview.preview_physics_time_delta_max>1e-8)throw new Error('Capture failed or altered physics');
  if(errors.length||snapshots)throw new Error('Browser error or legacy polling: '+JSON.stringify({errors,snapshots}));
  const result={browser:'Edge headless / SwiftShader software rendering',default_preview:'browser 3D wrist view; not sensor RGB',local,localMoving,transport:'MJPEG latest-frame push',paused,moving,paused_physics_unchanged:true,delivery_with_stream_passed:true,
   legacy_snapshot_requests:snapshots,preview_stats:state.camera_preview,errors,actual_quest_pro_tested:false};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/camera-stream-check.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
