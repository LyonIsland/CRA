const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const base=process.env.WORKSHOP_URL||'http://127.0.0.1:8878';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 let socketCount=0;page.on('websocket',()=>socketCount++);page.on('pageerror',e=>errors.push(String(e)));
 try{
  await page.goto(base+'/assembly?observe=1',{waitUntil:'domcontentloaded'});
  const view=page.frameLocator('#live-view');
  await view.locator('#view-heap').waitFor({state:'visible',timeout:45000});
  const frame=page.frames().find(f=>new URL(f.url()).searchParams.get('embedded')==='1');
  const first=await frame.evaluate(()=>window.workshopState.seq);
  await view.locator('#view-heap').click();await page.waitForTimeout(1800);
  const last=await frame.evaluate(()=>window.workshopState.seq);
  if(last<=first)throw Error('Observer state is not updating');
  for(const id of ['live-start','live-pause','live-reset'])if(!await page.locator('#'+id).isDisabled())throw Error('Observer control enabled: '+id);
  if(!await view.locator('#start').isDisabled())throw Error('Embedded observer control enabled');
  if(socketCount||errors.length)throw Error(JSON.stringify({socketCount,errors}));
  await page.screenshot({path:path.resolve(__dirname,'../outputs/clutter/observer-console.png'),fullPage:true});
  const report={real_HTTP_observer:true,live_sequence_advanced:true,websocket_count:socketCount,
   controls_disabled:true,errors,physical_task_success_tested:false};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/clutter/observer-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
