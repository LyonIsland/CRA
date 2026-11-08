// Verify completed rendering first, then explicitly test reset/start/pause/resume.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const base=process.env.WORKSHOP_URL||'http://127.0.0.1:8878';
 const out=path.resolve(__dirname,'../outputs/clutter');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 const state=()=>page.request.get(base+'/assembly/api/live').then(r=>r.json());
 async function waitStatus(predicate){for(let i=0;i<150;i++){const d=await state();if(predicate(d))return d;await page.waitForTimeout(200)}throw Error('Control state timeout')}
 try{
  await page.goto(base+'/assembly',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.liveAssemblyStatus?.state?.heap_to_assembly_completed,{},{timeout:45000});
  await page.waitForFunction(()=>!document.querySelector('#live-reset').disabled);
  const completed=await state(),view=page.frameLocator('#live-view');
  if(completed.state.normalized_colors.length!==6||completed.state.completed_steps.length!==6||completed.state.joint_count!==9)throw Error('Incomplete physical episode');
  if(completed.state.physical_assembly_completed!==false)throw Error('Incorrect plastic snap-fit claim');
  await view.locator('#view-assembly').click();await page.waitForTimeout(1000);
  await page.screenshot({path:path.join(out,'completed-console.png'),fullPage:true});
  await page.locator('#live-view').screenshot({path:path.join(out,'completed-closeup.png')});
  const pdf=await page.request.get(base+'/manual.pdf');if(!(await pdf.body()).subarray(0,4).equals(Buffer.from('%PDF')))throw Error('Manual missing');
  await page.locator('#live-reset').click();
  const reset=await waitStatus(d=>d.state.status==='ready'&&d.state.seed!==completed.state.seed);
  if(reset.state.scene_mode!=='physical_heap'||reset.state.normalized_colors.length||reset.state.completed_steps.length||reset.state.joint_count)throw Error('Reset did not restore heap mode');
  const scene=JSON.parse(fs.readFileSync(path.join(out,`scene_${reset.state.seed}.json`),'utf8'));
  if(scene.part_count!==8||Object.values(scene.parts).some(p=>p.position_m[2]<.001||p.position_m[2]>.10))throw Error('Reset bodies did not settle on table');
  await page.locator('#live-start').click();await waitStatus(d=>d.robot_mode==='robot');
  await page.locator('#live-pause').click();await waitStatus(d=>d.robot_mode==='paused_robot');
  await page.locator('#live-start').click();await waitStatus(d=>d.robot_mode==='robot');
  await page.locator('#live-pause').click();await waitStatus(d=>d.robot_mode==='paused_robot');
  await page.locator('#live-reset').click();await waitStatus(d=>d.state.status==='ready'&&d.state.seed!==reset.state.seed);
  if(errors.length)throw Error(errors.join('\n'));
  const report={completed_state:completed.state,manual_pdf:true,rendered_complete:true,
   reset_to_settled_eight_piece_heap:true,start_pause_resume:true,errors,
   physical_task_audited_separately:'acceptance.json'};
  fs.writeFileSync(path.join(out,'completed-controls-check.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({rendered_complete:true,reset_heap:true,start_pause_resume:true,errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
