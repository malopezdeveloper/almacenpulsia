(function(){
  function onBoard(){return !!document.getElementById('queueBody')&&!!document.getElementById('unitForm')}
  if(!onBoard())return;
  const csrfEl=document.querySelector('#unitForm input[name=csrfmiddlewaretoken]');
  const csrf=csrfEl?csrfEl.value:'';const workerZone=document.getElementById('workerZone');let openPallets=[];
  async function syncDeclaredZone(){if(!workerZone||!workerZone.value)return;try{const body=new URLSearchParams({zone_id:workerZone.value});await fetch('/produccion/pizarra/zona-declarada/',{method:'POST',headers:{'X-CSRFToken':csrf,'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'},body:body.toString()})}catch(e){console.warn('PULSIA: no se pudo sincronizar la zona declarada',e)}}
  if(workerZone){workerZone.addEventListener('change',syncDeclaredZone);setTimeout(syncDeclaredZone,50)}
  function ensureCounterBar(){let bar=document.getElementById('boardCounters');if(bar)return bar;bar=document.createElement('div');bar.id='boardCounters';bar.style.cssText='display:flex;gap:6px;flex-wrap:wrap;align-items:center;min-height:24px;padding:2px 1px;font-size:11px;font-weight:800';const form=document.getElementById('unitForm');form.parentNode.insertBefore(bar,form);return bar}
  function drawCounters(counters){const bar=ensureCounterBar(),list=(counters||[]).filter(x=>Number(x.count)>0);if(!list.length){bar.innerHTML='<span style="color:#748199">Terminadas hoy: 0</span>';return}bar.innerHTML=list.map(x=>'<span style="display:inline-block;padding:3px 7px;border:1px solid #dfe5ed;border-radius:999px;background:#fff">'+escapeHtml(x.label)+': '+Number(x.count)+' ud.</span>').join('')}
  function escapeHtml(v){const d=document.createElement('div');d.textContent=v==null?'':String(v);return d.innerHTML}
  async function refreshAux(){try{const [queueResp,palletResp]=await Promise.all([fetch('/produccion/pizarra/abiertas/',{headers:{'X-Requested-With':'XMLHttpRequest'}}),fetch('/pedidos/palets/abiertos/',{headers:{'X-Requested-With':'XMLHttpRequest'}})]);if(queueResp.ok){const q=await queueResp.json();drawCounters(q.counters||[])}if(palletResp.ok){const p=await palletResp.json();openPallets=p.results||[];decorateDestinations()}}catch(e){console.warn('PULSIA: no se pudieron actualizar contadores/palets',e)}}
  function rowZoneText(select){const tr=select.closest('tr');if(!tr)return '';const cells=tr.querySelectorAll('td');return (cells[6]?cells[6].textContent:'').trim().toLocaleLowerCase('es')}
  function isQualityRow(select){return rowZoneText(select).includes('calidad')}function isPaintRow(select){return rowZoneText(select).includes('pintura')}
  function decorateDestinations(){const headers=document.querySelectorAll('.queue-table thead th');if(headers[9])headers[9].textContent='Destino';document.querySelectorAll('.dest-select').forEach(sel=>{const empty=[...sel.options].find(o=>!o.value);if(empty)empty.textContent='Sin destino · queda en origen';[...sel.options].filter(o=>String(o.value).startsWith('pallet:')).forEach(o=>o.remove());[...sel.querySelectorAll('optgroup[label="Palet / Enviado"]')].forEach(g=>g.remove());[...sel.options].forEach(o=>{const text=(o.textContent||'').toLocaleLowerCase('es');if(!text.includes('secadero'))return;if(!isPaintRow(sel)){o.remove();return}if(!text.includes('directo'))o.textContent=o.textContent+' · movimiento directo'});if(isQualityRow(sel)&&openPallets.length){const group=document.createElement('optgroup');group.label='Palet / Enviado';openPallets.forEach(p=>{const o=document.createElement('option');o.value='pallet:'+p.id;o.textContent=p.code+' · '+p.units+' ud.';group.appendChild(o)});sel.appendChild(group)}})}

  // Un único controlador para Fin. Evita el manejador antiguo de la plantilla y
  // trata de forma uniforme destino normal, sin destino y Palet.
  document.addEventListener('click',async function(e){
    const btn=e.target.closest('.finish-btn');if(!btn)return;
    const sel=document.querySelector('.dest-select[data-id="'+btn.dataset.id+'"]');if(!sel)return;
    e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();btn.disabled=true;
    try{
      if(String(sel.value).startsWith('pallet:')){
        const palletId=String(sel.value).split(':')[1];if(!palletId)throw new Error('Palet no válido.');await syncDeclaredZone();
        const body=new URLSearchParams({pallet_id:palletId});const r=await fetch('/pedidos/palets/intervencion/'+btn.dataset.id+'/anadir/',{method:'POST',headers:{'X-CSRFToken':csrf,'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'},body:body.toString()});let d={};try{d=await r.json()}catch(_e){}if(!r.ok)throw new Error(d.error||'No se pudo enviar la unidad al palet.');location.reload();return;
      }
      const body=new URLSearchParams({destination_zone:sel.value||''});
      const r=await fetch('/produccion/intervencion/'+btn.dataset.id+'/terminar/',{method:'POST',headers:{'X-CSRFToken':csrf,'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'},body:body.toString()});
      let d={};try{d=await r.json()}catch(_e){throw new Error('El servidor no devolvió una respuesta válida al finalizar.')}if(!r.ok||d.ok===false)throw new Error(d.error||'No se pudo terminar la unidad.');location.reload();
    }catch(err){btn.disabled=false;alert(err.message||'No se pudo terminar la unidad.')}
  },true);
  const queue=document.getElementById('queueBody');new MutationObserver(function(){decorateDestinations()}).observe(queue,{childList:true,subtree:true});refreshAux();decorateDestinations();setInterval(refreshAux,30000);
})();
