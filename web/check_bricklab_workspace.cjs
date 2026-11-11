// Full model -> manual -> persistent Isaac workspace -> physical joint command.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const origin=process.env.BRICKLAB_URL||'http://127.0.0.1:18110',out=path.resolve(__dirname,'../outputs/bricklab/workspace-check');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});let taskPage,workspace;
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.locator('#import-file').setInputFiles(path.resolve(__dirname,'../assets/manuals/bricklab_camera_wall/model.json'));
  await page.waitForFunction(()=>document.querySelector('#stat-pieces')?.textContent.trim()==='6');
  await page.locator('#workflow-generate').click();
  const popup=page.waitForEvent('popup');
  await page.locator('#workflow-submit').click();
  taskPage=await popup;taskPage.on('pageerror',e=>errors.push(e.message));
  await taskPage.waitForURL('**/workspace/**',{timeout:90000});
  workspace=taskPage.url();
  await taskPage.waitForFunction(()=>document.querySelector('#record')&&!document.querySelector('#record').disabled,null,{timeout:150000});
  const job=new URL(workspace).pathname.split('/').pop();
  const status=async()=>{const r=await taskPage.request.get(workspace+'/status');assert.equal(r.status(),200);return r.json();};
  const first=await status();assert.equal(first.part_count,6);assert.equal(first.manual_page_count,8);assert.equal(first.scene_state_to_policy,false);
  assert(await taskPage.locator('#start-policy').isDisabled());
  const rejected=await taskPage.request.post(workspace+'/command',{data:{op:'start_policy'}});assert.equal(rejected.status(),409);
  await taskPage.locator('#manual-controls').evaluate(e=>e.open=true);
  await taskPage.locator('#record').click();
  await taskPage.waitForFunction(()=>document.querySelector('#robot-panel').classList.contains('recording'));
  assert(!(await taskPage.locator('#viewer').isVisible()));assert(await taskPage.locator('#wrist').isVisible());
  await taskPage.locator('.joint button[data-axis="0"][data-sign="1"]').click();
  await taskPage.waitForFunction(()=>!document.querySelector('#save').disabled);
  let stepped=await status();assert.equal(stepped.executed_steps,1);assert.equal(stepped.recorded_steps,1);
  assert(stepped.matrices.some((matrix,i)=>matrix.some((value,j)=>Math.abs(value-first.matrices[i][j])>1e-7)));
  await taskPage.locator('#save').click();
  await taskPage.waitForFunction(()=>document.querySelector('#record-status').textContent.includes('已保存 1 条'));
  await taskPage.screenshot({path:path.join(out,'workspace.png'),fullPage:true});
  const final=await status();assert.deepEqual(errors,[]);
  const result={job_id:job,workspace,browser_errors:errors,part_count:final.part_count,pages:final.manual_page_count,
   executed_steps:final.executed_steps,physical_transforms_changed:true,demonstration:final.saved_demonstrations[0],
   unavailable_policy_rejected:true,physical_assembly_completed:final.physical_assembly_completed};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{
  if(workspace&&taskPage)await taskPage.request.post(workspace+'/stop').catch(()=>{});
  await browser.close();
 }
})().catch(error=>{console.error(error);process.exit(1);});
