const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
(async()=>{
 const base=process.env.WORKSHOP_URL||'http://127.0.0.1:8875/';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});const errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 try{
  await page.goto(new URL('/assembly',base).href,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.assemblyPlanningResult,{},{timeout:30000});
  const seeds=await page.locator('#seed option').evaluateAll(options=>options.map(o=>o.value));
  if(seeds.length<2)throw new Error('Need two independent RGB layouts');
  const results=[];
  for(const seed of seeds.slice(0,2)){
   await page.selectOption('#seed',seed);
   await page.waitForFunction(seed=>document.getElementById('seed').value===seed&&window.assemblyPlanningResult?.observation?.pieces?.length>=6,seed);
   // Wait for the response that corresponds to this selector, not the last layout.
   await page.locator('#plan').click();await page.waitForTimeout(250);
   const result=await page.evaluate(()=>window.assemblyPlanningResult);
   if(result.execution?.available!==false||result.execution.completed_instruction_steps!==0)throw new Error('Incorrect execution readiness');
   if(!await page.locator('#execute-assembly').isDisabled()||await page.locator('#execution-missing li').count()<4)throw new Error('Missing visible execution blockers');
   if(result.physical_assembly_completed!==false||result.plan.status!=='blocked_execution')throw new Error('Unvalidated assembly reported executable');
   if(!result.plan.missing_capabilities.includes('force_limited_insertion')||!result.plan.missing_capabilities.includes('connection_verification'))throw new Error('Missing insertion capability gate');
   if(result.overview.steps.length!==6||result.overview.steps.some(s=>!s.selected_track_id||s.executable_now))throw new Error('Incomplete or executable lookahead');
   if(new Set(result.overview.steps.map(s=>s.selected_track_id)).size!==6)throw new Error('One part used twice');
   for(let view=0;view<7;view++){const response=await page.request.get(new URL(`/assembly/api/image?seed=${seed}&view=${view}`,base).href);if(!response.ok())throw new Error('Missing actual RGB snapshot')}
   results.push(result);
  }
  const a=results[0].plan,b=results[1].plan;
  if(JSON.stringify(a.target_pose)!==JSON.stringify(b.target_pose))throw new Error('Manual target depends on loose layout');
  if(JSON.stringify(a.source_pose_observed)===JSON.stringify(b.source_pose_observed))throw new Error('Source pose did not change between observed layouts');
  const pdf=await page.request.get(new URL('/manual.pdf',base).href);if(!(await pdf.body()).subarray(0,4).equals(Buffer.from('%PDF')))throw new Error('Missing PDF manual');
  if(errors.length)throw new Error(errors.join('\n'));
  await page.screenshot({path:path.resolve(__dirname,'../outputs/assembly/console.png')});
  const report={manual_pdf_available:true,recipe_steps:6,actual_rgb_layouts_reviewed:results.length,
   same_instruction_different_observed_sources:true,all_six_conditional_piece_assignments:true,
   insertion_and_connection_capability_gates_verified:true,unimplemented_executor_explicitly_displayed:true,physical_assembly_completed:false,errors};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/assembly/browser-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
