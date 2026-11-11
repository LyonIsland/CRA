// Read-only rendering/network regression. No controller ownership or motion.
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
(async()=>{
 const b=await chromium.launch({channel:'msedge',headless:true});const p=await b.newPage({viewport:{width:1600,height:1000}});
 let duplicatePolls=0,errors=[];p.on('request',r=>{if(r.url().includes('/assembly/api/live'))duplicatePolls++});p.on('pageerror',e=>errors.push(String(e)));
 try{
  await p.goto('http://127.0.0.1:8878/assembly?observe=1');const frame=p.frameLocator('#live-view');await frame.locator('#agent-board').waitFor();
  await frame.locator('[data-tab="manual"]').click();await frame.locator('#agent-pane summary').click();
  await frame.locator('#agent-pane iframe').waitFor();
  const f=p.frames().find(f=>f.url().includes('embedded=1'));
  await f.evaluate(()=>{window.boardMutations=0;new MutationObserver(()=>window.boardMutations++).observe(document.querySelector('#agent-pane'),{childList:true,subtree:true})});
  await p.waitForTimeout(4500);
  const measured=await f.evaluate(()=>({performance:window.workshopPerformance,board_mutations:window.boardMutations,manual_still_open:document.querySelector('#agent-pane details')?.open,manual_frames:document.querySelectorAll('#agent-pane iframe').length}));
  if(!measured.performance||measured.performance.render_fps>65||measured.performance.wrist_fps>22||duplicatePolls||errors.length||!measured.manual_still_open)throw Error(JSON.stringify({measured,duplicatePolls,errors}));
  const report={...measured,legacy_dashboard_polls:duplicatePolls,errors,physics_changed:false};
  fs.writeFileSync(path.resolve(__dirname,'../outputs/clutter_human/scene-performance-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
