// Actual Isaac episode; no synthetic human completion command is sent.
const fs=require('fs'),path=require('path');
const out=path.resolve(__dirname,'../outputs/clutter_human');
const socket=new WebSocket('ws://127.0.0.1:8878/ws');
let seq=0,started=false,paused=false,last='';
const send=op=>socket.send(JSON.stringify({seq:++seq,op}));
const timer=setTimeout(()=>{console.error('Automatic collaboration timeout');socket.close();process.exitCode=1},600000);
socket.onmessage=event=>{
 const s=JSON.parse(event.data),a=s.assembly;if(!a)return;
 if(!started){started=true;if(!a.simulated_human?.enabled){throw Error('Auto human is disabled')}send(s.mode==='paused_robot'?'resume':'start')}
 const key=JSON.stringify([s.mode,a.phase,a.simulated_human?.phase,a.human_request?.id]);
 if(key!==last){last=key;console.log(key)}
 if(a.status==='failed'){console.error(a.message);clearTimeout(timer);socket.close();process.exitCode=1;return}
 const events=a.human_activity||[];
 if(!paused&&events.some(e=>e.event==='robot_verified')){paused=true;send('pause')}
 if(paused&&['paused_robot','paused_human'].includes(s.mode)){
  const report=JSON.parse(fs.readFileSync(path.join(out,`run_${a.seed}.json`),'utf8'));
  if(!report.human_assistance.some(h=>h.completion_source==='automatic_simulated_human'&&h.RGB_verification_passed))throw Error('No verified automatic assistance');
  if(report.robot_body_pose_writes_after_reset!==0||report.simulated_human_pose_writes<1)throw Error('Invalid action provenance');
  const result={automatic_response:true,no_manual_completion_command:true,RGB_reobservation_verified:true,
   automatic_action_count:report.simulated_human_pose_writes,robot_body_pose_writes:0,full_assembly_tested:false,seed:a.seed};
  fs.writeFileSync(path.join(out,'auto-human-check.json'),JSON.stringify(result,null,2));
  fs.copyFileSync(path.join(out,`run_${a.seed}.json`),path.join(out,`accepted-auto-human-${a.seed}.json`));
  console.log(JSON.stringify(result));clearTimeout(timer);socket.close();
 }
};
socket.onerror=e=>{console.error(e);clearTimeout(timer);process.exitCode=1};
