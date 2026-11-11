const assert=require('assert/strict');
(async()=>{
 const {explainBehavior}=await import('./behavior-explanation.js');
 const sample=(phase,extra={})=>({mode:'robot',assembly:{phase,status:'running',active_skill:'extract',current_step:'extract_red',...extra}});
 const grasp=explainBehavior(sample('close'));assert.match(grasp.now,/闭合夹爪.*红色/);assert.match(grasp.next,/双侧接触稳定/);assert.match(grasp.why,/不能仅凭/);
 const paused=sample('close');paused.mode='paused_robot';assert.match(explainBehavior(paused).now,/暂停/);
 const failed=explainBehavior(sample('lower',{status:'failed',message:'接触丢失'}));assert.match(failed.now,/停止/);assert.equal(failed.why,'接触丢失');
 const waiting=sample('human_retreat',{active_skill:'human_retreat',human_request:{color:'blue',reason:'倒扣'}});waiting.mode='waiting_human';
 assert.equal(explainBehavior(waiting).why,'倒扣');assert.match(explainBehavior(waiting).target,/蓝色/);
 const verifying=explainBehavior(sample('heap_survey',{active_skill:'survey',human_request:{color:'yellow',state:'verifying'}}));assert.match(verifying.now,/重新拍照.*黄色/);assert.match(verifying.why,/不能直接假定/);
 const unknown=explainBehavior(sample('unpublished'));assert.match(unknown.next,/等待控制器/);
 const fitting=explainBehavior(sample('heap_fit',{active_skill:'survey',survey_progress:{pieces_completed:2,pieces_total:5,elapsed_seconds:9}}));
 assert.match(fitting.now,/拍照已完成.*2\/5/);assert.match(fitting.why,/保持当前观察位置/);
 const phases=['search','approach','align','orient_pick','descend','close','lift','verify_carry','align_transport','orient','via_source','via_goal','transfer','preseat','register_carry','lower','release','retreat','verify_placement','recover_raise','recover_open','extracted'];
 for(const phase of phases)assert.doesNotMatch(explainBehavior(sample(phase)).why,/尚未提供/);
 console.log(JSON.stringify({phase_explanations:phases.length,pause_and_failure_override:true,human_request_and_RGB_verification:true,unknown_state_not_invented:true}));
})().catch(e=>{console.error(e);process.exitCode=1});
