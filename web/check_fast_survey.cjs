// One real scan in an isolated simulator, without running the full build.
const fs=require('fs'),path=require('path');
const socket=new WebSocket(`ws://127.0.0.1:${process.env.ASSEMBLY_PORT||8879}/ws`);
let started=false,seq=0,pausing=false,sawFit=false,last='';
const timeout=setTimeout(()=>{socket.close();process.exitCode=1},300000);
socket.onmessage=e=>{
 const s=JSON.parse(e.data),a=s.assembly;if(!a)return;
 if(!started){started=true;socket.send(JSON.stringify({seq:++seq,op:'start'}))}
 if(a.phase==='heap_fit')sawFit=true;
 const key=JSON.stringify([a.phase,a.survey_progress?.views_completed,a.survey_progress?.pieces_completed]);
 if(last!==key){last=key;console.log(key)}
 if(a.status==='failed'){console.error(a.message);clearTimeout(timeout);socket.close();process.exitCode=1;return}
 if(a.heap_observation?.view_count>=3&&a.active_skill!=='survey'&&!pausing){pausing=true;socket.send(JSON.stringify({seq:++seq,op:'pause'}))}
 if(pausing&&s.mode==='paused_robot'){
  const folder=path.resolve(__dirname,'../outputs/clutter_human');
  const report=JSON.parse(fs.readFileSync(path.join(folder,`run_${a.seed}.json`),'utf8'));
  const scan=report.survey_metrics[0];
  if(!sawFit||scan.views_completed!==scan.views_total||scan.route_m>scan.original_route_m+1e-9||scan.pieces_completed!==scan.pieces_total)throw Error('Incomplete scan');
  const result={real_Isaac_survey:true,progress_published_between_piece_fits:sawFit,survey:scan,observed_pieces:a.heap_observation.pieces.length,max_grasp_retries:a.max_grasp_retries,full_build_tested:false};
  fs.writeFileSync(path.join(folder,'fast-survey-check.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));clearTimeout(timeout);socket.close();
 }
};
socket.onerror=e=>{console.error(e);clearTimeout(timeout);process.exitCode=1};
