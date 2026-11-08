// Browser controls and display checks; physical builds are evaluated separately.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const base=process.env.WORKSHOP_URL||'http://127.0.0.1:8877';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 const state=()=>page.request.get(base+'/assembly/api/live').then(r=>r.json());
 async function waitStatus(predicate){for(let i=0;i<100;i++){const data=await state();if(predicate(data))return data;await page.waitForTimeout(200)}throw Error('Live state timed out')}
 try{
  await page.goto(base+'/assembly',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.liveAssemblyStatus?.available,{},{timeout:45000});
  await page.waitForFunction(()=>!document.querySelector('#live-reset').disabled,{},{timeout:45000});
  if(!await page.locator('#execution-status').isHidden())throw Error('Planning-only blocker shown in live mode');
  const initial=await state();
  await page.screenshot({path:path.resolve(__dirname,'../outputs/live_assembly/console.png'),fullPage:true});
  const pdf=await page.request.get(base+'/manual.pdf');
  if(!(await pdf.body()).subarray(0,4).equals(Buffer.from('%PDF')))throw Error('Manual PDF missing');
  await page.locator('#live-reset').click();
  const reset=await waitStatus(d=>d.state.status==='ready'&&d.state.completed_steps.length===0&&d.state.seed!==initial.state.seed);
  await page.locator('#live-start').click();
  await waitStatus(d=>d.robot_mode==='robot');
  await page.locator('#live-pause').click();await waitStatus(d=>d.robot_mode==='paused_robot');
  await page.locator('#live-start').click();await waitStatus(d=>d.robot_mode==='robot');
  await page.locator('#live-pause').click();await waitStatus(d=>d.robot_mode==='paused_robot');
  await page.locator('#live-reset').click();await waitStatus(d=>d.state.status==='ready'&&d.state.seed!==reset.state.seed);
  if(errors.length)throw Error(errors.join('\n'));
  const report={embedded_live_view:true,manual_pdf:true,parent_start_pause_resume_reset:true,
   initial_state:initial.state,random_reset_seed:reset.state.seed,errors,physical_build_tested:false};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/live_assembly/browser-check.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
