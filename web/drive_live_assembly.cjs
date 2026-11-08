const fs=require('fs'),path=require('path');
const port=process.env.ASSEMBLY_PORT||8878;
const output=process.env.ASSEMBLY_RESULT||path.resolve(__dirname,'../outputs/live_assembly/driver-result.json');
const requestedSeed=process.env.ASSEMBLY_SEED===undefined?null:Number(process.env.ASSEMBLY_SEED);
let seq=0,last='',started=false,resetSent=false;
const socket=new WebSocket(`ws://127.0.0.1:${port}/ws`);
const timer=setTimeout(()=>{console.error('Live assembly timed out');socket.close();process.exitCode=1},900000);
socket.onmessage=event=>{
 const state=JSON.parse(event.data);if(!state.assembly_live)return;
 const assembly=state.assembly;
 if(!started){
  if(requestedSeed!==null&&!resetSent){resetSent=true;socket.send(JSON.stringify({seq:++seq,op:'reset',seed:requestedSeed}));return}
  if(requestedSeed!==null&&(assembly.seed!==requestedSeed||assembly.status!=='ready'))return;
  started=true;socket.send(JSON.stringify({seq:++seq,op:'start'}));
 }
 const key=JSON.stringify([assembly.status,assembly.current_step,assembly.phase,assembly.completed_steps]);
 if(key!==last){last=key;console.log(JSON.stringify({step:assembly.current_step,phase:assembly.phase,completed:assembly.completed_steps,message:assembly.message}))}
 if(['complete','failed'].includes(assembly.status)){
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(assembly,null,2));
  clearTimeout(timer);socket.close();if(assembly.status==='failed')process.exitCode=1;
 }
};
socket.onerror=error=>{console.error(error);clearTimeout(timer);process.exitCode=1};
