/* Engineering workflows, loaded before app.js. No actions run until invoked. */
'use strict';

async function dlgVariables() {
  await guard(async () => {
    const r=await rpc('parameters.list');
    const input=el('textarea',{id:'eng-vars',rows:9,spellcheck:'false',style:'width:100%;font-family:monospace'},
      r.rows.map(x=>x.name+' = '+x.expression).join('\n'));
    const body=el('div',{},field('One variable = expression per line',input),
      el('div',{class:'hint'},'Example: W = 22.86mm\nH = W/2\nUse explicit units. Dependent primitive dimensions rebuild together; fixed-coordinate ports must be checked.'));
    dialog({title:'Design Variables',body,ok:'Apply and rebuild',onOk:async()=>{
      const variables={};
      for(const line of input.value.split('\n')) {
        if(!line.trim())continue;
        const m=line.match(/^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.+?)\s*$/);
        if(!m)throw Error('Use name = expression: '+line);
        if(Object.prototype.hasOwnProperty.call(variables,m[1]))throw Error('Duplicate variable '+m[1]);
        variables[m[1]]=m[2];
      }
      await rpc('parameters.set',{variables,replace:true});await refreshGeometry(false);
    }});
  });
}

async function dlgPrimitive() {
  await guard(async()=>{
    const r=await rpc('modeler.primitiveInfo');const body=el('div');const inputs={};
    for(const [key,n] of Object.entries(r.fields)) {
      const value=r.definition.params[key];
      if(n>1 || key==='axis') {
        const items=(Array.isArray(value)?value:[0,0,1]).map((v,i)=>inp('eng-p-'+key+'-'+i,
          n>0&&typeof v==='number'?v+'m':v));
        inputs[key]=items;body.appendChild(field(key+' · '+(n===2?'U / V':'X / Y / Z'),el('div',{class:'row3'},...items)));
      } else if(key==='plane') {
        inputs[key]=sel('eng-p-plane',['xy','yz','xz'],value);body.appendChild(field(key,inputs[key]));
      } else {
        inputs[key]=inp('eng-p-'+key,typeof value==='number'?value+'m':value);body.appendChild(field(key,inputs[key]));
      }
    }
    body.appendChild(el('div',{class:'hint'},'Use values such as 10mm or W/2. Existing move/rotate/scale history is preserved. This edits the primitive before transforms.'));
    dialog({title:'Dimensions / Expressions — '+r.name,body,ok:'Apply',onOk:async()=>{
      const params={};
      for(const [key,input] of Object.entries(inputs))params[key]=Array.isArray(input)?input.map(x=>key==='axis'?Number(x.value):x.value):input.value;
      await rpc('modeler.editPrimitive',{name:r.name,params});await refreshGeometry(false);
    }});
  });
}

async function dlgControls() {
  await guard(async()=>{
    const r=await rpc('analysis.controls');const perf=await rpc('analysis.performance');const body=el('div');
    body.appendChild(field('Maximum element size (empty = automatic)',inp('eng-h',r.mesh.max_element_size?fmtLen(r.mesh.max_element_size,U()):'')));
    body.appendChild(field('Linear solver',sel('eng-solver',['auto','direct','iterative'],r.solver.linear_solver)));
    body.appendChild(field('Relative linear-solver tolerance',inp('eng-tol',r.solver.tol)));
    body.appendChild(field('Consecutive converged adaptive passes',inp('eng-conv',r.adaptive.min_converged_passes,'number',{min:1,max:20})));
    body.appendChild(field(`Solver threads (0 = automatic: ${perf.auto} of ${perf.cpus} cores)`,inp('eng-threads',perf.threads,'number',{min:0,max:256})));
    body.appendChild(el('div',{class:'check'},el('input',{id:'eng-isolate',type:'checkbox',...(perf.isolate?{checked:'checked'}:{})}),el('label',{for:'eng-isolate'},'Run the solver in a separate low-priority process (keeps the PC responsive; can be aborted)')));
    body.appendChild(el('div',{class:'hint'},'These controls are saved with the Design. A smaller mesh increases runtime and memory. Set maximum passes high enough for the required consecutive convergence.'));
    dialog({title:'Solver and Mesh Controls',body,ok:'Apply',onOk:async()=>{
      await rpc('analysis.setPerformance',{threads:gn('eng-threads')||0,isolate:$('#eng-isolate').checked});
      return rpc('analysis.setControls',{
        meshSize:gv('eng-h'),solver:gv('eng-solver'),tolerance:gn('eng-tol'),convergedPasses:gn('eng-conv')});}});
  });
}

