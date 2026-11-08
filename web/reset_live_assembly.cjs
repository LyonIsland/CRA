const port=process.env.ASSEMBLY_PORT||8878,seed=Number(process.env.ASSEMBLY_SEED||4200);
const socket=new WebSocket(`ws://127.0.0.1:${port}/ws`);
let sent=false;
const timer=setTimeout(()=>{socket.close();process.exitCode=1},30000);
socket.onmessage=event=>{
 const s=JSON.parse(event.data);if(!s.assembly_live)return;
 if(!sent){sent=true;socket.send(JSON.stringify({seq:1,op:'reset',seed}));return}
 if(s.assembly.seed===seed&&s.assembly.status==='ready'){
  console.log(JSON.stringify(s.assembly));clearTimeout(timer);socket.close();
 }
};
socket.onerror=error=>{console.error(error);clearTimeout(timer);process.exitCode=1};
