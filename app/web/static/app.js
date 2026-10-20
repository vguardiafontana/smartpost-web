const $=id=>document.getElementById(id);
let previewId=null,currentJobId=localStorage.getItem('smartpost_last_job')||null,pollTimer=null,currentReportJobId=localStorage.getItem('smartpost_last_report_job')||null,reportPollTimer=null,lastSearchRows=[],searchPhotoSortMode=0;

async function api(path,options={}){
  const res=await fetch(path,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
  if(res.status===401){showLogin();throw new Error('Sesión vencida');}
  let data={};try{data=await res.json();}catch{}
  if(!res.ok){const error=new Error(data.detail||`Error HTTP ${res.status}`);error.status=res.status;throw error;}
  return data;
}
function toast(msg){$('toast').textContent=msg;$('toast').classList.remove('hidden');setTimeout(()=>$('toast').classList.add('hidden'),2600)}
function showLogin(){$('loginView').classList.remove('hidden');$('appView').classList.add('hidden');$('logoutBtn').classList.add('hidden');$('pageTitle').textContent='SmartPost'}
function showApp(){$('loginView').classList.add('hidden');$('appView').classList.remove('hidden');$('logoutBtn').classList.remove('hidden')}
function step(name){['homeStep','composeStep','previewStep','jobStep','searchStep','reportsStep','visitPhotosStep'].forEach(id=>$(id).classList.toggle('hidden',id!==name));$('pageTitle').textContent=name==='composeStep'||name==='previewStep'||name==='jobStep'?'Cambio de estado v2':name==='searchStep'?'Búsqueda de guías':name==='reportsStep'?'Reportes y Visitas':name==='visitPhotosStep'?'Visitas sin foto':'SmartPost'}
function esc(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function safeUrl(v){const s=String(v||'');return /^https:\/\//i.test(s)?s:''}

async function init(){
  if('serviceWorker' in navigator){navigator.serviceWorker.register('/static/sw.js').catch(()=>{})}
  try{await api('/api/session');showApp();await loadStates();if(currentJobId){step('jobStep');pollJob(currentJobId)}else step('homeStep')}catch{showLogin()}
}
async function loadStates(){const d=await api('/api/states');$('stateSelect').innerHTML=d.states.map(s=>`<option value="${s.id}">${esc(s.label)}</option>`).join('')}

$('loginForm').addEventListener('submit',async e=>{e.preventDefault();$('loginError').textContent='';try{await api('/api/auth/login',{method:'POST',body:JSON.stringify({pin:$('pinInput').value})});$('pinInput').value='';showApp();await loadStates();step('homeStep')}catch(err){$('loginError').textContent=err.message}})
$('logoutBtn').addEventListener('click',async()=>{try{await api('/api/auth/logout',{method:'POST'})}catch{}localStorage.removeItem('smartpost_last_job');currentJobId=null;showLogin()})
$('openV2Btn').addEventListener('click',()=>step('composeStep'));
$('openSearchBtn').addEventListener('click',()=>step('searchStep'));
$('openReportsBtn').addEventListener('click',()=>{step('reportsStep');if(currentReportJobId)pollReportJob(currentReportJobId)});
document.querySelectorAll('[data-home]').forEach(b=>b.addEventListener('click',()=>{clearTimeout(pollTimer);clearTimeout(reportPollTimer);step('homeStep')}));

$('previewBtn').addEventListener('click',async()=>{
  const text=$('bulkInput').value.trim();if(!text)return toast('Pegá al menos una guía o remito.');
  const date=$('stateDate').value;if(!date)return toast('Elegí la fecha de la planilla y del cambio.');
  $('previewBtn').disabled=true;$('previewBtn').textContent='Buscando…';
  try{
    const d=await api('/api/preview',{method:'POST',body:JSON.stringify({text,state_id:Number($('stateSelect').value),date})});previewId=d.preview_id;
    $('previewMeta').innerHTML=`<strong>${d.count}</strong> entrada(s) → <strong>${esc(d.state_label)}</strong> · Fecha: <strong>${esc(d.selected_date.split('-').reverse().join('/'))}</strong>`;
    $('previewRows').innerHTML=d.rows.map(r=>{
      const resolved=r.resolution_status==='resolved';const same=!!r.already_assigned;
      const badge=same?'<span class="badge same">Estado ya asignado</span>':resolved?'<span class="badge ok">Lista</span>':'<span class="badge bad">No resuelta</span>';
      const detail=resolved?`Guía ${esc(r.retiro_id||r.guia||'')} · ${esc(r.detected_type||'')} · Estado actual: ${esc(r.current_state||'—')}`:esc(r.message||'No encontrada');
      return `<div class="row"><div class="row-top"><strong>${esc(r.input_value||'')}</strong>${badge}</div><div class="row-detail">${detail}</div></div>`
    }).join('');step('previewStep')
  }catch(err){toast(err.message)}finally{$('previewBtn').disabled=false;$('previewBtn').textContent='Ver vista previa'}
})
$('backBtn').addEventListener('click',()=>step('composeStep'))
$('confirmBtn').addEventListener('click',async()=>{if(!previewId)return; $('confirmBtn').disabled=true;try{const job=await api('/api/jobs',{method:'POST',body:JSON.stringify({preview_id:previewId})});previewId=null;currentJobId=job.id;localStorage.setItem('smartpost_last_job',job.id);step('jobStep');$('summaryCard').classList.add('hidden');pollJob(job.id)}catch(err){toast(err.message)}finally{$('confirmBtn').disabled=false}})

function statusBadge(row){
  if(row.resolution_status==='resolved'&&row.change_status==='ok')return ['Realizada','ok'];
  if(row.resolution_status==='resolved'&&row.change_status==='already_assigned')return ['Estado ya asignado','same'];
  if(row.resolution_status==='resolved'&&row.change_status==='warning')return ['Advertencia','warn'];
  if(row.resolution_status==='duplicate')return ['Duplicada','warn'];
  return ['Error','bad'];
}
function renderJob(job){
  const p=job.progress||{},total=Number(p.total||job.identifiers?.length||0),cur=Number(p.current||0),pct=total?Math.min(100,Math.round(cur/total*100)):0;
  $('progressBar').style.width=`${job.status==='completed'?100:pct}%`;$('progressText').textContent=(job.selected_date?job.selected_date.split('-').reverse().join('/')+' · ':'')+(p.message||job.status);$('jobTitle').textContent=job.status==='completed'?'Terminado':job.status==='failed'||job.status==='interrupted'?'Interrumpido':'Procesando…';
  if(['completed','failed','interrupted'].includes(job.status)){
    $('summaryCard').classList.remove('hidden');const s=job.summary||{};
    $('summaryGrid').innerHTML=[['Realizadas',s.success||0],['Estado ya asignado',s.already_assigned||0],['Errores',(s.errors||0)+(s.unresolved||0)],['Advertencias',s.warnings||0]].map(([l,n])=>`<div class="summary-item"><span class="summary-num">${n}</span><span class="summary-label">${l}</span></div>`).join('');
    $('resultRows').innerHTML=(job.results||[]).map(r=>{const [txt,cls]=statusBadge(r);const reason=r.change_message||r.message||'';return `<div class="row"><div class="row-top"><strong>${esc(r.input_value||r.retiro_id||'')}</strong><span class="badge ${cls}">${txt}</span></div>${reason?`<div class="row-detail">${esc(reason)}</div>`:''}</div>`}).join('');
    const hasErrors=job.status!=='completed'||((s.errors||0)+(s.unresolved||0)>0);$('retryBtn').classList.toggle('hidden',!hasErrors);
  }
}
async function pollJob(id){clearTimeout(pollTimer);try{const job=await api(`/api/jobs/${id}`);renderJob(job);if(['queued','running'].includes(job.status)){pollTimer=setTimeout(()=>pollJob(id),1000)}}catch(err){toast(err.message);pollTimer=setTimeout(()=>pollJob(id),3000)}}
$('retryBtn').addEventListener('click',async()=>{if(!currentJobId)return;try{const job=await api(`/api/jobs/${currentJobId}/retry`,{method:'POST'});currentJobId=job.id;localStorage.setItem('smartpost_last_job',job.id);$('summaryCard').classList.add('hidden');pollJob(job.id)}catch(err){toast(err.message)}})
$('newBatchBtn').addEventListener('click',()=>{localStorage.removeItem('smartpost_last_job');currentJobId=null;previewId=null;$('bulkInput').value='';step('composeStep')})

function searchRow(r){
  if(r.error){return `<div class="row"><div class="row-top"><strong>${esc(r.entrada||'')}</strong><span class="badge bad">Error</span></div><div class="row-detail">${esc(r.error)}</div></div>`}
  const guide=safeUrl(r.show_url),dist=safeUrl(r.distribuidor_url);
  const parts=[
    ['Guía',r.guia],['Guía agente',r.guia_agente],['Remito',r.remito],['Cliente',r.cliente],['Servicio',r.servicio],
    ['Destinatario',r.destinatario],['Domicilio',r.domicilio],['Localidad',r.localidad],['Provincia',r.provincia],['CP',r.codigo_postal],
    ['Teléfono',r.telefono],['Foto',r.foto||'No'],['Estado',r.estado],['Distribuidor',r.distribuidor_nombre||r.distribuidor_raw],['DNI distribuidor',r.distribuidor_dni],['Tel. distribuidor',r.distribuidor_telefono]
  ].filter(([,v])=>String(v||'').trim());
  return `<div class="row"><div class="row-top"><strong>${esc(r.guia||r.entrada||'Envío')}</strong><span class="badge ok">Encontrado</span></div><div class="detail-grid">${parts.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}</div><div class="row-actions">${guide?`<a class="link-btn" target="_blank" rel="noopener" href="${esc(guide)}">Abrir guía</a>`:''}${dist?`<a class="link-btn secondary-link" target="_blank" rel="noopener" href="${esc(dist)}">Distribuidor</a>`:''}</div></div>`
}
function renderSearchRows(){
  const rows=[...lastSearchRows];
  if(searchPhotoSortMode){
    const yesFirst=searchPhotoSortMode===1;
    rows.sort((a,b)=>{
      if(a.error&&!b.error)return 1;if(!a.error&&b.error)return -1;if(a.error&&b.error)return (a._searchIndex||0)-(b._searchIndex||0);
      const av=String(a.foto||'No').toLowerCase().startsWith('s')?1:0,bv=String(b.foto||'No').toLowerCase().startsWith('s')?1:0;
      if(av!==bv)return yesFirst?bv-av:av-bv;
      return (a._searchIndex||0)-(b._searchIndex||0);
    });
  }
  renderGuideTable('searchRows',rows,true);
  $('searchPhotoSort').textContent=searchPhotoSortMode===1?'Foto · Sí primero':searchPhotoSortMode===2?'Foto · No primero':'Foto ↕';
}
$('searchPhotoSort').addEventListener('click',()=>{if(!lastSearchRows.length)return;searchPhotoSortMode=searchPhotoSortMode===1?2:1;renderSearchRows()});
$('searchBtn').addEventListener('click',async()=>{
  const text=$('searchInput').value.trim();if(!text)return toast('Pegá al menos una guía, remito o guía agente.');
  $('searchBtn').disabled=true;$('searchBtn').textContent='Buscando…';$('searchResultsCard').classList.add('hidden');
  try{const d=await api('/api/search-guides',{method:'POST',body:JSON.stringify({text})});$('searchSummary').innerHTML=`<strong>${d.found}</strong> encontrado(s) · <strong>${d.errors}</strong> sin resolver/error(es)`;lastSearchRows=d.rows.map((r,i)=>({...r,_searchIndex:i}));searchPhotoSortMode=0;renderSearchRows();$('searchResultsCard').classList.remove('hidden')}catch(err){toast(err.message)}finally{$('searchBtn').disabled=false;$('searchBtn').textContent='Buscar'}
});


function localDateISO(){const p=new Intl.DateTimeFormat('en-US',{timeZone:'America/Montevideo',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()),v=t=>p.find(x=>x.type===t).value;return `${v('year')}-${v('month')}-${v('day')}`}
if($('reportsDate')&&!$('reportsDate').value)$('reportsDate').value=localDateISO();
if($('stateDate')&&!$('stateDate').value)$('stateDate').value=localDateISO();

$('generateReportsBtn').addEventListener('click',async()=>{
  const date=$('reportsDate').value;if(!date)return toast('Elegí una fecha.');
  $('generateReportsBtn').disabled=true;$('generateReportsBtn').textContent='Iniciando…';
  try{const job=await api('/api/report-jobs',{method:'POST',body:JSON.stringify({date})});currentReportJobId=job.id;localStorage.setItem('smartpost_last_report_job',job.id);$('reportsProgressCard').classList.remove('hidden');$('reportsResultsCard').classList.add('hidden');pollReportJob(job.id)}catch(err){toast(err.message)}finally{$('generateReportsBtn').disabled=false;$('generateReportsBtn').textContent='Generar reportes'}
});
function reportArtifactRow(job,a){
  if(a.kind==='all')return `<div class="row report-all"><div class="row-top"><strong>Todos juntos</strong><span class="badge ok">ZIP</span></div><div class="row-actions"><a class="link-btn download-big" href="/api/report-jobs/${job.id}/artifacts/${a.id}">Descargar todo</a></div></div>`;
  const isVisits=a.kind==='visitas';
  return `<div class="row"><div class="row-top"><strong>${esc(isVisits?'VISITAS':a.seller)}</strong><span class="badge ok">Listo</span></div><div class="row-detail">${esc(a.filename)}</div><div class="row-actions"><a class="link-btn" href="/api/report-jobs/${job.id}/artifacts/${a.id}">Descargar</a></div>${a.message?`<label class="copy-label">Mensaje</label><textarea class="message-box" readonly>${esc(a.message)}</textarea><button class="copy-btn secondary full" data-copy="${encodeURIComponent(a.message)}">Copiar mensaje</button>`:''}</div>`
}
async function copyText(text){try{await navigator.clipboard.writeText(text);toast('Mensaje copiado')}catch{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast('Mensaje copiado')}}
function bindCopyButtons(){document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>copyText(decodeURIComponent(b.dataset.copy||'')))}
function renderReportJob(job){
  const p=job.progress||{},total=Number(p.total||4),cur=Number(p.current||0),pct=total?Math.min(100,Math.round(cur/total*100)):0;
  $('reportsProgressBar').style.width=`${job.status==='completed'?100:pct}%`;$('reportsProgressText').textContent=p.message||job.status;$('reportsJobTitle').textContent=job.status==='completed'?'Terminado':job.status==='failed'||job.status==='interrupted'?'Interrumpido':'Generando…';
  if(['completed','failed','interrupted'].includes(job.status)){
    $('reportsResultsCard').classList.remove('hidden');
    if(job.status==='completed'){
      const reports=(job.artifacts||[]).filter(a=>a.kind==='report').length,vis=(job.artifacts||[]).some(a=>a.kind==='visitas');
      const nodata=(job.no_data||[]).length?` · ${(job.no_data||[]).length} cliente(s) sin guías`:'';
      $('reportsMeta').innerHTML=`<strong>${reports}</strong> reporte(s)${vis?' · VISITAS listo':''}${nodata}`;
      $('reportsRows').innerHTML=(job.artifacts||[]).map(a=>reportArtifactRow(job,a)).join('');bindCopyButtons();$('retryReportsBtn').classList.add('hidden');
    }else{$('reportsMeta').textContent='La generación no terminó.';$('reportsRows').innerHTML='<div class="row"><div class="row-detail">Podés reintentar. El detalle técnico queda en los logs.</div></div>';$('retryReportsBtn').classList.remove('hidden')}
  }
}
async function pollReportJob(id){clearTimeout(reportPollTimer);try{const job=await api(`/api/report-jobs/${id}`);renderReportJob(job);if(['queued','running'].includes(job.status))reportPollTimer=setTimeout(()=>pollReportJob(id),1200)}catch(err){toast(err.message);reportPollTimer=setTimeout(()=>pollReportJob(id),3000)}}
$('retryReportsBtn').addEventListener('click',async()=>{if(!currentReportJobId)return;try{const job=await api(`/api/report-jobs/${currentReportJobId}/retry`,{method:'POST'});currentReportJobId=job.id;localStorage.setItem('smartpost_last_report_job',job.id);$('reportsResultsCard').classList.add('hidden');pollReportJob(job.id)}catch(err){toast(err.message)}})

// Mismo orden de columnas que Windows. Los identificadores siempre son texto.
const guideColumns=[
  ['guia','Nro Guía'],['guia_agente','Guía Agente'],['remito','Remito'],['cliente','Cliente'],
  ['servicio','Servicio'],['destinatario','Destinatario'],['domicilio','Domicilio'],['localidad','Localidad'],
  ['provincia','Provincia'],['codigo_postal','Código postal'],['telefono','Teléfono'],['foto','Foto'],
  ['estado','Estado'],['distribuidor_nombre','Distribuidor']
];
function guideValue(row,key){
  const value=key==='distribuidor_nombre'?(row.distribuidor_nombre||row.distribuidor_raw):row[key];
  return value===null||value===undefined||String(value).trim()===''?'—':String(value);
}
function guideTSV(rows,columns=guideColumns){return rows.map(row=>columns.map(([key])=>guideValue(row,key).replace(/[\t\r\n]+/g,' ')).join('\t')).join('\n')}
async function copyGuideText(text){
  try{await navigator.clipboard.writeText(text);toast('Guías copiadas')}
  catch{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();const ok=document.execCommand('copy');ta.remove();toast(ok?'Guías copiadas':'No se pudo copiar. Seleccioná el texto de la tabla.');}
}
function renderGuideTable(targetId,rows,contacts=false,page=0){
  const target=$(targetId),size=100,start=page*size,visible=rows.slice(start,start+size);
  const columns=contacts?[...guideColumns,['distribuidor_dni','DNI distribuidor'],['distribuidor_telefono','Tel. distribuidor']]:guideColumns;
  if(!rows.length){target.innerHTML='<p class="muted">No hay guías que coincidan con este filtro.</p>';target.onclick=null;return;}
  target.innerHTML=`<div class="guide-tools"><span>${start+1}–${Math.min(start+size,rows.length)} de ${rows.length} guías</span><button class="secondary" data-guide-action="copy-all">Copiar guías</button></div><p class="muted small">Deslizá la tabla hacia los costados para ver todas las columnas.</p><div class="guide-table-scroll" tabindex="0" role="region" aria-label="Resultados de guías"><table class="guide-table"><thead><tr>${columns.map(([,label])=>`<th scope="col">${esc(label)}</th>`).join('')}<th scope="col">Acción</th></tr></thead><tbody>${visible.map((row,i)=>{
    if(row.error)return `<tr><td>${esc(row.entrada||'—')}</td><td colspan="${columns.length}">${esc(row.error)}</td></tr>`;
    const url=safeUrl(row.show_url);
    return `<tr>${columns.map(([key])=>`<td>${esc(guideValue(row,key))}</td>`).join('')}<td class="guide-actions"><button class="secondary" data-guide-action="copy" data-index="${start+i}">Copiar</button>${url?`<a class="link-btn" target="_blank" rel="noopener" href="${esc(url)}">Abrir guía</a>`:''}</td></tr>`;
  }).join('')}</tbody></table></div>${rows.length>size?`<div class="guide-tools"><button class="secondary" data-guide-action="prev" ${page===0?'disabled':''}>Anterior</button><span>Página ${page+1} de ${Math.ceil(rows.length/size)}</span><button class="secondary" data-guide-action="next" ${start+size>=rows.length?'disabled':''}>Siguiente</button></div>`:''}`;
  target.onclick=e=>{
    const button=e.target.closest('[data-guide-action]');if(!button)return;
    const action=button.dataset.guideAction;
    if(action==='copy')copyGuideText(guideTSV([rows[Number(button.dataset.index)]],columns));
    else if(action==='copy-all')copyGuideText(guideTSV(rows.filter(row=>!row.error),columns));
    else if(action==='prev'&&page>0)renderGuideTable(targetId,rows,contacts,page-1);
    else if(action==='next'&&start+size<rows.length)renderGuideTable(targetId,rows,contacts,page+1);
  };
}

let visitPhotoChoice='No',visitPhotoResult=null,visitPhotoTimer=null;
let visitPhotoJobId=localStorage.getItem('smartpost_visit_photos')||null;
function renderVisitPhotos(){
  if(!visitPhotoResult)return;
  const data=visitPhotoResult,rows=data.rows.filter(r=>r.foto===visitPhotoChoice),unknown=data.rows.filter(r=>r.foto==='Sin verificar');
  $('visitPhotosResults').classList.remove('hidden');
  $('visitPhotosSummary').textContent=`${data.date.split('-').reverse().join('/')} · ${rows.length} visitas ${visitPhotoChoice==='Sí'?'con':'sin'} foto · ${data.rows.length} revisadas · ${unknown.length} sin verificar`;
  renderGuideTable('visitPhotosRows',rows);
  $('visitPhotosUnknown').classList.toggle('hidden',!unknown.length);
  $('visitPhotosUnknownTitle').textContent=`${unknown.length} guías sin verificar`;
  renderGuideTable('visitPhotosUnknownRows',unknown);
}
for(const [id,value] of [['visitPhotoYes','Sí'],['visitPhotoNo','No']]){
  $(id).addEventListener('click',()=>{
    visitPhotoChoice=value;
    for(const [button,choice] of [['visitPhotoYes','Sí'],['visitPhotoNo','No']]){
      $(button).className=choice===value?'primary':'secondary';$(button).setAttribute('aria-pressed',String(choice===value));
    }
    renderVisitPhotos();
  });
}
async function pollVisitPhotos(id,retries=0){
  clearTimeout(visitPhotoTimer);
  try{
    const job=await api(`/api/visit-photo-jobs/${id}`);
    if(visitPhotoJobId!==id)return;
    $('visitPhotosProgress').textContent=job.message;
    const active=['queued','running'].includes(job.status);
    $('queryVisitPhotos').disabled=active;
    if(active)visitPhotoTimer=setTimeout(()=>pollVisitPhotos(id),1500);
    else if(job.status==='completed'){visitPhotoResult=job;renderVisitPhotos();}
  }catch(err){
    if(visitPhotoJobId!==id)return;
    if((!err.status||[502,503,504].includes(err.status))&&retries<6){
      $('visitPhotosProgress').textContent='Reconectando con el servidor…';$('queryVisitPhotos').disabled=true;
      visitPhotoTimer=setTimeout(()=>pollVisitPhotos(id,retries+1),Math.min(2000*2**retries,15000));return;
    }
    if(err.status===404){visitPhotoJobId=null;localStorage.removeItem('smartpost_visit_photos');}
    $('visitPhotosProgress').textContent=err.message;$('queryVisitPhotos').disabled=false;
  }
}
$('openVisitPhotosBtn').addEventListener('click',()=>{step('visitPhotosStep');if(visitPhotoJobId)pollVisitPhotos(visitPhotoJobId)});
$('queryVisitPhotos').addEventListener('click',async()=>{
  $('queryVisitPhotos').disabled=true;$('visitPhotosResults').classList.add('hidden');visitPhotoResult=null;
  $('visitPhotosProgress').textContent='Iniciando consulta…';
  try{
    const job=await api('/api/visit-photo-jobs',{method:'POST'});visitPhotoJobId=job.id;
    localStorage.setItem('smartpost_visit_photos',job.id);pollVisitPhotos(job.id);
  }catch(err){$('visitPhotosProgress').textContent=err.message;$('queryVisitPhotos').disabled=false;}
});
$('logoutBtn').addEventListener('click',()=>{
  clearTimeout(visitPhotoTimer);visitPhotoJobId=null;visitPhotoResult=null;
  localStorage.removeItem('smartpost_visit_photos');$('visitPhotosRows').innerHTML='';$('visitPhotosUnknownRows').innerHTML='';
  $('visitPhotosResults').classList.add('hidden');$('visitPhotosProgress').textContent='';$('queryVisitPhotos').disabled=false;
});

init();