async function dlgDiagnostics() {
  await guard(async()=>{
    const r=await rpc('analysis.diagnostics');const body=el('div');
    body.appendChild(el('div',{class:'eng-banner '+(r.ok?'ok':'error')},r.ok?'Model checks passed — review warnings before solving':'Resolve the following model errors'));
    for(const x of r.errors)body.appendChild(el('p',{class:'eng-error'},'✕ '+x));
    for(const x of r.warnings)body.appendChild(el('p',{class:'eng-warning'},'△ '+x));
    if(r.estimate)body.appendChild(el('p',{},'Target element size: '+fmtLen(r.estimate.targetSize,U())+'; bounding-grid estimate: '+r.estimate.uniformGridTets.toLocaleString()+' tetrahedra. '+r.estimate.note));
    body.appendChild(el('div',{class:'hint'},'Implemented: Driven Modal FEM and Eigenmode, first/second-order basis, adaptive refinement, discrete / interpolating / fast sweeps, far fields and optimization. PML, periodic/Floquet and terminal solutions are not implemented. Diagnostics do not certify physical accuracy.'));
    dialog({title:'Engineering Diagnostics',body,ok:null,cancel:'Close',width:'wide'});
  });
}

function exportCsvFile(filename,rows) {
  const csv=rows.map(r=>r.map(x=>'"'+String(x??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'}));
  el('a',{href:url,download:filename}).click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

async function dlgStudy() {
  await guard(async()=>{
    const r=await rpc('parameters.list');if(!r.rows.length)throw Error('Define a variable, then use it in a primitive dimension first.');
    const body=el('div');
    body.appendChild(field('Design variable',sel('eng-variable',r.rows.map(x=>x.name),r.rows[0].name)));
    body.appendChild(field('One value per line (maximum 50 cases)',el('textarea',{id:'eng-values',rows:5,style:'width:100%'},String(r.rows[0].expression))));
    body.appendChild(field('Solution setup',sel('eng-setup',(STATE.design?.setups||[]).map(x=>x.name),(STATE.design?.setups||[])[0]?.name)));
    body.appendChild(field('Mesh backend',sel('eng-backend',[['auto','Auto'],['occ','OCC (CAD conformal)'],['builtin','Builtin (approximate curved geometry)']],'auto')));
    body.appendChild(el('div',{class:'check'},el('input',{id:'eng-adaptive',type:'checkbox'}),el('label',{for:'eng-adaptive'},'Adaptive mesh for every case')));
    body.appendChild(el('div',{class:'hint'},'Each case performs a real FEM solve on a copy of the Design. The original model is preserved. Fixed-coordinate port/boundary assignments do not follow changed dimensions automatically.'));
    dialog({title:'Parameter Study',body,ok:'Run study',onOk:async()=>{
      await rpc('analysis.study',{variable:gv('eng-variable'),values:gv('eng-values').split('\n').map(x=>x.trim()).filter(Boolean),setup:gv('eng-setup'),backend:gv('eng-backend'),adaptive:$('#eng-adaptive').checked});
      setTimeout(dlgStudyResults,0);
    }});
  });
}

async function dlgStudyResults() {
  const body=el('div');const status=el('p');const plot=el('canvas',{width:720,height:240,style:'width:100%;height:240px;background:#fff;border:1px solid #ccd3df'});
  const table=el('table',{class:'eng-table'});const data={rows:[]};
  body.appendChild(status);body.appendChild(plot);body.appendChild(table);
  body.appendChild(el('div',{class:'dim-actions'},el('button',{onclick:()=>guard(()=>rpc('analysis.cancel'))},'Request cancel'),
    el('button',{onclick:()=>exportCsvFile('aether-study-curves.csv',[['Case','Variable','Value','Frequency Hz','S11 dB'],...data.rows.flatMap(r=>r.freq.map((f,k)=>[r.index,r.variable,r.value,f,r.s11Db[k]]))])},'Export curves CSV'),
    el('button',{onclick:()=>exportCsvFile('aether-parameter-study.csv',[['Case','Variable','Value','Minimum S11 dB','Frequency Hz','Runtime s'],...data.rows.map(r=>[r.index,r.variable,r.value,r.metrics.minimumDb,r.metrics.minimumFrequency,r.runtime])])},'Export summary CSV')));
  const dlg=dialog({title:'Parameter Study Results',body,width:'wide',ok:null,cancel:'Close'});
  let busy=false;
  const refresh=async()=>{
    if(!dlg.node.isConnected){clearInterval(timer);return;}
    if(busy)return;busy=true;
    try {
      const r=await rpc('analysis.studyResults');data.rows=r.rows;
      status.textContent=(r.job.stage||'No study yet')+' · '+r.rows.length+' completed'+(r.job.error?' · '+r.job.error:'');
      table.replaceChildren(el('thead',{},el('tr',{},...['Case','Value','Min S11','At frequency','Runtime'].map(x=>el('th',{},x)))),
        el('tbody',{},...r.rows.map((x,i)=>el('tr',{},el('td',{style:'color:'+studyColor(i)},'● '+x.index),el('td',{},x.value),el('td',{},x.metrics.minimumDb.toFixed(3)+' dB'),el('td',{},fmtHz(x.metrics.minimumFrequency)),el('td',{},x.runtime.toFixed(2)+' s')))));
      drawStudyPlot(plot,r.rows);
      if(!r.job.running)clearInterval(timer);
    } catch(e){status.textContent=e.message;clearInterval(timer);}finally{busy=false;}
  };
  const timer=setInterval(refresh,1500);await refresh();
}

function studyColor(i) { return 'hsl('+((i*137.508)%360).toFixed(2)+' 65% 38%)'; }
function drawStudyPlot(canvas,rows) {
  const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#24314b';ctx.font='12px sans-serif';
  ctx.fillText('S11 (dB) — solved samples',45,18);if(!rows.length){ctx.fillText('Waiting for the first completed case…',45,55);return;}
  let lo=Infinity,hi=-Infinity,vmin=0,vmax=0;
  for(const row of rows){for(const f of row.freq){lo=Math.min(lo,f);hi=Math.max(hi,f);}for(const v of row.s11Db){if(Number.isFinite(v)){vmin=Math.min(vmin,v);vmax=Math.max(vmax,v);}}}
  const bottom=Math.max(-120,Math.min(-10,Math.floor(vmin/10)*10)),top=Math.max(0,Math.ceil(vmax/10)*10);
  const x=f=>50+(f-lo)/(hi-lo||1)*620,y=v=>35+(top-Math.max(bottom,v))/(top-bottom)*165;
  ctx.strokeStyle='#d7dce5';ctx.beginPath();for(let v=bottom;v<=top;v+=10){ctx.moveTo(50,y(v));ctx.lineTo(670,y(v));ctx.fillText(String(v),8,y(v)+4);}ctx.stroke();
  ctx.fillText(fmtHz(lo),50,220);ctx.fillText(fmtHz(hi),585,220);
  rows.forEach((r,i)=>{ctx.strokeStyle=studyColor(i);ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();r.freq.forEach((f,k)=>k?ctx.lineTo(x(f),y(r.s11Db[k])):ctx.moveTo(x(f),y(r.s11Db[k])));ctx.stroke();if(r.freq.length===1){ctx.beginPath();ctx.arc(x(r.freq[0]),y(r.s11Db[0]),3,0,2*Math.PI);ctx.fill();}});
}

async function dlgMetrics() {
  await guard(async()=>{
    const body=el('div');const results=el('div');
    body.appendChild(field('Port (1-based)',inp('eng-port',1,'number',{min:1})));
    body.appendChild(field('Threshold (dB)',inp('eng-threshold',-10)));
    body.appendChild(field('Marker frequency (optional, e.g. 2.4GHz)',inp('eng-marker','')));
    const calc=el('button',{class:'pri',onclick:async()=>{
      await guard(async()=>{
        const r=await rpc('results.metrics',{port:gn('eng-port'),threshold:gn('eng-threshold'),freq:gv('eng-marker')||null});
        results.replaceChildren(el('p',{},'Minimum sampled S'+gv('eng-port')+gv('eng-port')+': '+r.minimumDb.toFixed(4)+' dB at '+fmtHz(r.minimumFrequency)),
          el('p',{},'Marker: '+fmtHz(r.marker.frequency)+' / '+r.marker.db.toFixed(4)+' dB'),
          el('p',{},'Passive: '+r.passive+' · Reciprocal: '+r.reciprocal),
          ...r.bands.map(b=>el('p',{},fmtHz(b.start)+' → '+fmtHz(b.stop)+'; bandwidth '+fmtHz(b.bandwidth)+(b.clipped?' (sweep-edge limited)':''))),el('div',{class:'hint'},r.note));
      });
    }},'Calculate metrics');body.appendChild(calc);body.appendChild(results);
    dialog({title:'S-Parameter Metrics and Marker',body,ok:null,cancel:'Close'});calc.click();
  });
}

function dlgCadExport() {
  const body=el('div');body.appendChild(field('Format',sel('eng-cad-format',[['stl','STL surface mesh'],['step','STEP BREP (OCC required)']],'stl')));
  body.appendChild(field('STL coordinate units',sel('eng-cad-unit',['mm','m','cm','um','in','mil'],U())));
  body.appendChild(el('div',{class:'check'},el('input',{id:'eng-cad-selection',type:'checkbox',checked:'checked'}),el('label',{for:'eng-cad-selection'},'Export selected objects only')));
  body.appendChild(el('div',{class:'hint'},'STEP export verifies bounds after reimport before replacing the target. STL stores surface triangles and does not standardize units. Geometry export does not include EM assignments.'));
  const dlg=dialog({title:'Export CAD Geometry',body,ok:'Choose file…',onOk:()=>{
    const format=gv('eng-cad-format'),units=gv('eng-cad-unit'),names=$('#eng-cad-selection').checked?STATE.selection:null;
    if(names&&!names.length)throw Error('Select objects or turn off selected-only export.');
    filePicker({mode:'save',kind:format==='step'?'cadstep':'cadstl',title:'Export '+format.toUpperCase(),filename:STATE.project.name+'.'+format,
      onPick:async path=>{const r=await rpc('modeler.exportCad',{path,names,units});setStatus(r.note,'');dlg.close();}});
    return false;
  }});
}

function dlgAirRegion() {
  const body=el('div',{},field('Name',inp('eng-air-name','AirRegion')),field('Padding on each side',inp('eng-air-gap','20mm')),
    el('div',{class:'hint'},'Creates surrounding air with six first-order radiation planes. Choose padding based on wavelength and verify by increasing it. Recheck the region after changing geometry; this is not PML.'));
  dialog({title:'Surrounding Air Region',body,ok:'Create region',onOk:async()=>{
    await rpc('modeler.airRegion',{name:gv('eng-air-name'),padding:gv('eng-air-gap')});await refreshGeometry(true);
  }});
}


/* ----------------------------------------------------------- optimization */
const GOAL_LABELS = [
  ['s_max', 'max dB(S) in band ≤ target'],
  ['s_min', 'min dB(S) in band ≥ target'],
  ['s_at', 'dB(S) at frequency = target'],
  ['resonance', 'S11 notch frequency = target'],
  ['eigenfreq', 'Eigenmode frequency = target'],
  ['peak_gain', 'Peak gain ≥ target (dBi)']];

async function dlgOptimize() {
  await guard(async () => {
    const r = await rpc('parameters.list');
    const vars = r.rows.filter(x => !x.error);
    if (!vars.length) throw Error('Define a design variable, then bind it to a primitive dimension first.');
    const eigen = STATE.design?.solutionType === 'eigenmode';
    const body = el('div');
    const vt = el('table', { class: 'eng-table' });
    vt.appendChild(el('thead', {}, el('tr', {}, ...['Use', 'Variable', 'Current', 'Minimum', 'Maximum']
      .map(h => el('th', {}, h)))));
    const vb = el('tbody');
    vars.forEach((v, i) => {
      const dim = v.dimension && v.dimension[0] === 1 ? 'm' : '';
      const cb = el('input', { type: 'checkbox', id: 'op-use-' + i });
      if (i === 0) cb.checked = true;
      const lo = inp('op-lo-' + i, v.si ? (v.si * 0.5) + dim : '');
      const hi = inp('op-hi-' + i, v.si ? (v.si * 1.5) + dim : '');
      vb.appendChild(el('tr', {}, el('td', {}, cb), el('td', {}, v.name),
        el('td', {}, v.expression), el('td', {}, lo), el('td', {}, hi)));
    });
    vt.appendChild(vb);
    body.appendChild(el('div', { class: 'hint', style: 'margin-top:0' }, 'Variables to tune and their allowed range'));
    body.appendChild(vt);

    const goals = el('div', { id: 'op-goals' });
    const addGoal = (kind) => {
      const row = el('div', { class: 'row3', style: 'align-items:center;margin:4px 0' });
      const k = sel('', eigen ? GOAL_LABELS.filter(g => g[0] === 'eigenfreq')
        : GOAL_LABELS.filter(g => g[0] !== 'eigenfreq'), kind ||
        (eigen ? 'eigenfreq' : 's_max'));
      const t = inp('', eigen ? '10GHz' : '-10');
      const f1 = inp('', ''); f1.placeholder = 'f start / freq';
      const f2 = inp('', ''); f2.placeholder = 'f stop';
      const w = inp('', '1', 'number', { step: 'any', min: 0 });
      const rm = el('button', { onclick: () => row.remove() }, '✕');
      row.append(k, t, f1, f2, w, rm);
      row._get = () => ({ kind: k.value, target: t.value, fStart: f1.value,
        fStop: f2.value, weight: w.value, port: 1, port2: 1, mode: 1 });
      goals.appendChild(row);
    };
    addGoal();
    body.appendChild(el('div', { class: 'hint' }, 'Goals — type · target (dB / Hz / dBi) · band start · band stop · weight'));
    body.appendChild(goals);
    body.appendChild(el('button', { onclick: () => addGoal() }, '+ Add goal'));
    body.appendChild(field('Optimizer', sel('op-method', [
      ['nelder-mead', 'Nelder–Mead (local, few solves)'],
      ['pattern', 'Pattern search (local, robust)'],
      ['quasi-newton', 'Quasi-Newton L-BFGS-B (smooth responses)'],
      ['differential-evolution', 'Genetic / differential evolution (global)']], 'nelder-mead')));
    body.appendChild(field('Maximum solves', inp('op-max', '30', 'number', { min: 2, max: 1000 })));
    body.appendChild(field('Solution setup', sel('op-setup', (STATE.design?.setups || []).map(x => x.name),
      (STATE.design?.setups || [])[0]?.name)));
    body.appendChild(el('div', { class: 'check' }, el('input', { id: 'op-adaptive', type: 'checkbox' }),
      el('label', { for: 'op-adaptive' }, 'Adaptive mesh for every solve')));
    body.appendChild(el('div', { class: 'hint' },
      'Each trial is a real FEM solve on a copy of the design; yours is untouched until you press Apply best. ' +
      'Goals that are already met cost nothing, and the search stops once all are met. ' +
      'A local optimizer needs a starting point near the answer — use the global one for narrow notches.'));
    dialog({ title: 'Optimization', body, width: 'wide', ok: 'Start', onOk: async () => {
      const variables = {};
      vars.forEach((v, i) => { if ($('#op-use-' + i).checked) variables[v.name] = [gv('op-lo-' + i), gv('op-hi-' + i)]; });
      await rpc('analysis.optimize', { variables, goals: [...goals.children].map(g => g._get()),
        method: gv('op-method'), maxEvals: gn('op-max'), setup: gv('op-setup'),
        adaptive: $('#op-adaptive').checked });
      setTimeout(dlgOptimizeResults, 0);
    } });
  });
}

async function dlgOptimizeResults() {
  const body = el('div'), status = el('p');
  const plot = el('canvas', { width: 720, height: 220, style: 'width:100%;height:220px;background:#fff;border:1px solid #ccd3df' });
  const table = el('table', { class: 'eng-table' });
  const apply = el('button', { class: 'pri', disabled: 'disabled', onclick: () => guard(async () => {
    const r = await rpc('analysis.optimizeApply');
    await refreshGeometry(false);
    setStatus('Applied: ' + Object.entries(r.variables).map(([k, v]) => k + ' = ' + v).join(', '), '');
  }) }, 'Apply best values');
  body.append(status, plot, table, el('div', { class: 'dim-actions' },
    el('button', { onclick: () => guard(() => rpc('analysis.cancel')) }, 'Request cancel'), apply));
  const dlg = dialog({ title: 'Optimization Results', body, width: 'wide', ok: null, cancel: 'Close' });
  let busy = false, timer = null;
  const refresh = async () => {
    if (!dlg.node.isConnected) { clearInterval(timer); return; }
    if (busy) return; busy = true;
    try {
      const r = await rpc('analysis.optimizeResults');
      const rows = r.rows || [];
      const best = r.best;
      status.textContent = (r.spec ? r.spec.method + ' · ' : '') + (r.status || 'no optimization yet') +
        ' · ' + rows.length + ' solve(s)' + (best ? ' · best cost ' + best.cost.toPrecision(4) : '') +
        (r.error ? ' · ' + r.error : '');
      const names = r.spec ? Object.keys(r.spec.variables) : [];
      table.replaceChildren(
        el('thead', {}, el('tr', {}, ...['#', ...names, 'Cost', ...(r.spec ? r.spec.goals : [])]
          .map(h => el('th', {}, h)))),
        el('tbody', {}, ...rows.map(x => el('tr', { style: best && x.eval === best.eval ? 'font-weight:600' : '' },
          el('td', {}, x.eval),
          ...names.map(n => el('td', {}, (x.values[n] * 1e3).toPrecision(5) + ' mm')),
          el('td', {}, x.cost.toPrecision(4)),
          ...x.goals.map(g => el('td', {}, g.value.toPrecision(5)))))));
      drawCostPlot(plot, rows);
      apply.disabled = !(r.expressions && r.status !== 'running');
      if (!r.job.running) clearInterval(timer);
    } catch (e) { status.textContent = e.message; clearInterval(timer); } finally { busy = false; }
  };
  timer = setInterval(refresh, 1200); await refresh();
}

function drawCostPlot(canvas, rows) {
  const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#24314b'; ctx.font = '12px sans-serif';
  ctx.fillText('Cost per solve (lower is better; 0 = every goal met)', 45, 16);
  if (!rows.length) { ctx.fillText('Waiting for the first solve…', 45, 55); return; }
  const cs = rows.map(r => r.cost), top = Math.max(...cs) || 1;
  const x = i => 50 + i / Math.max(rows.length - 1, 1) * 620, y = v => 190 - v / top * 150;
  ctx.strokeStyle = '#d7dce5'; ctx.beginPath(); ctx.moveTo(50, 190); ctx.lineTo(670, 190); ctx.moveTo(50, 40); ctx.lineTo(50, 190); ctx.stroke();
  ctx.fillText(top.toPrecision(3), 4, 44); ctx.fillText('0', 36, 194);
  ctx.strokeStyle = '#999'; ctx.beginPath(); cs.forEach((c, i) => i ? ctx.lineTo(x(i), y(c)) : ctx.moveTo(x(i), y(c))); ctx.stroke();
  let bestSoFar = Infinity; ctx.strokeStyle = '#2b6cb0'; ctx.lineWidth = 2; ctx.beginPath();
  cs.forEach((c, i) => { bestSoFar = Math.min(bestSoFar, c); i ? ctx.lineTo(x(i), y(bestSoFar)) : ctx.moveTo(x(i), y(bestSoFar)); });
  ctx.stroke(); ctx.lineWidth = 1;
}
