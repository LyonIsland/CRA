// Display published controller evidence and plans, never invented model thoughts.
import {explainBehavior} from './behavior-explanation.js?v=survey-2';
const names={red:'红色',blue:'蓝色',green:'绿色',yellow:'黄色',orange:'橙色',purple:'紫色',cyan_distractor:'青色干扰件',black_distractor:'黑色干扰件'};
const phases={ready:'等待开始',heap_fit:'计算零件姿态',heap_survey:'多视角观察',heap_inspection:'分析观察结果',human_retreat:'撤离协作区',approach:'接近目标',orient_pick:'调整抓取方向',descend:'低速下降',close:'闭合夹爪',lift:'抬起零件',align_transport:'调整搬运方向',transfer:'搬运零件',lower:'接触放置',release:'松开夹爪',retreat:'撤离零件',recover_raise:'受阻后抬高',recover_open:'松爪并重新观察',complete:'任务完成',search:'搜索零件',verify_carry:'检查夹持',register_carry:'视觉配准',verify_placement:'放置验收'};
const eventNames={requested:'机器人请求协助',announced:'模拟人响应',action_started:'开始处理零件',action_completed:'处理完成',withdrawn:'协作者撤手',robot_verified:'RGB 复查通过',robot_verification_failed:'RGB 复查未通过',auto_mode_changed:'协作模式变更',auto_limit_reached:'自动处理次数已达上限'};
const faceNames={up:'凸点朝上假设',down:'倒扣假设',side_left:'侧躺假设',side_right:'侧躺假设',end_front:'端面着地假设',end_back:'端面着地假设'};
const color=c=>names[c]||c||'未发布';
const actionNames={reobserve_selected_piece:'重新观察目标',grasp:'夹取',verify_grasp:'检查夹持',orient:'调整方向',move_above_target:'移动到目标上方',seat_on_support:'接触放置',engage_simulated_connector:'建立概念连接',release:'松爪',verify_concept_placement:'验收概念搭建',align_studs:'对准凸点',press_with_force_limit:'限力压入',verify_pose_and_connections:'验收位置与连接'};
function text(tag,value,cls){const e=document.createElement(tag);e.textContent=value;if(cls)e.className=cls;return e}
function card(parent,title,value,note){const e=document.createElement('section');e.className='agent-card';e.append(text('h3',title),text('p',value));if(note)e.append(text('small',note));parent.append(e);return e}
export function createAgentBoard(command){
 const board=document.createElement('aside');board.id='agent-board';board.hidden=true;board.setAttribute('aria-label','Agent 场景看板');
 board.innerHTML='<header><div><small>LIVE · AGENT</small><h2>任务看板</h2></div><button id="board-collapse" aria-label="收起任务看板" aria-expanded="true">收起</button></header><div id="board-body"><div id="agent-summary"></div><nav aria-label="看板内容"></nav><div id="agent-pane"></div><footer>实时控制器记录 · 规则与几何基线<br>装配连接为概念近似</footer></div>';
 document.body.append(board);const nav=board.querySelector('nav'),pane=board.querySelector('#agent-pane');
 const explanation=document.createElement('section');explanation.id='agent-explanation';explanation.setAttribute('aria-label','机械臂行为解释');
 explanation.innerHTML='<div id="behavior-target"></div><div><small>当前状态</small><p id="behavior-now"></p></div><div><small>接下来做什么</small><p id="behavior-next"></p></div><div><small>为什么这样做</small><p id="behavior-why"></p></div><details><summary>查看依据</summary><p id="behavior-evidence"></p></details>';
 nav.before(explanation);let explanationKey='';
 let selected='execution',latest=null,owns=false,key='',last=0,episode=null,trace=[];
 const tabs=[['execution','执行'],['decision','决策'],['checks','检查'],['human','协作'],['manual','说明书']];
 for(const [id,label] of tabs){const b=text('button',label);b.dataset.tab=id;b.setAttribute('aria-selected',String(id===selected));b.onclick=()=>{selected=id;key='';render()};nav.append(b)}
 board.querySelector('#board-collapse').onclick=e=>{const collapsed=board.classList.toggle('collapsed');e.currentTarget.textContent=collapsed?'展开':'收起';e.currentTarget.setAttribute('aria-expanded',String(!collapsed))};
 function action(parent,label,op,disabled){const b=text('button',label);b.dataset.op=op;b.disabled=disabled;b.onclick=()=>command(op);parent.append(b)}
 function render(){
  if(!latest)return;const s=latest,a=s.assembly,agent=s.assembly_agent||{},plan=agent.last_plan,req=a.human_request;
  for(const b of nav.children)b.setAttribute('aria-selected',String(b.dataset.tab===selected));
  board.querySelector('#agent-summary').textContent=`整理 ${a.normalized_colors?.length||0}/6 · 搭建 ${a.completed_steps.length}/${a.total_steps}`;
  if(board.classList.contains('collapsed'))return;
  const behavior=explainBehavior(s),behaviorKey=JSON.stringify(behavior);
  if(behaviorKey!==explanationKey){explanationKey=behaviorKey;
   for(const field of ['now','next','why','evidence'])board.querySelector('#behavior-'+field).textContent=behavior[field];
   board.querySelector('#behavior-target').textContent='当前目标 · '+behavior.target;
  }
  const content=selected==='execution'?[a.phase,a.message,a.active_skill,a.normalized_colors,s.mode,trace]:
   selected==='decision'?[req,plan,agent.reason,a.active_skill,a.message,behaviorKey]:
   selected==='checks'?[a.heap_observation,a.joint_count,a.broken_connections]:
   selected==='human'?[a.simulated_human?.enabled,a.simulated_human?.phase,req,s.mode,a.human_activity]:
   [a.completed_steps,a.current_step,s.assembly_overview];
  const signature=JSON.stringify([selected,owns,content]);if(signature===key)return;key=signature;
  pane.replaceChildren();
  if(selected==='execution'){
   card(pane,'正在执行',phases[a.phase]||a.phase,a.message);
   card(pane,'任务阶段',a.active_skill==='assembly'?'按说明书搭建':a.active_skill==='human_retreat'?'人机协作交接':'观察与整理',`模式：${s.mode} · 布局 ${a.seed}`);
   card(pane,'已整理的零件',(a.normalized_colors||[]).map(color).join('、')||'暂无');
   const timeline=card(pane,'执行轨迹','本次页面连接后记录');
   const list=document.createElement('ol');for(const item of trace.slice(-8))list.append(text('li',item));timeline.append(list);
  }else if(selected==='decision'){
   card(pane,'决策记录来源','控制器状态、视觉观察和结构化计划','展示已发布的决策依据；未发布的信息会标为待观察。');
   if(req){card(pane,'为什么请求协作',req.reason);card(pane,'请求的操作',req.instruction)}
   else if(plan){card(pane,'当前计划',`${plan.step_id||''} · ${color(plan.selected_part?.color)}`,plan.reason||`从当前观察选择 ${plan.selected_track_id||'待选目标'}`);
    card(pane,'动作计划',(plan.actions||[]).map(a=>actionNames[a]||a).join(' → ')||'尚未生成');
    if(plan.missing_capabilities?.length)card(pane,'执行阻塞',plan.missing_capabilities.join('、'));
   }else {card(pane,'当前动作逻辑',behavior.why,behavior.evidence);card(pane,'下一步',behavior.next);}
   if(a.scene_mode==='physical_heap'){
    const rules=document.createElement('details');rules.append(text('summary','查看零件选择规则'),text('p','优先取走人工交接区中已确认的零件；否则比较可见候选的高度、可见程度和拟合误差。朝向不可靠或重复失败时请求协作。'));pane.append(rules);
   }
  }else if(selected==='checks'){
   const obs=a.heap_observation,pieces=obs?.pieces||[];
   card(pane,'视觉观察',obs?.view_count?`${obs.view_count} 个腕部 RGB 视角`:'尚未完成观察','几何拟合结果有歧义，不等同于真实朝向。');
   for(const p of pieces)card(pane,color(p.color),`${faceNames[p.face_hypothesis]||p.face_hypothesis} · ${p.safe_candidate?'可取件候选':'暂不满足取件条件'}`,`重投影误差 ${Number(p.score_px).toFixed(2)} px · 观察位置 ${p.position_m.map(v=>v.toFixed(3)).join(', ')} m`);
   if(!pieces.length)card(pane,'零件检查','待观察','没有视觉证据时，不显示为已通过。');
   card(pane,'结构连接',`${a.joint_count||0} 条概念连接`,a.broken_connections?.length?'检测到断裂：'+a.broken_connections.join('、'):'当前未报告连接断裂；不代表真实塑料卡接验收。');
  }else if(selected==='human'){
   const h=a.simulated_human;
   card(pane,'协作状态',h?.enabled?'自动模拟人已开启':'手动协作',h?`模拟人阶段：${({idle:'待命',responding:'响应',acting:'处理',withdrawn:'已撤手'})[h.phase]||h.phase}`:'当前场景未接入模拟人');
   if(h)action(pane,h.enabled?'关闭自动模拟人':'启用自动模拟人',h.enabled?'human_auto_off':'human_auto_on',!owns);
   if(req){card(pane,'当前求助',req.reason,req.instruction);
    action(pane,'我已完成并撤手','human_done',!owns||s.mode!=='waiting_human');
    action(pane,'模拟人完成一次','simulate_human',!owns||s.mode!=='waiting_human');}
   for(const event of [...(a.human_activity||[])].reverse())card(pane,eventNames[event.event]||event.event,color(event.color),event.interpretation||event.reason||'');
   if(!a.human_activity?.length)card(pane,'协作记录','尚未发生协作事件');
   card(pane,'模拟方式','任务级零件姿态代操作','未模拟手指接触；机器人通过新 RGB 观察确认处理结果。');
  }else{
   card(pane,'搭建目标','六块 2×4 积木 · 三层交错小墙');
   const steps=s.assembly_overview?.steps||[];
   for(const step of steps)card(pane,`${step.step_id} · ${color(step.part?.color)}`,a.completed_steps.includes(step.step_id)?'已验收':step.step_id===a.current_step?'执行中':'待执行',step.requires_verified_supports?.length?'依赖：'+step.requires_verified_supports.join('、'):'');
   const details=document.createElement('details');details.append(text('summary','展开图解说明书'));
   details.addEventListener('toggle',()=>{if(details.open&&!details.querySelector('iframe')){const f=document.createElement('iframe');f.src='/manual';f.title='乐高图解说明书';details.append(f)}},{once:true});pane.append(details);
   const link=text('a','下载说明书 PDF');link.href='/manual.pdf';link.target='_blank';link.rel='noopener';pane.append(link);
  }
 }
 return {update(s,owner){board.hidden=!s.assembly_live;if(!s.assembly_live)return;latest=s;owns=owner;
   if(episode!==s.assembly.seed||s.assembly.status==='ready'&&s.assembly.phase==='ready'&&trace.length){episode=s.assembly.seed;trace=[];}
   const label=phases[s.assembly.phase]||s.assembly.phase;
   if(trace.at(-1)!==label)trace.push(label);if(trace.length>40)trace.shift();
   if(performance.now()-last>500){last=performance.now();render();}
  }};
}
