const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let token = '', jobs = [], filter = 'all', selected = null, config = {}, activity = null, loading = false, editing = false;
let toastTimer, librarySnapshot = '';
const labels = {REVIEW:'Por revisar', APPROVED:'Aprobado', UPLOADED:'Publicado', ERROR:'Necesita atención', RESEARCHING:'Investigando', GENERATING:'Generando', RESEARCHED:'Listo para generar', REJECTED:'Descartado', UPLOADING:'Envío en curso', UNKNOWN:'Revisar archivos'};
const colors = {REVIEW:'orange', APPROVED:'green', UPLOADED:'blue', ERROR:'red', RESEARCHING:'blue', GENERATING:'blue', RESEARCHED:'neutral', REJECTED:'neutral', UPLOADING:'orange', UNKNOWN:'red'};
Object.assign(labels, {TOPIC_RESEARCHING:'Investigando temas', TOPICS_REVIEW:'Temas por aprobar', TOPIC_APPROVED:'Tema aprobado'});
Object.assign(colors, {TOPIC_RESEARCHING:'blue', TOPICS_REVIEW:'orange', TOPIC_APPROVED:'green'});
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const badge = status => `<span class="badge ${colors[status] || 'neutral'}">${esc(labels[status] || status)}</span>`;
const duration = seconds => { const total = Math.round(seconds || 0); return total ? `${Math.floor(total / 60)}:${String(total % 60).padStart(2,'0')}` : '—'; };
const date = value => { const d = new Date(value); return value && !Number.isNaN(d.valueOf()) ? d.toLocaleDateString('es-PE',{day:'numeric',month:'short',timeZone:'America/Lima'}) : 'Sin fecha'; };
const safeURL = value => { try { const u = new URL(value); return ['https:','http:'].includes(u.protocol) ? u.href : '#'; } catch { return '#'; } };

function errorPanel(error) {
  if(!error) return '';
  const legacy=error.type==='BadRequestError'&&!error.reason;
  const message=legacy?'OpenAI rechazó la solicitud. Este registro anterior no conservó el código del proveedor; todavía no se puede confirmar la causa.':error.message||'Revisa los datos del trabajo antes de reintentar.';
  return `<div class="error-panel"><strong>${esc(error.context||`Fallo en ${error.phase} (${error.type})`)}</strong><p>${esc(message)}</p>${error.diagnostic?`<details><summary>Datos para soporte</summary><p>${esc(error.diagnostic)}</p></details>`:''}${error.recovery?`<p class="small">${esc(error.recovery)}</p>`:''}</div>`;
}

function previewControls(item, editable) {
  if(!editable||item.demo||!item.script.scenes?.length) return '';
  const preferred=item.error?.scene||item.preview_report?.scene||1;
  return `<label>Escena de la muestra<select id="preview-scene">${item.script.scenes.map((s,i)=>`<option value="${i+1}" ${i+1===preferred?'selected':''}>${i+1} · ${esc(s.heading)}</option>`).join('')}</select></label><button class="outline" id="preview-button">Probar voz e imagen</button><p class="small">Genera solo esta escena. Reutiliza recursos sin cambios; los nuevos consumen API.</p>`;
}

function editVisualScene(number) {
  renderTab('edit');
  const field=$(`.edit-scene[data-index="${number-1}"] .edit-visual`);
  field?.scrollIntoView({block:'center'});
  field?.focus({preventScroll:true});
}

