const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',error=>errors.push(String(error)));
 try{
  await page.goto(process.env.WORKSHOP_URL||'http://127.0.0.1:8875/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.workshopModelCount>10&&window.workshopState?.seq>0,{},{timeout:45000});
  if(await page.evaluate(()=>window.workshopRobotVisualCount)<8)throw new Error('Missing robot visual meshes');
  if(await page.evaluate(()=>window.workshopState.wrist_camera)){
   const camera=await page.request.get(new URL('/wrist.jpg',page.url()).href);
   if(!camera.ok()||!(await camera.body()).length)throw new Error('Missing wrist RGB preview');
  }
  await page.locator('#reset').click();
  await page.waitForFunction(()=>window.workshopState.mode==='ready');
  await page.locator('#start').click();
  await page.waitForFunction(()=>window.workshopState.mode==='robot');
  await page.locator('#grab').click();
  await page.waitForTimeout(200);
  if(await page.evaluate(()=>window.workshopState.holding))throw new Error('Human stole robot-owned brick');
  await page.waitForFunction(()=>window.workshopState.mode==='human'&&window.workshopState.success,{},{timeout:120000});
  await page.locator('#grab').click();
  await page.waitForFunction(()=>window.workshopState.holding);
  await page.locator('#lift').click();
  await page.waitForFunction(()=>window.workshopState.brick[1]>.035,{},{timeout:10000});
  const lifted=await page.evaluate(()=>window.workshopState.brick[1]);
  const orientation=await page.evaluate(()=>window.workshopState.brick_rotation);
  await page.locator('#rotate').click();
  await page.waitForFunction(before=>Math.abs(window.workshopState.brick_rotation.reduce((sum,value,i)=>sum+value*before[i],0))<.9,orientation,{timeout:10000});
  await page.screenshot({path:path.resolve(__dirname,'../outputs/xr_desktop.png')});
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('Emulation.setScriptExecutionDisabled',{value:true});
  await new Promise(resolve=>setTimeout(resolve,700));
  await cdp.send('Emulation.setScriptExecutionDisabled',{value:false});
  await page.waitForFunction(()=>!window.workshopState.holding,{},{timeout:5000});
  await page.waitForFunction(()=>window.workshopState.brick[1]<.012,{},{timeout:10000});
  await page.locator('#reset').click();
  await page.waitForFunction(()=>window.workshopState.mode==='ready');
  await page.locator('#start').click();
  await page.waitForFunction(()=>window.workshopState.mode==='robot');
  await page.locator('#pause').click();
  await page.waitForFunction(()=>window.workshopState.mode==='paused_robot');
  const paused=await page.evaluate(()=>window.workshopState.sim_time);
  await page.waitForTimeout(400);
  const stillPaused=await page.evaluate(()=>window.workshopState.sim_time);
  if(Math.abs(paused-stillPaused)>1e-6)throw new Error('Paused physics continued advancing');
  if(errors.length)throw new Error(errors.join('\n'));
  const result={local_webxr_frontend_passed:true,mesh_count:await page.evaluate(()=>window.workshopModelCount),
   robot_delivery_passed:true,robot_ownership_rejection_passed:true,human_force_grab_passed:true,
   human_lift_height_m:lifted,tracking_timeout_passed:true,pause_passed:true,
   human_rotation_passed:true,robot_visual_meshes:await page.evaluate(()=>window.workshopRobotVisualCount),
   actual_quest_pro_tested:false,controller:await page.evaluate(()=>window.workshopState.controller),
   browser:'Microsoft Edge, desktop software rendering',errors};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/xr-software-check.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
