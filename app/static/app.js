const modal=document.getElementById('modal');
const toast=document.getElementById('toast');
const form=document.getElementById('assessmentForm');
const errorBox=document.getElementById('formError');
function notify(message){toast.textContent=message;toast.classList.add('show');setTimeout(()=>toast.classList.remove('show'),3600)}
document.getElementById('newAssessment').addEventListener('click',()=>modal.classList.add('open'));
document.getElementById('closeModal').addEventListener('click',()=>modal.classList.remove('open'));
modal.addEventListener('click',e=>{if(e.target===modal)modal.classList.remove('open')});
form.addEventListener('submit',async e=>{
 e.preventDefault();errorBox.textContent='';const data=Object.fromEntries(new FormData(form).entries());
 try{const r=await fetch('/api/assessments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Could not create assessment.');
 modal.classList.remove('open');notify('Assessment created. Preparing the execution console…');
 if(data.mode==='demo'){const run=await fetch(`/api/assessments/${j.id}/run`,{method:'POST'});if(!run.ok){const x=await run.json();throw new Error(x.detail||'Demo run failed.')}}
 else {const run=await fetch(`/api/assessments/${j.id}/run`,{method:'POST'});if(!run.ok){const x=await run.json();throw new Error(x.detail||'Live run halted.')}}
 location.href='/?assessment='+j.id;
 }catch(err){errorBox.textContent=err.message}
});
document.getElementById('exportReport').addEventListener('click',()=>{if(!window.AETHRON_ACTIVE)return;window.open(`/api/assessments/${window.AETHRON_ACTIVE}/report`,'_blank')});
const params=new URLSearchParams(location.search);if(params.has('new'))modal.classList.add('open');
