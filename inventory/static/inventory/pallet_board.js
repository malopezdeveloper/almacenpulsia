(function(){
  function onBoard(){return !!document.getElementById('queueBody')&&!!document.getElementById('unitForm')}
  if(!onBoard())return;

  const csrfEl=document.querySelector('#unitForm input[name=csrfmiddlewaretoken]');
  const csrf=csrfEl?csrfEl.value:'';
  let openPallets=[];

  function ensureCounterBar(){
    let bar=document.getElementById('boardCounters');
    if(bar)return bar;
    bar=document.createElement('div');
    bar.id='boardCounters';
    bar.style.cssText='display:flex;gap:6px;flex-wrap:wrap;align-items:center;min-height:24px;padding:2px 1px;font-size:11px;font-weight:800';
    const form=document.getElementById('unitForm');
    form.parentNode.insertBefore(bar,form);
    return bar;
  }

  function drawCounters(counters){
    const bar=ensureCounterBar();
    const list=(counters||[]).filter(x=>Number(x.count)>0);
    if(!list.length){bar.innerHTML='<span style="color:#748199">Terminadas hoy: 0</span>';return}
    bar.innerHTML=list.map(x=>'<span style="display:inline-block;padding:3px 7px;border:1px solid #dfe5ed;border-radius:999px;background:#fff">'+escapeHtml(x.label)+': '+Number(x.count)+' ud.</span>').join('');
  }

  function escapeHtml(v){const d=document.createElement('div');d.textContent=v==null?'':String(v);return d.innerHTML}

  async function refreshAux(){
    try{
      const [queueResp,palletResp]=await Promise.all([
        fetch('/produccion/pizarra/abiertas/',{headers:{'X-Requested-With':'XMLHttpRequest'}}),
        fetch('/pedidos/palets/abiertos/',{headers:{'X-Requested-With':'XMLHttpRequest'}})
      ]);
      if(queueResp.ok){const q=await queueResp.json();drawCounters(q.counters||[])}
      if(palletResp.ok){const p=await palletResp.json();openPallets=p.results||[];decorateDestinations()}
    }catch(e){console.warn('PULSIA: no se pudieron actualizar contadores/palets',e)}
  }

  function isQualityRow(select){
    const tr=select.closest('tr');
    if(!tr)return false;
    const cells=tr.querySelectorAll('td');
    const zoneText=(cells[6]?cells[6].textContent:'').trim().toLocaleLowerCase('es');
    return zoneText.includes('calidad');
  }

  function decorateDestinations(){
    document.querySelectorAll('.dest-select').forEach(sel=>{
      [...sel.options].filter(o=>String(o.value).startsWith('pallet:')).forEach(o=>o.remove());
      if(!isQualityRow(sel))return;
      if(openPallets.length){
        const group=document.createElement('optgroup');group.label='Palet / Enviado';
        openPallets.forEach(p=>{const o=document.createElement('option');o.value='pallet:'+p.id;o.textContent=p.code+' · '+p.units+' ud.';group.appendChild(o)});
        sel.appendChild(group);
      }
    });
  }

  document.addEventListener('click',async function(e){
    const btn=e.target.closest('.finish-btn');
    if(!btn)return;
    const sel=document.querySelector('.dest-select[data-id="'+btn.dataset.id+'"]');
    if(!sel||!String(sel.value).startsWith('pallet:'))return;
    e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();
    const palletId=String(sel.value).split(':')[1];
    if(!palletId)return;
    btn.disabled=true;
    try{
      const body=new URLSearchParams({pallet_id:palletId});
      const r=await fetch('/pedidos/palets/intervencion/'+btn.dataset.id+'/anadir/',{method:'POST',headers:{'X-CSRFToken':csrf,'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'},body:body.toString()});
      let d={};try{d=await r.json()}catch(_e){}
      if(!r.ok)throw new Error(d.error||'No se pudo enviar la unidad al palet.');
      location.reload();
    }catch(err){btn.disabled=false;alert(err.message||'No se pudo enviar la unidad al palet.')}
  },true);

  const queue=document.getElementById('queueBody');
  new MutationObserver(function(){decorateDestinations()}).observe(queue,{childList:true,subtree:true});
  refreshAux();
  setInterval(refreshAux,30000);
})();
