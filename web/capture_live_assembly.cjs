const {chromium}=require('playwright');
const path=require('path'),fs=require('fs');
(async()=>{
 const base=process.env.WORKSHOP_URL||'http://127.0.0.1:8877';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 try{
  await page.goto(base+'/assembly',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.liveAssemblyStatus?.state?.status==='complete',{},{timeout:45000});
  const frame=page.frameLocator('#live-view');
  await frame.locator('#view-assembly').click();
  await page.waitForTimeout(1000);
  if(errors.length)throw Error(errors.join('\n'));
  await page.screenshot({path:path.resolve(__dirname,'../outputs/live_assembly/final-console.png'),fullPage:true});
  await page.locator('#live-view').screenshot({path:path.resolve(__dirname,'../outputs/live_assembly/final-closeup.png')});
  const data=await page.evaluate(()=>window.liveAssemblyStatus);
  if(data.state.physical_assembly_completed!==false)throw Error('Incorrect physical snap-fit claim');
  const report={rendered_complete_steps:data.state.completed_steps,broken_connections:data.state.broken_connections,
   near_view_button:true,browser_errors:errors,physics_state:data.state};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/live_assembly/completed-browser.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
