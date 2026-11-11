import * as THREE from 'three';
import {createAgentBoard} from './agent-board.js?v=survey-2';

const $=id=>document.getElementById(id);
const renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setSize(innerWidth,innerHeight);renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));
renderer.xr.enabled=true;renderer.setClearColor(0x101923);
document.body.appendChild(renderer.domElement);
const scene=new THREE.Scene();
scene.add(new THREE.HemisphereLight(0xe7f1ff,0x39414b,2));
const sunlight=new THREE.DirectionalLight(0xffffff,2.5);sunlight.position.set(-1,3,2);scene.add(sunlight);
const table=new THREE.Group();table.position.y=.75;table.visible=false;scene.add(table);
const humanTarget=new THREE.Mesh(new THREE.RingGeometry(.022,.026,40),new THREE.MeshBasicMaterial({color:0x37e577,side:THREE.DoubleSide}));
humanTarget.rotation.x=-Math.PI/2;humanTarget.visible=false;table.add(humanTarget);
const humanSource=new THREE.Mesh(new THREE.RingGeometry(.019,.022,40),new THREE.MeshBasicMaterial({color:0xffbf36,side:THREE.DoubleSide}));
humanSource.rotation.x=-Math.PI/2;humanSource.visible=false;table.add(humanSource);
const floor=new THREE.Mesh(new THREE.PlaneGeometry(6,6),new THREE.MeshStandardMaterial({color:0x172330}));floor.rotation.x=-Math.PI/2;scene.add(floor);
scene.add(new THREE.GridHelper(6,30,0x4a6277,0x25394a));
const camera=new THREE.PerspectiveCamera(55,innerWidth/innerHeight,.01,30);
const rig=new THREE.Group();scene.add(rig);rig.add(camera);
function desktopCamera(){rig.position.set(0,0,0);rig.rotation.set(0,0,0);camera.position.set(.65,1.35,1.05);camera.lookAt(0,.91,.25)}
desktopCamera();
$('view-overview').onclick=()=>{if(!renderer.xr.isPresenting)desktopCamera()};
$('view-assembly').onclick=()=>{if(renderer.xr.isPresenting)return;rig.position.set(0,0,0);rig.rotation.set(0,0,0);camera.position.set(.10,.98,.53);camera.lookAt(-.084,.765,.274)};
$('view-heap').onclick=()=>{if(renderer.xr.isPresenting)return;rig.position.set(0,0,0);rig.rotation.set(0,0,0);camera.position.set(.39,1.02,.53);camera.lookAt(.125,table.position.y+.015,.275)};
$('view-fixture').onclick=()=>{if(renderer.xr.isPresenting)return;rig.position.set(0,0,0);rig.rotation.set(0,0,0);camera.position.set(.20,.99,.51);camera.lookAt(0,table.position.y+.04,.30)};
const pointer=new THREE.Mesh(new THREE.SphereGeometry(.012,16,12),new THREE.MeshStandardMaterial({color:0xffc86b}));table.add(pointer);pointer.position.set(.07,.08,.32);
const controllers=[0,1].map(i=>{const c=renderer.xr.getControllerGrip(i);rig.add(c);c.add(new THREE.Mesh(new THREE.SphereGeometry(.012,12,10),new THREE.MeshStandardMaterial({color:i?0xffc86b:0x6db8ff})));c.addEventListener('connected',e=>c.userData.source=e.data);c.addEventListener('disconnected',()=>{c.userData.source=null;send('release')});return c});
const banner=document.createElement('canvas');banner.width=1024;banner.height=256;const ctx=banner.getContext('2d');
function setBanner(message){ctx.fillStyle='#142131';ctx.fillRect(0,0,1024,256);ctx.fillStyle='#e8f2ff';ctx.font='bold 42px sans-serif';ctx.fillText('PIPER / ISAAC SIM',30,60);ctx.font='28px sans-serif';ctx.fillText(message.slice(0,65),30,120);ctx.fillText('Right A: start   B: pause   Grip: grab   Left X: reset',30,190);bannerTexture.needsUpdate=true}
const bannerTexture=new THREE.CanvasTexture(banner);const sign=new THREE.Mesh(new THREE.PlaneGeometry(.64,.16),new THREE.MeshBasicMaterial({map:bannerTexture,side:THREE.DoubleSide}));sign.position.set(-.3,1.15,.05);scene.add(sign);setBanner('Connecting...');
const observerMode=new URLSearchParams(location.search).get('observe')==='1';
let state=null,seq=0,connected=false,socket=null,lastHand=0,desktopHolding=false,desktopYaw=0;
let restartPending=null;
$('restart').onclick=()=>{
 if(observerMode||!connected||!state?.assembly_live||restartPending)return;
 restartPending={seed:state.assembly.seed};desktopHolding=false;
 $('restart').disabled=true;$('restart').textContent='正在重新开始…';
 $('status').textContent='正在清空本轮进度并重新布置零件，随后自动开始。';
 // WebSocket preserves order: backend finishes reset before processing start.
 send('reset');send('start');
};
const agentBoard=createAgentBoard(op=>{
 if(observerMode||!connected||socket?.readyState!==WebSocket.OPEN)return;
 socket.send(JSON.stringify({seq:++seq,op,request_id:state?.assembly?.human_request?.id}));
});
const meshes=[];const previousButtons=new Map();const keyboard=new Set();let lastTime=performance.now();
// Render between authoritative snapshots rather than jumping at network frequency.
const snapshots=[];
let sourcePeriod=60,interpolationDelay=120,lastSceneRender=0,lastWristRender=0;
const blendPosition=new THREE.Vector3(),blendRotation=new THREE.Quaternion(),blendScale=new THREE.Vector3();
function receiveTransforms(matrices){
 const now=performance.now(),previous=snapshots.at(-1);
 if(previous){const interval=now-previous.time;if(interval>0&&interval<1000)sourcePeriod=.9*sourcePeriod+.1*interval;}
 interpolationDelay=.9*interpolationDelay+.1*Math.min(250,Math.max(100,sourcePeriod*1.5));
 const poses=matrices.map(values=>{const p=new THREE.Vector3(),q=new THREE.Quaternion(),s=new THREE.Vector3();new THREE.Matrix4().fromArray(values).decompose(p,q,s);return {p,q,s}});
 snapshots.push({time:performance.now(),poses});if(snapshots.length>12)snapshots.shift();
}
function animateTransforms(now){
 if(!snapshots.length)return;
 const time=now-interpolationDelay;
 while(snapshots.length>2&&snapshots[1].time<=time)snapshots.shift();
 const a=snapshots[0],b=snapshots[1]||a;
 const alpha=b.time>a.time?THREE.MathUtils.clamp((time-a.time)/(b.time-a.time),0,1):1;
 for(let i=0;i<meshes.length;i++){
  const x=a.poses[i],y=b.poses[i];
  blendPosition.lerpVectors(x.p,y.p,alpha);blendRotation.slerpQuaternions(x.q,y.q,alpha);blendScale.lerpVectors(x.s,y.s,alpha);
  meshes[i].matrix.compose(blendPosition,blendRotation,blendScale);meshes[i].matrixWorldNeedsUpdate=true;
 }
 table.visible=true;
}
const tmpV=new THREE.Vector3(),tmpQ=new THREE.Quaternion();
const wristCamera=new THREE.PerspectiveCamera(73.739795,4/3,.008,3);
const wristRenderer=new THREE.WebGLRenderer({canvas:$('wrist-canvas'),antialias:true});
wristRenderer.setSize(320,240,false);wristRenderer.setPixelRatio(1);wristRenderer.setClearColor(0x101923);
let wristFrames=0,wristRateStart=performance.now(),wristFPS=0;
function receiveWristPose(pose){
 if(!pose)return;
 const position=new THREE.Vector3().fromArray(pose.position),target=new THREE.Vector3().fromArray(pose.target);
 wristCamera.fov=THREE.MathUtils.radToDeg(2*Math.atan(pose.resolution[1]/(2*pose.K[1][1])));
 wristCamera.aspect=pose.resolution[0]/pose.resolution[1];wristCamera.updateProjectionMatrix();
 const camera=new THREE.PerspectiveCamera();camera.position.copy(position);camera.up.fromArray(pose.up);camera.lookAt(target);
 if(snapshots.length)snapshots[snapshots.length-1].wrist={position,quaternion:camera.quaternion.clone()};
}
function drawWristPreview(now){
 if(!state?.wrist_camera||document.hidden||$('wrist-mode').value!=='local'||!snapshots[0]?.wrist)return;
 if(now-lastWristRender<1000/20)return;lastWristRender=now;
 const a=snapshots[0],b=snapshots[1]||a;if(!b.wrist)return;
 const alpha=b.time>a.time?THREE.MathUtils.clamp((now-interpolationDelay-a.time)/(b.time-a.time),0,1):1;
 wristCamera.position.lerpVectors(a.wrist.position,b.wrist.position,alpha);wristCamera.position.y+=table.position.y;
 wristCamera.quaternion.slerpQuaternions(a.wrist.quaternion,b.wrist.quaternion,alpha);
 wristRenderer.render(scene,wristCamera);wristFrames++;
 if(now-wristRateStart>=500){wristFPS=wristFrames*1000/(now-wristRateStart);wristFrames=0;wristRateStart=now;$('wrist-rate').textContent=wristFPS.toFixed(0)+' fps'}
 window.workshopWristPreviewStats={mode:'browser_3D',fps:wristFPS};
}
function send(op,position,rotation){if(observerMode)return;if(socket?.readyState!==WebSocket.OPEN)return;const command={seq:++seq,op};if(position)command.position=position;if(rotation)command.rotation=rotation;socket.send(JSON.stringify(command))}
function hand(p,q){q=q||new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),desktopYaw).toArray();send('hand',p,q)}
function grab(){if(!state)return;pointer.position.fromArray(state.brick);hand(pointer.position.toArray());send('grab');desktopHolding=true}
function drop(){send('release');desktopHolding=false}
$('start').onclick=()=>{if(!connected||!state)return;if(state.mode==='paused_robot')send('resume');else if(state.assembly_live){send('start')}else if(state.tabletop){drop();send('start')}else{if(state.mode==='paused'||state.mode==='human')send('reset');send('start')}};$('pause').onclick=()=>send('pause');$('reset').onclick=()=>{desktopHolding=false;send('reset')};$('grab').onclick=grab;$('drop').onclick=drop;$('lift').onclick=()=>pointer.position.y+=.06;
$('rotate').onclick=()=>desktopYaw+=Math.PI/2;
document.addEventListener('keydown',e=>{if(e.repeat)return;keyboard.add(e.code);if(e.code==='Space'){$('start').click();e.preventDefault()}if(e.code==='KeyR')$('reset').click();if(e.code==='KeyG')desktopHolding?drop():grab()});document.addEventListener('keyup',e=>keyboard.delete(e.code));
window.addEventListener('blur',()=>{keyboard.clear();if(window.parent===window){drop();send('pause')}});
function applyState(data){state=data;window.workshopState=state;receiveTransforms(state.matrices);receiveWristPose(state.wrist_camera_pose);$('wrist-preview').hidden=!state.wrist_camera;syncCameraPreview();if($('wrist-mode').value==='rgb')$('wrist-rate').textContent=state.camera_preview?state.camera_preview.fps.toFixed(1)+' fps':'';$('tabletop-tools').hidden=!state.tabletop;if(state.tabletop)$('hint').textContent='台面操作 \u00b7 \u666e\u901a RGB \u89c6\u89c9\u641c\u7d22 \u00b7 \u5f00\u59cb\u4e0d\u91cd\u7f6e\u79ef\u6728'; $('status').textContent=state.message;$('detail').textContent=`${state.mode} · ${state.controller} · t=${state.sim_time.toFixed(2)}s · seq ${state.seq}`;$('hud').dataset.mode=state.mode;$('start').textContent=state.mode==='paused_robot'?'\u7ee7\u7eed\u9012\u6599':(['paused','human'].includes(state.mode)?'\u91cd\u7f6e\u5e76\u5f00\u59cb':'\u673a\u5668\u4eba\u9012\u6599');if(state.tabletop)$('start').textContent=state.mode==='paused_robot'?'\u7ee7\u7eed\u4efb\u52a1':'\u5f00\u59cb\u89c6\u89c9\u641c\u7d22';$('start').disabled=state.mode==='robot';for(const id of ['randomize','place','set-goal'])$(id).disabled=state.mode==='robot';updateAssemblyUI();setBanner(state.message);if(observerMode){for(const id of ['restart','start','pause','reset','grab','lift','rotate','drop','vr','randomize','place','set-goal'])$(id).disabled=true;$('detail').textContent='\u53ea\u8bfb\u89c2\u5bdf \u00b7 '+$('detail').textContent}}
function restrictControls(){if(!connected||observerMode){for(const id of ['restart','start','pause','reset','grab','lift','rotate','drop','vr','randomize','place','set-goal'])$(id).disabled=true;}}
async function pollObserver(){
 if(observerMode||!connected){try{
  const response=await fetch('/health',{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);
  const health=await response.json();if(health.state?.matrices?.length&&health.state.seq!==state?.seq)applyState(health.state);
  if(!connected||observerMode){restrictControls();$('error').textContent=observerMode?'只读观察模式':
   (health.controller_connected?'场景已加载；另一页面正在控制。关闭其他控制标签页后，本页会自动接入。':'场景已加载；正在重新连接控制通道…');}
 }catch(error){$('error').textContent='物理后端暂时无法访问，正在重连：'+String(error);restrictControls();}}
 setTimeout(pollObserver,observerMode?100:300);
}
function connect(){if(observerMode)return;socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);socket.onopen=()=>{connected=true;$('error').textContent='';};socket.onmessage=e=>applyState(JSON.parse(e.data));socket.onclose=()=>{connected=false;restartPending=null;restrictControls();setTimeout(connect,1500)};socket.onerror=()=>{}}
pollObserver();
async function init(){const response=await fetch('/model');if(!response.ok)throw new Error('Model download failed');const model=await response.json();for(const item of model.objects){const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(item.vertices,3));geometry.setIndex(item.triangles);geometry.computeVertexNormals();const material=new THREE.MeshStandardMaterial({color:new THREE.Color(...item.color),roughness:.6});const mesh=new THREE.Mesh(geometry,material);mesh.name=item.name;mesh.matrixAutoUpdate=false;table.add(mesh);meshes.push(mesh)}if(model.assembly_targets){for(const goal of model.assembly_targets){const ghost=new THREE.Mesh(new THREE.BoxGeometry(.0158,.0096,.0318),new THREE.MeshBasicMaterial({color:0x65c8ff,wireframe:true,transparent:true,opacity:.35}));ghost.position.fromArray(goal.position);table.add(ghost)}}window.workshopModelCount=meshes.length;window.workshopRobotVisualCount=meshes.filter(m=>m.name.includes('/visuals/')).length;connect();const supported=!!navigator.xr&&await navigator.xr.isSessionSupported('immersive-vr');$('vr').textContent=supported?'进入 VR':'当前浏览器未连接 VR';$('vr').disabled=!supported;$('vr').onclick=async()=>{try{rig.position.set(0,0,.95);rig.rotation.set(0,Math.PI,0);camera.position.set(0,0,0);camera.rotation.set(0,0,0);const session=await navigator.xr.requestSession('immersive-vr',{optionalFeatures:['local-floor','bounded-floor']});renderer.xr.setReferenceSpaceType('local-floor');await renderer.xr.setSession(session);session.addEventListener('end',()=>{send('release');send('pause');desktopCamera()})}catch(error){$('error').textContent=String(error);desktopCamera()}}}
function edge(source,key,value,callback){const id=source.handedness+key;const old=previousButtons.get(id)||false;if(value&&!old)callback();previousButtons.set(id,value)}
const renderMeter={start:performance.now(),frames:0};
renderer.setAnimationLoop(now=>{
 if(!renderer.xr.isPresenting){if(now-lastSceneRender<1000/60)return;lastSceneRender=now-(now-lastSceneRender)%(1000/60);}
 const dt=Math.min((now-lastTime)/1000,.05);lastTime=now;
 if(renderer.xr.isPresenting){rig.updateMatrixWorld(true);for(const controller of controllers){const source=controller.userData.source;if(!source?.gamepad)continue;controller.updateMatrixWorld(true);const buttons=source.gamepad.buttons;const grip=!!buttons[1]?.pressed;if(source.handedness==='right'){controller.getWorldPosition(tmpV);table.worldToLocal(tmpV);controller.getWorldQuaternion(tmpQ);if(now-lastHand>25){hand(tmpV.toArray(),tmpQ.toArray());lastHand=now}edge(source,'grip',grip,()=>{hand(tmpV.toArray(),tmpQ.toArray());send('grab')});if(!grip&&previousButtons.get('right_release'))send('release');previousButtons.set('right_release',grip);edge(source,'A',!!buttons[4]?.pressed,()=>$('start').click());edge(source,'B',!!buttons[5]?.pressed,()=>$('pause').click())}else edge(source,'X',!!buttons[4]?.pressed,()=>$('reset').click())}}
 else{const speed=.15*dt;pointer.position.x+=((keyboard.has('KeyL')?1:0)-(keyboard.has('KeyJ')?1:0))*speed;pointer.position.z+=((keyboard.has('KeyI')?1:0)-(keyboard.has('KeyK')?1:0))*speed;pointer.position.y+=((keyboard.has('KeyU')?1:0)-(keyboard.has('KeyO')?1:0))*speed;pointer.position.y=Math.max(.007,Math.min(.5,pointer.position.y));if(connected&&!state?.assembly_live&&now-lastHand>30){hand(pointer.position.toArray());lastHand=now}}
 animateTransforms(now);renderer.render(scene,camera);drawWristPreview(now);
 renderMeter.frames++;if(now-renderMeter.start>=1000){window.workshopPerformance={render_fps:renderMeter.frames*1000/(now-renderMeter.start),source_fps:1000/sourcePeriod,interpolation_ms:interpolationDelay,wrist_fps:wristFPS,draw_calls:renderer.info.render.calls};renderMeter.frames=0;renderMeter.start=now;}
});
window.addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight)});
init().catch(error=>{$('error').textContent=String(error);console.error(error)});

