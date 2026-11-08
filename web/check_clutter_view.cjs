// Read-only visual check: the real controller socket remains owned by driver.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const base=process.env.WORKSHOP_URL||'http://127.0.0.1:8878';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 try{
  const health=await (await page.request.get(base+'/health')).json();
  if(health.state?.assembly?.scene_mode!=='physical_heap')throw Error('Not a heap scene');
  await page.routeWebSocket('**/ws',socket=>{
   socket.send(JSON.stringify(health.state));
   socket.onMessage(()=>{}); // Never forward commands or acquire robot control.
  });
  await page.goto(base+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.workshopState?.assembly?.scene_mode==='physical_heap');
  for(const [id,name] of [['view-heap','heap-view.png'],['view-fixture','fixture-view.png']]){
   await page.locator('#'+id).click();await page.waitForTimeout(1000);
   await page.screenshot({path:path.resolve(__dirname,'../outputs/clutter/'+name)});
  }
  if(errors.length)throw Error(errors.join('\n'));
  const report={read_only_snapshot:true,controller_socket_acquired:false,
   heap_camera:true,fixture_camera:true,errors,physical_execution_tested:false,
   captured_phase:health.state.assembly.phase};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/clutter/view-check.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
