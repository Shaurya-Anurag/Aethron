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
 const run=await fetch(`/api/assessments/${j.id}/run`,{method:'POST'});
 if(!run.ok){const x=await run.json();throw new Error(x.detail||'Assessment run failed.')}
 location.href='/?assessment='+j.id;
 }catch(err){errorBox.textContent=err.message}
});
document.getElementById('exportReport').addEventListener('click',()=>{if(!window.AETHRON_ACTIVE)return;window.open(`/api/assessments/${window.AETHRON_ACTIVE}/report`,'_blank')});
const params=new URLSearchParams(location.search);if(params.has('new'))modal.classList.add('open');

// Poll persisted state while an assessment is active. Stop cleanly on terminal states;
// never reload the page on completion (that caused an infinite reload loop).
(function startAssessmentPolling() {
  const assessmentId = window.AETHRON_ACTIVE;
  if (!assessmentId) return;
  const timeline = document.querySelector(".timeline");
  let lastEventId = Number(window.AETHRON_LAST_EVENT_ID || 0);
  let stopped = false;
  let pollTimer = null;

  function stopPolling() {
    stopped = true;
    if (pollTimer !== null) window.clearInterval(pollTimer);
  }

  async function refresh() {
    if (stopped) return;
    try {
      const [detailResponse, eventsResponse] = await Promise.all([
        fetch(`/api/assessments/${assessmentId}`),
        fetch(`/api/assessments/${assessmentId}/events?after=${lastEventId}`)
      ]);
      if (!detailResponse.ok || !eventsResponse.ok) return;
      const detail = await detailResponse.json();
      const events = await eventsResponse.json();

      if (timeline && events.length) {
        const empty = timeline.querySelector(".empty-state");
        if (empty) empty.remove();
        for (const item of events) {
          if (item.id <= lastEventId) continue;
          lastEventId = Math.max(lastEventId, item.id);
          const article = document.createElement("div");
          article.className = "event";
          const dot = document.createElement("span");
          dot.className = `event-dot ${item.kind}`;
          const body = document.createElement("div");
          const title = document.createElement("b");
          title.textContent = item.title;
          const description = document.createElement("p");
          description.textContent = item.detail;
          const timestamp = document.createElement("small");
          timestamp.textContent = `${item.at.slice(11, 19)} UTC · ${item.kind.toUpperCase()}`;
          body.append(title, description, timestamp);
          article.append(dot, body);
          timeline.append(article);
        }
        timeline.scrollTop = timeline.scrollHeight;
      }

      const status = detail.assessment?.status;
      const statusText = document.querySelector(".status");
      if (statusText && status) {
        statusText.lastChild.textContent = ` ${status.replaceAll("_", " ").toUpperCase()}`;
        statusText.classList.toggle("done", status === "complete");
      }
      if (status && !["running", "ready"].includes(status)) {
        stopPolling();
        notify(status === "complete" ? "Assessment completed." : `Assessment stopped: ${status.replaceAll("_", " ")}.`);
      }
    } catch (error) {
      // A transient polling failure does not change or fabricate assessment state.
    }
  }

  refresh();
  pollTimer = window.setInterval(refresh, 1800);
})();