function syncCameraPreview(){
 const img=$('wrist-image');const raw=$('wrist-mode').value==='rgb';const active=!!state?.wrist_camera&&!document.hidden&&raw;
 img.hidden=!raw;$('wrist-canvas').hidden=raw;$('wrist-note').textContent=raw?'Isaac \u4f20\u611f\u5668\u5b9e\u9645\u56fe\u50cf\uff0c\u4f9b\u5b9a\u4f4d\u4e0e\u8bad\u7ec3\u4f7f\u7528\u3002':'\u6d4f\u89c8\u5668\u6e32\u67d3\u9884\u89c8\uff1b\u5b9a\u4f4d\u4f7f\u7528 Isaac \u539f\u59cb RGB\u3002';
 if(active&&!img.hasAttribute('src'))img.src='/wrist.mjpeg';
 else if(!active&&img.hasAttribute('src'))img.removeAttribute('src');
}
document.addEventListener('visibilitychange',syncCameraPreview);$('wrist-mode').onchange=()=>{wristFrames=0;wristRateStart=performance.now();$('wrist-rate').textContent='';syncCameraPreview()};
$('wrist-image').onerror=()=>{ $('wrist-image').removeAttribute('src');setTimeout(syncCameraPreview,1500) };


let placementMode=null;
$('randomize').onclick=()=>send('randomize');
$('place').onclick=()=>{placementMode='place';$('placement-hint').textContent='请点击机械臂可达的台面位置摆放积木。'};
$('set-goal').onclick=()=>{placementMode='goal';$('placement-hint').textContent='请点击机械臂可达的台面位置设置放置目标。'};
renderer.domElement.addEventListener('pointerdown',event=>{
 if(!placementMode||!state?.tabletop||state.mode==='robot'||renderer.xr.isPresenting)return;
 const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2(event.clientX/innerWidth*2-1,1-event.clientY/innerHeight*2),camera);
 const hit=new THREE.Vector3();if(ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0,1,0),-.7548),hit)){
  table.worldToLocal(hit);send(placementMode,hit.toArray());placementMode=null;$('placement-hint').textContent='\u4f4d\u7f6e\u5df2\u63d0\u4ea4\uff0c\u70b9\u51fb\u5f00\u59cb\u89c6\u89c9\u641c\u7d22\u3002';
 }
});

