const {chromium}=require('playwright'),path=require('path');
(async()=>{
 const base=process.env.WORKSHOP_URL||'http://127.0.0.1:8877';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 try{
  await page.goto(base+'/assembly',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.liveAssemblyStatus?.state?.status==='ready'&&window.liveAssemblyStatus.state.random_yaw,{},{timeout:45000});
  await page.waitForFunction(()=>!document.querySelector('#live-start').disabled,{},{timeout:45000});
  await page.waitForTimeout(600);
  if(errors.length)throw Error(errors.join('\n'));
  await page.screenshot({path:path.resolve(__dirname,'../outputs/live_assembly/scattered-console.png'),fullPage:true});
  await page.locator('#live-view').screenshot({path:path.resolve(__dirname,'../outputs/live_assembly/scattered-layout.png')});
  console.log(JSON.stringify({ready:true,random_yaw:true,start_enabled:true,errors}));
 }catch(error){
  console.error(JSON.stringify({errors,frames:await Promise.all(page.frames().map(f=>f.evaluate(()=>({url:location.href,status:document.querySelector('#status')?.textContent,error:document.querySelector('#error')?.textContent,state:window.workshopState?.assembly})).catch(()=>null)))}));
  throw error;
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
