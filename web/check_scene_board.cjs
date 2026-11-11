// Read-only UI validation against the running simulator; never sends motion commands.
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
(async()=>{
 const b=await chromium.launch({channel:'msedge',headless:true});
 const p=await b.newPage({viewport:{width:1600,height:1000}}),errors=[];let sockets=0;
 p.on('pageerror',e=>errors.push(String(e)));p.on('websocket',()=>sockets++);
 try{
  await p.goto('http://127.0.0.1:8878/assembly?observe=1');
  const frame=p.frameLocator('#live-view');await frame.locator('#agent-board').waitFor({state:'visible'});
  const bounds=await p.locator('#live-view').boundingBox();if(bounds.width<1590||bounds.height<990)throw Error('Scene is not fullscreen');
  const f=p.frames().find(f=>f.url().includes('embedded=1'));
  await f.waitForFunction(()=>window.workshopRobotVisualCount>=6&&!!window.workshopState,{},{timeout:30000});
  if(!await f.evaluate(()=>window.workshopRobotVisualCount>=6&&!!window.workshopState))throw Error('No actual robot state');
  for(const id of ['behavior-now','behavior-next','behavior-why']){
   await frame.locator('#'+id).waitFor({state:'visible'});
   if(!(await frame.locator('#'+id).innerText()).trim())throw Error('Empty behavior explanation: '+id);
  }
  for(const tab of ['execution','decision','checks','human','manual']){
   await frame.locator(`[data-tab="${tab}"]`).click();
   if(!await frame.locator(`[data-tab="${tab}"]`).getAttribute('aria-selected').then(v=>v==='true'))throw Error('Tab did not activate');
   if(!(await frame.locator('#agent-pane').innerText()).trim())throw Error('Empty tab '+tab);
   if(!await frame.locator('#behavior-now').isVisible())throw Error('Behavior explanation disappeared with tab switch');
  }
  if(await frame.locator('#agent-pane iframe').count())throw Error('Manual loaded before expansion');
  await frame.locator('#agent-pane summary').click();await frame.locator('#agent-pane iframe').waitFor();
  await frame.locator('[data-tab="human"]').click();
  for(const button of await frame.locator('#agent-pane button').all())if(!await button.isDisabled())throw Error('Observer action enabled');
  await frame.locator('[data-tab="decision"]').click();
  const out=path.resolve(__dirname,'../outputs/clutter_human');fs.mkdirSync(out,{recursive:true});
  await p.screenshot({path:path.join(out,'scene-board.png')});
  await frame.locator('#board-collapse').click();if(await frame.locator('#board-body').isVisible())throw Error('Collapse failed');
  await frame.locator('#board-collapse').click();
  const pageSize=await p.evaluate(()=>({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}));
  if(pageSize.width>1600||pageSize.height>1000)throw Error('Outer page scrolls');
  await p.setViewportSize({width:560,height:850});await p.waitForTimeout(300);
  await p.screenshot({path:path.join(out,'scene-board-mobile.png')});
  if(errors.length||sockets)throw Error(JSON.stringify({errors,sockets}));
  const report={fullscreen_scene:true,live_robot:true,tabs:5,collapsible:true,lazy_manual:true,observer_controls_disabled:true,websocket_count:sockets,errors,physics_changed:false};
  fs.writeFileSync(path.join(out,'scene-board-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
