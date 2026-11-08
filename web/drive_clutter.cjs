const fs=require('fs'),path=require('path');
const port=process.env.ASSEMBLY_PORT||8878;
const socket=new WebSocket(`ws://127.0.0.1:${port}/ws`);
let started=false,last='';
const timer=setTimeout(()=>{socket.close();process.exitCode=1},3600000);
socket.onmessage=event=>{
 const state=JSON.parse(event.data),a=state.assembly;if(a?.scene_mode!=='physical_heap')return;
 if(!started){started=true;socket.send(JSON.stringify({seq:1,op:state.mode==='paused_robot'?'resume':'start'}))}
 const key=JSON.stringify([a.status,a.phase,a.active_skill,a.extracted_colors]);
 if(key!==last){last=key;console.log(JSON.stringify({status:a.status,phase:a.phase,extracted:a.extracted_colors,message:a.message}))}
 if(['failed','inspection_required','normalization_required','normalization_complete','complete'].includes(a.status)){
  fs.writeFileSync(path.resolve(__dirname,'../outputs/clutter/driver-result.json'),JSON.stringify(a,null,2));
  clearTimeout(timer);socket.close();if(!['normalization_required','normalization_complete','complete'].includes(a.status))process.exitCode=1;
 }
};
socket.onerror=e=>{console.error(e);clearTimeout(timer);process.exitCode=1};
