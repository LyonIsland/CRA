// Real browser generation and policy-file surface check. Does not train or move.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const origin=process.env.BRICKLAB_URL||'http://127.0.0.1:18110';
 const out=path.resolve(__dirname,'../outputs/bricklab/browser-check');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  // This check covers generation/finite inspection; the separate workspace
  // check exercises a real persistent session and physical joint commands.
  await page.context().route('**/workspace/*/start',route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'Persistent runtime is covered by check_bricklab_workspace.cjs'})}));
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.locator('#import-file').setInputFiles(path.resolve(__dirname,'../assets/manuals/bricklab_camera_wall/model.json'));
  await page.waitForFunction(()=>document.querySelector('#stat-pieces')?.textContent.trim()==='6');
  await page.locator('#workflow-generate').click();
  await page.locator('#workflow-dialog-mode').selectOption('steps');
  const responsePromise=page.waitForResponse(r=>r.url()===origin+'/api/jobs'&&r.request().method()==='POST');
  const autoPopup=page.waitForEvent('popup');
  await page.locator('#workflow-submit').click();
  const response=await responsePromise;assert.equal(response.status(),202);const submitted=await response.json();
  await page.waitForFunction(()=>document.querySelector('#workflow-job')?.dataset.status==='prepared',null,{timeout:90000});
  await page.locator('#workflow-environment').scrollIntoViewIfNeeded();
  assert(await page.locator('#workflow-pdf').isVisible());
  await page.screenshot({path:path.join(out,'generated-task.png'),fullPage:true});
  const link=await page.locator('#workflow-environment').getAttribute('href');assert(link.includes('/workspace/'));
  const taskPage=await autoPopup;await taskPage.waitForURL('**/workspace/**');
  await taskPage.goto(origin+'/training/'+submitted.job_id,{waitUntil:'networkidle'});
  assert(await taskPage.locator('#inspect').isVisible());
  assert((await taskPage.locator('iframe').getAttribute('src')).includes('/policy/manual.pdf'));
  const denied=await page.request.get(origin+'/files/'+submitted.job_id+'/task/evaluation/manual-page-map.json');assert.equal(denied.status(),404);
  if(process.argv.includes('--inspect')){
   await taskPage.locator('#inspect').click();
   await taskPage.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('相机检查完成'),null,{timeout:150000});
   await taskPage.waitForFunction(()=>{const image=document.querySelector('#frame');return !image.hidden&&image.complete&&image.naturalWidth>0;});
   assert(await taskPage.locator('#frame').isVisible());
  }
  await taskPage.screenshot({path:path.join(out,'training-task.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  const result={job_id:submitted.job_id,url:link,browser_errors:errors,private_evaluation_http_status:denied.status(),physical_success_evaluated:false};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
