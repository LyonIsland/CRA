// Public action explanations derived from controller phases and published evidence.
const colors={red:'红色积木',blue:'蓝色积木',green:'绿色积木',yellow:'黄色积木',orange:'橙色积木',purple:'紫色积木',cyan_distractor:'青色干扰件',black_distractor:'黑色干扰件'};
export function explainBehavior(s){
 const a=s.assembly||{},req=a.human_request,agent=s.assembly_agent||{};
 const plan=agent.last_plan?.step_id===a.current_step?agent.last_plan:null;
 const extracted=a.current_step?.startsWith('extract_')?a.current_step.slice(8):null;
 const step=s.assembly_overview?.steps?.find(step=>step.step_id===a.current_step);
 const targetColor=(a.active_skill==='human_retreat'||req?.state==='verifying')?req?.color:extracted||plan?.selected_part?.color||step?.part?.color;
 const target=colors[targetColor]||'尚未选定零件';
 const item=targetColor?target:'目标零件';
 const placement=a.active_skill==='assembly'?'说明书指定的位置':targetColor?.endsWith('_distractor')?'干扰件移除区':'整理区';
 const output=(now,next,why,evidence='依据当前控制阶段的执行条件')=>({now,next,why,target,evidence});
 if(a.status==='complete')return output('本轮搭建已完成','点击“重新开始”，生成新布局并开始下一轮',`控制器已报告完成 ${a.completed_steps?.length||0}/${a.total_steps||6} 步概念搭建。`,'依据本轮完成状态');
 if(a.status==='failed')return output('执行异常，机械臂已停止','检查异常原因，或重新开始',a.message||'当前执行条件未通过。','依据控制器异常报告');
 if(a.status==='ready')return output('等待开始','点击“开始观察与整理”，先扫描桌面','还没有启动本轮任务，需要先观察零件的位置和朝向。','依据任务就绪状态');
 if(['paused_robot','paused_human','paused'].includes(s.mode))return output('任务已暂停','点击“继续任务”，恢复当前阶段',`控制器处于暂停模式，当前不继续执行动作。暂停时的阶段：${a.phase||'未发布'}。`,'依据控制器暂停状态');
 if(s.mode==='waiting_human')return output(a.simulated_human?.phase==='acting'?'机械臂保持撤离，等待协作者处理零件':'机械臂等待协作者响应',`等待${targetColor?item:'指定零件'}被翻正、分开并撤手，然后重新拍照检查`,req?.reason||'当前条件不满足自主取件，需要协作者帮助。','依据当前求助原因');
 if(a.phase==='human_retreat')return output('机械臂正在撤离协作区域',`留出操作空间，请协作者处理${item}`,req?.reason||'先完成撤离，再进入人工协作阶段。','依据当前求助和撤离阶段');
 if(a.phase==='heap_fit'){
  const p=a.survey_progress;
  return output(`拍照已完成，正在计算零件姿态${p?`（${p.pieces_completed}/${p.pieces_total}）`:''}`,
   '完成剩余候选的图像分析，再决定抓取或请求协作',
   '需要比较各朝向与多视角图像的匹配程度；计算期间机械臂保持当前观察位置。',
   p?`本轮扫描与分析已用 ${p.elapsed_seconds} 秒；已整理零件不再重复拟合。`:'依据图像拟合阶段');
 }
 if(a.phase==='heap_survey'||a.phase==='heap_inspection'){
  if(req?.state==='verifying')return output(`重新拍照检查${item}`,`确认${item}朝上、位于协作区且与邻件分开，再尝试抓取`,'协作者报告完成后，仍须用新的视觉观察验证结果，不能直接假定处理成功。','依据协作后的视觉复查状态');
  const p=a.survey_progress;
  return output(p?`前往观察点 ${Math.min(p.views_completed+1,p.views_total)}/${p.views_total}，扫描剩余零件`:'移动腕部相机，扫描桌面上的零件',
   '拍完全部视角后，分析剩余零件并选取下一块',
   '换视角是为了定位零件、分辨朝向和遮挡；需要不同方向的观察才能确定抓取目标。',
   p?`已拍 ${p.views_completed}/${p.views_total} 个视角；本轮已用 ${p.elapsed_seconds} 秒。`:'依据多视角观察阶段');
 }
 const steps={
  search:['搜索说明书需要的零件','找到可靠目标后移动到其上方','必须先获得所需颜色和规格的视觉定位，才能开始抓取。'],
  approach:[`移动到${item}上方`,'近距离复查位置，再调整夹爪方向','先在零件上方对准，为后续低速下降留出空间。'],
  align:[`近距离复查${item}的位置`,'计算可达且尽量避开邻件的夹持方向','初次观察不足以直接下降，需要复查图像并计算夹持姿态。'],
  orient_pick:[`调整夹爪，准备夹取${item}`,'沿选定方向低速下降','夹爪需要先对准零件方向和抓取位置，才能下降闭合。'],
  descend:[`向${item}低速下降`,'到达抓取高度后闭合夹爪','缓慢接近可检测受阻情况；受阻时退出并重新观察。'],
  close:[`闭合夹爪，尝试夹住${item}`,'双侧接触稳定后抬起零件','必须建立稳定的双指接触，不能仅凭夹爪已闭合就开始搬运。'],
  lift:[`抬起${item}`,`保持夹持，调整搬运方向后移往${placement}`,'需要先把零件抬离桌面和邻件，搬运中继续检查夹持接触。'],
  verify_carry:[`检查是否夹稳${item}`,'检查通过后调整方向并搬运','抬起动作完成不等于夹持可靠，需要继续检查持物情况。'],
  align_transport:[`调整${item}的搬运方向`,`经过上方路径移往${placement}`,'先在抬起状态调整方向，避免带着错误朝向进入放置位置。'],
  orient:[`将${item}转到说明书要求的方向`,'在结构上方检查夹持和位置','积木需要符合当前说明书步骤的方向要求。'],
  via_source:[`携带${item}离开原抓取位置`,`经过上方路径前往${placement}`,'搬运遵循上方路径，保持零件抬起并检查接触是否丢失。'],
  via_goal:[`携带${item}移向${placement}`,'到达目标上方后准备放置','先到达目标上方，再执行下降放置。'],
  transfer:[`将${item}搬运到${placement}上方`,'保持夹持，低速下降到放置位置','需要先对准目标位置，才能下降和松爪。'],
  preseat:[`将${item}对准结构上方`,'用近距离视觉配准位置，再下降','说明书装配需要在下降前检查持物位置偏差。'],
  register_carry:[`用相机校正${item}的放置位置`,'补偿夹持偏移后继续下降','积木中心可能偏离夹爪中心，需要视觉配准补偿。'],
  lower:[`把${item}缓慢放到${placement}`,'接触放置条件满足后松开夹爪',a.active_skill==='assembly'?'需要满足支撑接触和概念连接条件，才允许松爪。':'需要检测到支撑接触并放稳后再松爪，避免在空中释放。'],
  release:[`松开夹爪，释放${item}`,'张开夹爪并撤离，随后检查放置结果','放置阶段已推进到释放步骤；松开后仍需要独立验收。'],
  retreat:[`从${item}上方撤离`,'检查零件是否放稳，再继续下一块','先让夹爪离开零件，避免影响放置结果的观察和评估。'],
  verify_placement:[`检查${item}的放置结果`,'验收通过后推进说明书下一步','必须检查位置、方向和概念连接，不能把完成搬运动作当作装配成功。'],
  extracted:[`${item}已取出`,'确认整理结果，再观察下一块零件','取出不等于完成整套搭建，仍需完成整理与说明书装配。'],
  recover_raise:['抓取遇到问题，正在抬高退出','松开夹爪，重新观察零件堆','当前抓取未满足继续执行的条件，需要先退出再尝试。'],
  recover_open:['松开夹爪，准备重新观察','换视角观察并重试；多次失败时请求协作','继续沿原抓取方案执行不可靠，需要更新观察结果。']
 };
 let result=steps[a.phase];
 if(result){
  const p=a.heap_observation?.pieces?.find(p=>p.color===targetColor);
  const evidence=p?`当前目标：${target}；最近视觉拟合误差 ${Number(p.score_px).toFixed(2)} px。`:'依据已发布的控制阶段；未发布的接触结果不视为通过。';
  return output(...result,evidence);
 }
 return output(a.message||'等待控制器状态','等待控制器发布下一步动作','当前阶段尚未提供更详细的执行条件。','仅显示已发布的状态');
}