function updateAssemblyUI(){
 $('restart').hidden=!state?.assembly_live;
 if(restartPending&&state.assembly?.seed!==restartPending.seed)restartPending=null;
 $('restart').textContent=restartPending?'正在重新开始…':'重新开始';
 $('restart').disabled=observerMode||!connected||!!restartPending;
 document.body.classList.toggle('assembly-scene',!!state?.assembly_live);
 agentBoard.update(state,connected&&!observerMode);
 const active=!!state?.assembly_live;$('assembly-progress').hidden=!active;$('assembly-view-tools').hidden=!active;pointer.visible=!active;
 if(!active)return;
 const a=state.assembly;
 $('view-heap').hidden=a.scene_mode!=='physical_heap';$('view-fixture').hidden=a.scene_mode!=='physical_heap'||a.collaboration_mode==='human_assisted_no_turning_fixture';
 humanTarget.visible=!!a.human_request;humanSource.visible=false;
 if(a.human_request){const p=a.human_request.target_m;humanTarget.position.set(-p[1],.0015,p[0]);
  const source=a.heap_observation?.pieces?.find(p=>p.color===a.human_request.color);
  if(source){const p=source.position_m;humanSource.position.set(-p[1],p[2]+.008,p[0]);humanSource.visible=true;}}
 $('start').textContent=state.mode==='paused_robot'?'\u7ee7\u7eed\u6982\u5ff5\u642d\u5efa':'\u5f00\u59cb\u6309\u8bf4\u660e\u4e66\u642d\u5efa';
 $('start').disabled=state.mode==='robot'||['failed','complete'].includes(a.status);
 $('reset').textContent='重置布局';
 for(const id of ['grab','lift','rotate','drop'])$(id).hidden=true;
 $('assembly-progress').textContent='\u6982\u5ff5\u642d\u5efa '+a.completed_steps.length+'/'+a.total_steps+' \u00b7 '+(a.current_step||a.status)+' \u00b7 '+a.phase+'\n\u8fde\u63a5\u91c7\u7528\u63a5\u89e6\u89e6\u53d1\u7684\u7ea6\u675f\u8fd1\u4f3c\uff0c\u771f\u5b9e LEGO \u5361\u63a5\u672a\u9a8c\u6536\u3002';
 $('hint').textContent='\u5b9e\u65f6 Isaac Sim \u00b7 \u8bf4\u660e\u4e66\u9a71\u52a8 \u00b7 RGB \u9009\u6599 \u00b7 \u8fde\u63a5\u7ea6\u675f\u6982\u5ff5\u6a21\u578b';
 if(a.random_yaw)$('hint').textContent='随机位置＋随机角度 · 腕部 RGB 选料 · 概念连接';
 if(a.scene_mode==='physical_heap'){
  $('start').textContent=['paused_robot','paused_human'].includes(state.mode)?'继续任务':'开始观察与整理';
  $('start').disabled=!(a.status==='ready'||['paused_robot','paused_human'].includes(state.mode));
  $('pause').disabled=!['robot','waiting_human'].includes(state.mode);
  $('assembly-progress').textContent='已整理 '+a.normalized_colors.length+'/6 · 说明书 '+a.completed_steps.length+'/6 · '+a.phase+'\n'+a.message;
  $('hint').textContent='真实零件堆 · RGB 多视角观察 · 机器人取件与人工协助 · 装配仍为概念连接';
 }
}
window.addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==window.parent)return;
 if(event.data?.type==='assembly-command'){
  if(['start','pause','resume','reset'].includes(event.data.op))send(event.data.op);
  else if(['human_done','simulate_human','human_auto_on','human_auto_off'].includes(event.data.op)&&!observerMode&&socket?.readyState===WebSocket.OPEN)
   socket.send(JSON.stringify({seq:++seq,op:event.data.op,request_id:event.data.request_id}));
 }
});
