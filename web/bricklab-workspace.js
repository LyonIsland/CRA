import * as THREE from 'three';
import {OrbitControls} from '/workspace-assets/OrbitControls.js';
const $=id=>document.getElementById(id),id=document.body.dataset.job,base='/workspace/'+id;
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x152334);
$('viewer').prepend(renderer.domElement);
const scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xffffff,0x4b586a,2));const light=new THREE.DirectionalLight(0xffffff,2);light.position.set(-1,3,2);scene.add(light);
const camera=new THREE.PerspectiveCamera(50,1,.01,10);camera.position.set(.65,.65,1);const orbit=new OrbitControls(camera,renderer.domElement);orbit.target.set(0,.12,.25);orbit.update();
let meshes=[],loaded=false,busy=false,state=null,failedPolls=0;
function resize(){const box=$('viewer');if(box.clientWidth&&box.clientHeight){renderer.setSize(box.clientWidth,box.clientHeight,false);camera.aspect=box.clientWidth/box.clientHeight;camera.updateProjectionMatrix();}}
new ResizeObserver(resize).observe($('viewer'));resize();
function animate(){requestAnimationFrame(animate);if(!document.hidden&&$('viewer').offsetHeight){orbit.update();renderer.render(scene,camera);}}animate();
async function request(route,body){const r=await fetch(base+route,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await r.json();if(!r.ok)throw Error(result.error||'操作未完成');return result;}
async function command(op,extra={}){try{await request('/command',{op,...extra});}catch(error){$('status').textContent=error.message;}}
async function loadModel(){const r=await fetch(base+'/model');if(!r.ok)return;const model=await r.json();for(const object of model.objects){const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(object.vertices,3));geometry.setIndex(object.triangles);geometry.computeVertexNormals();const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:new THREE.Color(...object.color),roughness:.7}));mesh.matrixAutoUpdate=false;scene.add(mesh);meshes.push(mesh);}loaded=true;}
async function poll(){if(busy)return;busy=true;try{state=await request('/status');failedPolls=0;$('status').textContent=state.message;const active=!['starting','not_started','failed','closed'].includes(state.mode);if(active&&!loaded)await loadModel();if(loaded&&state.matrices)state.matrices.forEach((matrix,i)=>{if(meshes[i])meshes[i].matrix.fromArray(matrix);});
 if(state.sequence){const url=base+'/wrist.jpg?v='+state.sequence;$('wrist-mini').src=url;$('wrist').src=url;}
 $('start-policy').disabled=!active||!state.policy_available||state.recording;$('pause').disabled=!active;$('record').disabled=!active||state.mode==='policy'||state.recording;$('save').disabled=!active||!state.recorded_steps;
 for(const button of document.querySelectorAll('.joint button'))button.disabled=!active||state.mode==='policy';
 $('robot-panel').classList.toggle('recording',!!state.recording);$('view-scene').disabled=!!state.recording;
 $('capability').textContent=state.policy_available?'可启动说明书条件策略。搭建结果仍需独立验收。':'尚未训练好说明书自动搭建策略。当前可直接进入对应场景、手动操作并记录训练示范。';
 $('record-status').textContent=(state.recording?'正在记录 · ':'')+(state.recorded_steps||0)+' 个动作；已保存 '+(state.saved_demonstrations?.length||0)+' 条示范。';
 }catch(error){if(++failedPolls>3)$('status').textContent='场景连接暂时中断：'+error.message;}finally{busy=false;}}
async function start(){try{$('status').textContent='正在打开本作品的机械臂场景…';await request('/start',{});await poll();}catch(error){$('status').textContent=error.message;}}
$('reconnect').onclick=start;$('stop').onclick=async()=>{try{await request('/stop',{});await poll();}catch(error){$('status').textContent=error.message;}};
$('pause').onclick=()=>command('pause');$('start-policy').onclick=()=>command('start_policy');$('record').onclick=()=>command('record');$('save').onclick=()=>command('save');
$('view-scene').onclick=()=>{if(!state?.recording){$('viewer').style.display='block';$('wrist').style.display='none';resize();}};
$('view-wrist').onclick=()=>{$('viewer').style.display='none';$('wrist').style.display='block';};
['关节 1','关节 2','关节 3','关节 4','关节 5','关节 6','夹爪'].forEach((name,index)=>{const row=document.createElement('div');row.className='joint';const label=document.createElement('span');label.textContent=name;row.append(label);for(const [text,sign] of [['−',-1],['+',1]]){const button=document.createElement('button');button.textContent=text;button.disabled=true;button.dataset.axis=index;button.dataset.sign=sign;button.onclick=()=>{const action=Array(7).fill(0);action[index]=sign;command('step',{action});};row.append(button);}$('joints').append(row);});
setInterval(poll,500);start();
