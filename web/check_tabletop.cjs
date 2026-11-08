const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 const result={actual_quest_pro_tested:false,errors};
 try{
  await page.goto(process.env.WORKSHOP_URL||'http://127.0.0.1:8876/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.workshopState?.tabletop&&window.workshopModelCount===23,{},{timeout:60000});
  const beforeSeq=await page.evaluate(()=>window.workshopState.seq);
  await page.locator('#randomize').click();
  await page.waitForFunction(seq=>window.workshopState.mode==='ready'&&window.workshopState.seq>seq&&window.workshopState.message.includes('\u4f4d\u7f6e\u5df2\u8bbe\u7f6e'),beforeSeq);
  await page.waitForTimeout(250);
  const source=await page.evaluate(()=>window.workshopState.brick);
  await page.locator('#start').click();await page.waitForFunction(()=>window.workshopState.mode==='robot');
  const after=await page.evaluate(()=>window.workshopState.brick);
  if(Math.hypot(source[0]-after[0],source[2]-after[2])>.003)throw new Error('Start reset user-authored source');
  result.start_preserves_placed_brick=true;
  await page.locator('#pause').click();await page.waitForFunction(()=>window.workshopState.mode==='paused_robot');
  const time=await page.evaluate(()=>window.workshopState.sim_time);await page.waitForTimeout(350);
  if(Math.abs(await page.evaluate(()=>window.workshopState.sim_time)-time)>1e-6)throw new Error('Pause advanced physics');
  await page.locator('#start').click();await page.waitForFunction(()=>window.workshopState.mode==='robot');
  await page.waitForFunction(()=>['human','paused'].includes(window.workshopState.mode),{},{timeout:180000});
  if(!await page.evaluate(()=>window.workshopState.success))throw new Error(await page.evaluate(()=>window.workshopState.message));
  result.randomized_delivery_passed=true;result.pause_resume_passed=true;
  async function clickXY(x,y){
   const p=await page.evaluate(async({x,y})=>{const THREE=await import('/vendor/three.module.js');const c=new THREE.PerspectiveCamera(55,innerWidth/innerHeight,.01,30);c.position.set(.65,1.35,1.05);c.lookAt(0,.91,.25);c.updateMatrixWorld();const v=new THREE.Vector3(-y,.7548,x).project(c);return {x:(v.x+1)*innerWidth/2,y:(1-v.y)*innerHeight/2}},{x,y});
   await page.mouse.click(p.x,p.y);
  }
  await page.locator('#set-goal').click();await clickXY(.28,.12);
  await page.waitForFunction(()=>Math.abs(window.workshopState.goal[0]+.12)<.002&&Math.abs(window.workshopState.goal[2]-.28)<.002);
  result.specified_destination_passed=true;
  await page.locator('#place').click();await clickXY(.18,.24);
  await page.waitForFunction(()=>Math.abs(window.workshopState.brick[0]+.24)<.002&&Math.abs(window.workshopState.brick[2]-.18)<.002);
  result.click_to_place_passed=true;
  await page.locator('#start').click();await page.waitForFunction(()=>window.workshopState.mode==='robot');
  await page.waitForFunction(()=>['human','paused'].includes(window.workshopState.mode),{},{timeout:180000});
  if(!await page.evaluate(()=>window.workshopState.success))throw new Error(await page.evaluate(()=>window.workshopState.message));
  result.user_placed_delivery_to_changed_goal_passed=true;
  const beforeRejected=await page.evaluate(()=>window.workshopState.brick);
  await page.locator('#place').click();await clickXY(.6,-.3);
  await page.waitForFunction(()=>window.workshopState.message.includes('\u8d85\u51fa'));
  const rejected=await page.evaluate(()=>window.workshopState.brick);
  if(Math.hypot(beforeRejected[0]-rejected[0],beforeRejected[2]-rejected[2])>.003)throw new Error('Unreachable placement moved the brick');
  result.unreachable_placement_rejected=true;
  const response=await page.request.get(new URL('/wrist.jpg',page.url()).href);
  if(!response.ok()||!(await response.body()).length)throw new Error('Missing live wrist preview');
  result.wrist_preview_passed=true;
  await page.screenshot({path:path.resolve(__dirname,'../outputs/tabletop/browser.png')});
  if(errors.length)throw new Error(errors.join('\n'));
  fs.writeFileSync(path.resolve(__dirname,'../outputs/tabletop/browser-check.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
