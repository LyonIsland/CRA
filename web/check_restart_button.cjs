// UI command contract with a simulated socket; does not reset the live experiment.
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage();
 const health=await(await page.request.get('http://127.0.0.1:8878/health')).json();
 const completed=structuredClone(health.state);completed.mode='done';completed.assembly.status='complete';completed.assembly.phase='complete';
 const commands=[],errors=[];let peer;page.on('pageerror',e=>errors.push(String(e)));
 await page.routeWebSocket('**/ws',ws=>{peer=ws;ws.onMessage(message=>commands.push(JSON.parse(message).op));ws.send(JSON.stringify(completed))});
 try{
  await page.goto('http://127.0.0.1:8878/?embedded=1');await page.locator('#restart:enabled').waitFor();
  await page.locator('#restart').click();await page.waitForTimeout(200);
  if(JSON.stringify(commands)!==JSON.stringify(['reset','start']))throw Error('Restart commands are not ordered: '+commands);
  if(!await page.locator('#restart').isDisabled())throw Error('Duplicate restart is allowed');
  peer.send(JSON.stringify({...completed,seq:completed.seq+2}));await page.waitForTimeout(100);
  if(!await page.locator('#restart').isDisabled())throw Error('Stale completion acknowledges restart');
  const next=structuredClone(completed);next.seq+=4;next.mode='robot';next.assembly.seed++;next.assembly.status='running';next.assembly.phase='heap_survey';next.assembly.completed_steps=[];next.assembly.normalized_colors=[];
  peer.send(JSON.stringify(next));await page.locator('#restart:enabled').waitFor();
  if(await page.locator('#restart').innerText()!=='重新开始'||errors.length)throw Error(JSON.stringify(errors));
  const report={completed_state_restart_visible:true,commands,duplicate_click_blocked:true,stale_ack_ignored:true,new_episode_acknowledged:true,live_scene_reset:false,errors};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/clutter_human/restart-button-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