async function api(path, data) {
  const options = data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(data)};
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'No se pudo completar la operación.');
  return body;
}
function toast(message, error = false) { clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').classList.toggle('error',error); $('#toast').hidden = false; toastTimer = setTimeout(()=>$('#toast').hidden = true,6500); }
function busy() { return activity?.status === 'RUNNING'; }
async function perform(action) { try { await action(); } catch(error) { if ($('#detail-dialog').open && $('#detail-error')) $('#detail-error').textContent=error.message; toast(error.message,true); } }

async function refresh() {
  if (loading) return;
  loading = true;
  try {
    const [list,status] = await Promise.all([api('/api/jobs'),api('/api/status')]);
    jobs = list.jobs; config = status.configuration; activity = status.activity;
    renderLibrary(); renderStatus();
    if (selected && $('#detail-dialog').open && !editing && !$('#approval-dialog').open && !$('#publish-dialog').open) {
      const current = jobs.find(j=>j.id===selected.id);
      if (current && (current.status !== selected.status || current.updated_at !== selected.updated_at || (activity?.status==='DONE' && (activity.id!==selected.activity_id || selected.activity_status!=='DONE')))) await openJob(selected.id);
    }
  } catch(error) { $('#setup-banner').hidden=false; $('.setup-banner strong').textContent='No se pudo conectar con el agente'; $('.setup-banner p').textContent='Comprueba que la ventana del panel sigue abierta y pulsa Actualizar.'; }
  finally { loading = false; }
}
function renderStatus() {
  $('#environment-label').textContent=config.cloud?'Nube':'Local';
  $('#space-label').textContent=config.cloud?'Estudio privado':'Espacio local';
  $('#space-detail').textContent=config.cloud?'Acceso protegido':'Solo en este equipo';
  $('.schedule-foot').textContent=config.cloud?'Investigación gestionada en el servidor':'Horario gestionado desde Codex';
  $('#config-form').hidden=!!config.cloud;
  if(config.cloud){
    $('#key-help').textContent='Configura OPENAI_API_KEY en las variables de Railway. La clave nunca se muestra en el panel.';
    $('#youtube-help').textContent='Autoriza tu canal desde el panel local y guarda su token en YOUTUBE_TOKEN_JSON, en Railway Variables. Consulta RAILWAY.md.';
    $('#connect-youtube').textContent='Verificar mi canal';
    $('#youtube-next').textContent='El ID del canal aparecerá en los detalles de la operación. Esta verificación no sube videos.';
    $('#schedule-help').textContent='6:00 a. m. · Perú. Activa DAILY_RESEARCH_ENABLED en Railway para investigar y proponer temas. Cada video requiere tu aprobación del tema y del resultado.';
  }
  $('#setup-banner').hidden=!!config.openai_configured;
  $('.setup-banner strong').textContent='Conecta OpenAI para crear videos con voz';
  $('.setup-banner p').textContent='Mientras tanto, puedes explorar el estudio con una demo local.';
  const s = config.schedule?.status;
  $('#schedule-badge').textContent=s==='ACTIVE'?'Programado':s==='PAUSED'?'En pausa':'Sin verificar';
  $('#schedule-badge').className=`badge ${s==='ACTIVE'?'green':'neutral'}`;
  $('#openai-status').textContent=config.openai_configured?'Clave guardada':'Sin configurar';
  $('#youtube-status').textContent=config.youtube_connected?'Token guardado':config.oauth_configured?'Listo para conectar':'Sin configurar';
  $('#activity').hidden=!activity;
  for(const id of ['generate-button','demo-button','daily-button','connect-youtube']) $('#'+id).disabled=busy();
  if(activity){ $('#activity-title').textContent=activity.status==='ERROR'?'La operación se detuvo':activity.label; $('#activity-subtitle').textContent=busy()?'El agente está trabajando. Puedes consultar tus otros videos.':activity.status==='DONE'?'Proceso finalizado. Revisa los resultados en tu biblioteca.':'El proceso necesita atención. Abre los detalles para ver el motivo.'; $('#activity-icon').textContent=busy()?'◌':activity.status==='DONE'?'✓':'!'; $('#activity-log').textContent=(activity.lines||[]).join('\n'); }
}
function renderLibrary() {
  $('#total-count').textContent=jobs.length;
  $('#review-count').textContent=jobs.filter(j=>j.status==='REVIEW').length;
  const query=$('#search').value.toLocaleLowerCase('es');
  const snapshot=JSON.stringify([jobs,filter,query]);
  if(snapshot===librarySnapshot) return;
  librarySnapshot=snapshot;
  const visible=jobs.filter(j=>(filter==='all'||j.status===filter)&&`${j.title} ${j.id}`.toLocaleLowerCase('es').includes(query));
  $('#videos').innerHTML=visible.length?visible.map(j=>`<button class="video-card" data-job="${esc(j.id)}" aria-label="Revisar ${esc(j.title)}"><div class="poster">${j.poster?`<img src="${esc(j.poster)}" alt="" loading="lazy">`:'<span class="poster-placeholder">✦</span>'}${j.ready?'<span class="play">▷</span>':''}${j.demo?'<span class="demo-tag">DEMO</span>':''}<span class="duration">${duration(j.duration)}</span></div><div class="card-content">${badge(j.status)}<h3>${esc(j.title)}</h3><div class="card-bottom"><span>${date(j.created_at)}</span><span>${j.locked?'En proceso':'Abrir revisión ↗'}</span></div></div></button>`).join(''):'<div class="empty">No hay videos en esta vista.<br><small>Escribe un tema o crea una demo para empezar.</small></div>';
  $$('.video-card').forEach(card=>card.addEventListener('click',()=>perform(()=>openJob(card.dataset.job))));
}
function changeFilter(value) { filter=value; $$('.filter').forEach(b=>b.classList.toggle('active',b.dataset.filter===value)); $('#nav-review').classList.toggle('active',value==='REVIEW'); $('#nav-studio').classList.toggle('active',value!=='REVIEW'); renderLibrary(); }

async function create(mode) {
  await api('/api/create',{mode,topic:$('#topic').value});
  toast(mode==='daily'?'Investigando propuestas. Elegirás el tema antes de generar un video.':mode==='demo'?'Preparando tu demo local.':'Generación de tu tema iniciada. Te mostraremos el progreso.');
  await refresh();
}
async function openJob(id) {
  const item=await api('/api/jobs/'+encodeURIComponent(id));
  selected=item;selected.activity_id=activity?.id;selected.activity_status=activity?.status; editing=false;
  $('#detail-title').textContent=item.title;
  if(item.kind==='topic_proposals') return openTopics(item);
  const editable=!['UPLOADING','UPLOADED','RESEARCHING','GENERATING','UNKNOWN'].includes(item.status)&&!item.locked;
  const canApprove=!item.demo&&item.ready&&item.render_current&&['REVIEW','APPROVED'].includes(item.status)&&!item.locked;
  const report=item.report;
  const failedVisual=editable&&item.error?.stage==='image'&&Number.isInteger(item.error.scene)&&item.error.scene>=1&&item.error.scene<=item.script.scenes?.length;
  $('#detail-content').innerHTML=`<div class="detail-grid"><div>${item.video?`<video id="player" class="player" controls preload="metadata" poster="${esc(item.poster||'')}" src="${esc(item.video)}?v=${encodeURIComponent(item.updated_at||item.review_hash)}"></video>`:'<div class="no-video">El video estará disponible al terminar la generación.</div>'}${item.demo?'<p class="small muted">Demo local con audio silencioso. No se puede publicar.</p>':''}<div class="tabs" role="group" aria-label="Contenido del trabajo"><button class="tab active" data-tab="script">Guion</button><button class="tab" data-tab="sources">Fuentes (${item.sources.length})</button><button class="tab" data-tab="research">Investigación</button>${editable&&item.script.scenes?'<button class="tab" data-tab="edit">Editar guion</button>':''}</div><div id="tab-content"></div></div><aside class="detail-aside">${badge(item.status)}<dl class="facts"><dt>Duración</dt><dd>${duration(item.duration)}</dd><dt>Escenas</dt><dd>${item.script.scenes?.length||0}</dd><dt>Fuentes</dt><dd>${item.sources.length}</dd></dl>${errorPanel(item.error)}${failedVisual?`<button class="outline" id="edit-visual-button">Editar imagen de escena ${item.error.scene}</button>`:''}${report?.status==='MEASURED'?'<div class="error-panel">La duración necesita un ajuste del guion.</div>':''}${item.ready&&!item.render_current?'<div class="error-panel">El contenido cambió desde el montaje. Regenera antes de aprobar.</div>':''}${canApprove?'<button class="primary" id="approve-button">Revisar aprobación</button>':''}${item.status==='APPROVED'&&!item.demo?'<button class="primary" id="publish-button">Subir a YouTube</button>':''}${previewControls(item,editable)}${item.preview?`<details><summary>Ver última muestra</summary><p class="small">Escena ${esc(item.preview_report?.scene||1)} · Voz: ${esc(item.preview_report?.voice||'')}. La muestra no cambia el video completo.</p><video class="player" controls preload="metadata" src="${esc(item.preview)}?v=${encodeURIComponent(JSON.stringify(item.preview_report))}"></video></details>`:''}${editable?'<button class="outline" id="regenerate-button">Regenerar con este guion</button><p class="small">Usa la voz y el estilo de Configuración. Reutiliza recursos sin cambios; los nuevos consumen API.</p>':''}${item.status==='ERROR'||item.status==='RESEARCHING'?'<button class="outline" id="retry-button">Reintentar trabajo</button><p class="small">Reutiliza los recursos guardados sin cambios. Lo pendiente o modificado consume API.</p>':''}${editable?'<button class="text-button danger-text" id="reject-button">Descartar video</button>':''}${item.youtube_id?`<a class="text-button" href="https://www.youtube.com/watch?v=${encodeURIComponent(item.youtube_id)}" target="_blank" rel="noopener noreferrer">Ver en YouTube ↗</a>`:''}<p id="detail-error" class="inline-error" role="alert"></p><hr><p class="small">La aprobación y la subida son pasos separados. Tú decides qué se publica.</p><div class="detail-id">${esc(item.id)}</div></aside></div>`;
  $$('.tab').forEach(tab=>tab.addEventListener('click',()=>renderTab(tab.dataset.tab)));
  $('#approve-button')?.addEventListener('click',openApproval);
  $('#publish-button')?.addEventListener('click',openPublish);
  $('#regenerate-button')?.addEventListener('click',()=>perform(()=>jobAction('regenerate')));
  $('#preview-button')?.addEventListener('click',()=>perform(()=>jobAction('preview',{scene:Number($('#preview-scene').value)})));
  $('#edit-visual-button')?.addEventListener('click',()=>editVisualScene(item.error.scene));
  $('#retry-button')?.addEventListener('click',()=>perform(()=>jobAction('retry')));
  $('#reject-button')?.addEventListener('click',()=>perform(async()=>{await jobAction('reject');toast('Video descartado. Puedes regenerarlo cuando quieras.');}));
  renderTab('script');
  if(!$('#detail-dialog').open) $('#detail-dialog').showModal();
}
function openTopics(item) {
  const canChoose=item.status==='TOPICS_REVIEW'&&!item.demo&&!item.locked&&!busy();
  $('#detail-content').innerHTML=`${badge(item.status)}<p>Revisa los temas y sus fuentes. Al pulsar <strong>Aprobar tema y generar video</strong> iniciarás un video de diez minutos con consumo de API. Cuando esté listo, tendrás que revisarlo y aprobarlo antes de subirlo a YouTube.</p>
    ${item.demo?'<p class="error-panel">Simulación local: estos temas son ficticios y no se pueden aprobar para generar videos.</p>':''}
    ${errorPanel(item.error)}
    ${(item.topics||[]).map((t,i)=>{const child=item.selections?.[String(i+1)];return `<article class="scene topic-proposal"><span class="eyebrow">${esc(t.category)} · ${esc(t.event_date)}</span><h3>${i+1}. ${esc(t.title)}</h3><p>${esc(t.summary)}</p><p><strong>Por qué vale la pena:</strong> ${esc(t.reason)}</p><ul class="sources-list">${t.sources.map(url=>`<li><a href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(item.sources.find(s=>s.url===url)?.title||url)} ↗</a></li>`).join('')}</ul>${child?`<button class="outline" data-selected-job="${esc(child)}">Tema aprobado · abrir trabajo</button>`:`<button class="primary" data-topic-number="${i+1}" ${canChoose?'':'disabled'}>Aprobar tema y generar video</button>`}</article>`;}).join('')||'<p class="muted">Las propuestas aparecerán cuando termine la investigación.</p>'}
    ${['ERROR','TOPIC_RESEARCHING'].includes(item.status)&&!item.locked&&!busy()&&!item.demo?'<button class="outline" id="retry-topics">Reintentar investigación de temas</button>':''}
    <details><summary>Ver investigación completa</summary><pre class="research-text" id="topics-research"></pre></details><p id="detail-error" class="inline-error" role="alert"></p><div class="detail-id">${esc(item.id)}</div>`;
  $('#topics-research').textContent=item.research||'Todavía no hay investigación guardada.';
  $$('[data-topic-number]').forEach(button=>button.addEventListener('click',()=>perform(async()=>{
    button.disabled=true;
    try {
      const result=await api(`/api/jobs/${item.id}/select-topic`,{number:Number(button.dataset.topicNumber),confirmed:true,topics_hash:item.topics_hash});
      await refresh();await openJob(result.job_id);toast('Tema aprobado. El video quedará pendiente de una nueva revisión.');
    } catch(error) {button.disabled=false;throw error;}
  })));
  $$('[data-selected-job]').forEach(button=>button.addEventListener('click',()=>perform(()=>openJob(button.dataset.selectedJob))));
  $('#retry-topics')?.addEventListener('click',()=>perform(()=>jobAction('retry')));
  if(!$('#detail-dialog').open) $('#detail-dialog').showModal();
}

function renderTab(tab) {
  editing=tab==='edit'; $$('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  const j=selected, container=$('#tab-content');
  if(tab==='script') container.innerHTML=j.script.scenes?`<p class="muted">${esc(j.script.description)}</p>`+j.script.scenes.map((scene,i)=>`<article class="scene"><h4><span class="muted">${String(i+1).padStart(2,'0')} · </span>${esc(scene.heading)}</h4><p>${esc(scene.narration)}</p>${scene.visual_description?`<p><strong>Imagen elegida:</strong> ${esc(scene.visual_description)}</p>`:''}<ul>${scene.bullets.map(b=>`<li>${esc(b)}</li>`).join('')}</ul></article>`).join(''):'<p class="muted">Todavía no hay un guion.</p>';
  if(tab==='sources') container.innerHTML=`<ul class="sources-list">${j.sources.map(s=>`<li><a href="${esc(safeURL(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a><small>${esc(s.url)}</small></li>`).join('')}</ul>`;
  if(tab==='research'){ container.innerHTML='<pre class="research-text"></pre>'; $('.research-text').textContent=j.research||'Esta demo no incluye investigación de actualidad.'; }
  if(tab==='edit') {
    container.innerHTML=`<form id="edit-form"><p class="error-panel">Guardar cambios anula la aprobación. Después debes regenerar el video.</p><label>Título<input id="edit-title" maxlength="100" value="${esc(j.script.title)}" required></label><label>Descripción<textarea id="edit-description" maxlength="1500">${esc(j.script.description)}</textarea></label>${j.script.scenes.map((s,i)=>`<div class="edit-scene" data-index="${i}"><strong>Escena ${i+1}</strong><label>Encabezado<input class="edit-heading" maxlength="90" value="${esc(s.heading)}" required></label><label>Ideas de la escena · visibles solo en modo láminas<textarea class="edit-bullets" rows="3" required>${esc(s.bullets.join('\n'))}</textarea></label><label>Narración<textarea class="edit-narration" maxlength="1800" rows="5" required>${esc(s.narration)}</textarea></label><label>Imagen de esta escena (opcional)<textarea class="edit-visual" maxlength="1200" rows="3" placeholder="Describe un paisaje, objetos o una escena apropiada para el documental.">${esc(s.visual_description||'')}</textarea><span class="small">Describe qué quieres mostrar. Este texto solo define la imagen y no se narra. Si lo dejas vacío, se usará la narración como referencia.</span></label></div>`).join('')}<p id="edit-error" class="inline-error" role="alert"></p><button class="primary" type="submit">Guardar guion</button></form>`;
    $('#edit-form').addEventListener('submit',async event=>{event.preventDefault(); const copy=structuredClone(j.script); copy.title=$('#edit-title').value;copy.description=$('#edit-description').value;$$('.edit-scene').forEach(el=>{const scene=copy.scenes[Number(el.dataset.index)];scene.heading=$('.edit-heading',el).value;scene.narration=$('.edit-narration',el).value;scene.bullets=$('.edit-bullets',el).value.split('\n').map(x=>x.trim()).filter(Boolean);const visual=$('.edit-visual',el).value.trim();if(visual)scene.visual_description=visual;else delete scene.visual_description;});try{await api(`/api/jobs/${j.id}/save-script`,{script:copy,script_hash:j.script_hash});editing=false;await openJob(j.id);await refresh();toast('Guion guardado. Regenera para aplicar los cambios al video.');}catch(e){$('#edit-error').textContent=e.message;}});
  }
}
async function jobAction(action, data={}) { const id=selected.id;await api(`/api/jobs/${id}/${action}`,data);await refresh();if(['approve','reject','save-script'].includes(action))await openJob(id); }
function openApproval() { $('#approval-form').reset();$('#approval-error').textContent='';$('#approval-title').textContent=selected.title;const pub=selected.publication;if(pub){$('#channel-id').value=pub.channel_id;$('#privacy').value=pub.privacy;}$('#approval-dialog').showModal(); }
function openPublish() { const p=selected.publication;$('#publish-form').reset();$('#publish-error').textContent='';$('#publish-summary').innerHTML=`<strong>${esc(selected.title)}</strong><p>Canal: ${esc(p.channel_id)}</p><p>Visibilidad: ${esc({private:'Privado',unlisted:'No listado',public:'Público'}[p.privacy])}</p><p>Dirigido a niños: ${p.made_for_kids?'Sí':'No'}<br>Contenido sintético realista: ${p.synthetic_media?'Sí':'No'}</p>`;$('#publish-dialog').showModal(); }
function showConfig(){ renderStatus();$('#config-error').textContent='';$('#production-message').textContent='';$('#voice').value=config.production?.voice||'cedar';$('#visual-mode').value=config.production?.visual_mode||'images';$('#config-dialog').showModal(); }

$('#create-form').addEventListener('submit',event=>{event.preventDefault();perform(()=>create('topic'));});
$('#demo-button').addEventListener('click',()=>perform(()=>create('demo')));
$('#daily-button').addEventListener('click',()=>perform(()=>create('daily')));
$('#refresh-button').addEventListener('click',refresh);
$('#search').addEventListener('input',renderLibrary);
$$('.filter').forEach(b=>b.addEventListener('click',()=>changeFilter(b.dataset.filter)));
$('#nav-review').addEventListener('click',()=>{changeFilter('REVIEW');$('.library').scrollIntoView({behavior:'smooth'});});
$('#nav-studio').addEventListener('click',()=>{changeFilter('all');window.scrollTo({top:0,behavior:'smooth'});});
$('#nav-config').addEventListener('click',showConfig);$('#setup-config').addEventListener('click',showConfig);
$$('[data-close]').forEach(b=>b.addEventListener('click',()=>$('#'+b.dataset.close).close()));
$('#detail-dialog').addEventListener('close',()=>{$('#player')?.pause();editing=false;});
$('#config-dialog').addEventListener('close',()=>$('#api-key').value='');
$('#toggle-log').addEventListener('click',()=>{$('#activity-log').hidden=!$('#activity-log').hidden;$('#toggle-log').textContent=$('#activity-log').hidden?'Ver detalles':'Ocultar detalles';});
$('#approval-form').addEventListener('submit',async event=>{event.preventDefault();const data={reviewed:$('#reviewed').checked,confirmation:$('#approval-confirmation').value,review_hash:selected.review_hash,publication:{channel_id:$('#channel-id').value.trim(),privacy:$('#privacy').value,made_for_kids:$('#kids').value==='yes',synthetic_media:$('#synthetic').value==='yes'}};try{await api(`/api/jobs/${selected.id}/approve`,data);$('#approval-dialog').close();await openJob(selected.id);await refresh();toast('Aprobación guardada. El video todavía no se ha subido.');}catch(e){$('#approval-error').textContent=e.message;}});
$('#publish-form').addEventListener('submit',async event=>{event.preventDefault();try{await api(`/api/jobs/${selected.id}/publish`,{confirmation:$('#publish-confirmation').value,approved_hash:selected.approved_hash});$('#publish-dialog').close();$('#detail-dialog').close();await refresh();toast('Subida iniciada. Consulta el progreso en el estudio.');}catch(e){$('#publish-error').textContent=e.message;}});
$('#config-form').addEventListener('submit',async event=>{event.preventDefault();try{await api('/api/config',{openai_key:$('#api-key').value.trim()});$('#api-key').value='';$('#config-error').textContent='Clave guardada. Se verificará al generar tu primer video.';await refresh();}catch(e){$('#config-error').textContent=e.message;}});
$('#connect-youtube').addEventListener('click',async()=>{try{await api('/api/channel',{});$('#config-dialog').close();await refresh();$('#activity-log').hidden=false;toast(config.cloud?'Verificando el canal autorizado.':'Completa la conexión en la ventana de Google.');}catch(e){$('#config-error').textContent=e.message;}});
$('#date-label').textContent=new Date().toLocaleDateString('es-PE',{weekday:'long',day:'numeric',month:'long',timeZone:'America/Lima'});
(async()=>{try{token=(await api('/api/session')).token;await refresh();setInterval(refresh,3500);}catch(e){toast('No se pudo abrir la sesión. Actualiza la página.',true);}})();

$('#production-form').addEventListener('submit',async event=>{event.preventDefault();try{await api('/api/production',{voice:$('#voice').value,visual_mode:$('#visual-mode').value});await refresh();$('#production-message').textContent='Preferencias guardadas. Abre un video y prueba una escena o regenera para aplicarlas.';}catch(e){$('#production-message').textContent=e.message;}});
