// Open the matching live workspace only for a new, explicit model submission.
(()=>{
 const submit=document.getElementById('workflow-submit'),job=document.getElementById('workflow-job');
 if(!submit||!job)return;
 let pending=null;
 submit.addEventListener('click',()=>{
  if(submit.disabled)return;
  const previous=document.getElementById('workflow-environment').getAttribute('href');
  const popup=window.open('about:blank','_blank');
  if(popup){popup.document.title='正在准备机械臂搭建';popup.document.body.textContent='正在生成本作品的说明书和机械臂场景，请稍候…';}
  pending={previous,popup};
 },true);
 new MutationObserver(()=>{
  if(!pending)return;
  if(job.dataset.status==='failed'){
   if(pending.popup&&!pending.popup.closed)pending.popup.document.body.textContent='任务尚未生成，请返回编辑器查看原因并修改模型。';
   pending=null;return;
  }
  const link=document.getElementById('workflow-environment').getAttribute('href');
  if(job.dataset.status==='prepared'&&link&&link!==pending.previous){
   const url=new URL(link,location.href);
   if(url.origin===location.origin&&url.pathname.startsWith('/workspace/')){
    if(pending.popup&&!pending.popup.closed)pending.popup.location.replace(url.href);
    pending=null;
   }
  }
 }).observe(job,{attributes:true,childList:true,subtree:true});
})();
