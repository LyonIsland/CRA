// Real Isaac episode: reach assistance request, reject false completion, then test explicit human surrogate.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 const base=process.env.WORKSHOP_URL||'http://127.0.0.1:8878',out=path.resolve(__dirname,'../outputs/clutter_human');
 const state=()=>page.request.get(base+'/assembly/api/live').then(r=>r.json());
 let last='';async function waitFor(predicate,ms=600000){const end=Date.now()+ms;while(Date.now()<end){const d=await state();const key=JSON.stringify([d.robot_mode,d.state.phase,d.state.human_request?.id]);if(key!==last){last=key;console.log(key)}if(d.state.status==='failed')throw Error(d.state.message);if(predicate(d))return d;await page.waitForTimeout(500)}throw Error('Human workflow timeout')}
 try{
  await page.goto(base+'/assembly',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>!document.querySelector('#live-start').disabled);
  const frame=page.frameLocator('#live-view');
  if(await frame.locator('#view-fixture').isVisible())throw Error('Turning fixture control still visible');
  const model=await(await page.request.get(base+'/model')).json();
  if(model.objects.some(o=>/regripper/i.test(o.name)))throw Error('Turning fixture still in scene');
  await page.locator('#live-start').click();
  const waiting=await waitFor(d=>d.robot_mode==='waiting_human');
  const before=waiting.state.human_request;
  await page.waitForFunction(()=>!document.querySelector('#human-done').disabled);
  await page.screenshot({path:path.join(out,'human-request.png'),fullPage:true});
  await page.locator('#human-done').click();
  const rejected=await waitFor(d=>d.robot_mode==='waiting_human'&&d.state.human_request.id>before.id);
  console.log(JSON.stringify({false_confirmation_rejected:true,request:rejected.state.human_request}));
  await page.waitForFunction(()=>!document.querySelector('#human-simulate').disabled);
  await page.locator('#human-simulate').click();
  const verified=await waitFor(()=>{
   const files=fs.readdirSync(out).filter(f=>/^run_.*\.json$/.test(f));
   return files.some(f=>{const r=JSON.parse(fs.readFileSync(path.join(out,f),'utf8'));return r.human_assistance?.some(h=>h.completion_source==='simulated_human'&&h.RGB_verification_passed)})
  });
  if(verified.robot_mode==='robot')await page.locator('#live-pause').click();
  const report={no_turning_fixture:true,real_robot_retreat_and_wait:true,false_completion_rejected:true,
   explicit_simulated_human_action_RGB_reobserved:true,full_assembly_tested:false,errors};
  if(errors.length)throw Error(errors.join('\n'));
  fs.writeFileSync(path.join(out,'browser-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
