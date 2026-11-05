/* Runs inside the original graph closure. Existing data, IDs, SVG renderer and handlers remain. */
var AT = {edge:null,history:false,zoom:1,pan:{x:0,y:0}};
var originalEdgeSvg=edgeSvg, originalDraw=draw, originalInspector=renderInspector;
var historicalLayout=layout(buildGraph()).pos;
function atEdgeKey(e){return JSON.stringify([e.s||e.source,e.t||e.target]);}
function atOriginalEdges(){return D.graph.edges.map(function(e){return Object.assign({s:e.source,t:e.target},e);});}
function atMissing(){return atOriginalEdges().filter(function(e){return !G.edges().some(function(x){return atEdgeKey(x)===atEdgeKey(e);});});}
edgeSvg=function(e,a,b,opacity){
  var key=atEdgeKey(e), selected=AT.edge===key, history=!G.has_node(e.s)||!G.has_node(e.t)||!G.E.has(DiGraph.key(e.s,e.t));
  return '<g class="at-connection '+(selected?'at-selected':'')+(history?' at-removed':'')+'" data-connection="'+esc(key)+'" role="button" tabindex="0" aria-label="'+esc(label(e.s)+' to '+label(e.t)+(history?', removed in scenario':', unverified relationship'))+'">'+originalEdgeSvg(e,a,b,opacity)+'<path class="at-edge-hit" d="'+edgePath(a,b)+'"/>'+(history?'<text class="at-removal" x="'+((a.x+NW+b.x)/2)+'" y="'+((a.y+b.y)/2+NH/2-8)+'">REMOVED IN SCENARIO</text>':'')+'</g>';
};
draw=function(e){
  originalDraw(e);
  if(AT.history){var html='';atMissing().forEach(function(ed){var a=pos[ed.s]||historicalLayout[ed.s],b=pos[ed.t]||historicalLayout[ed.t];if(a&&b)html+=edgeSvg(ed,a,b,.65);});D.graph.nodes.filter(function(n){return !G.has_node(n.id);}).forEach(function(n){var p=historicalLayout[n.id];if(p)html+='<g class="at-history-node">'+nodeSvg(n,p,.45,true)+'</g>';});$('#gdraw').insertAdjacentHTML('afterbegin',html);}
  $('#gdraw').setAttribute('transform','translate('+AT.pan.x+' '+AT.pan.y+') scale('+AT.zoom+')');
  if(AT.edge){var edge=atOriginalEdges().find(function(x){return atEdgeKey(x)===AT.edge;});$$('#gdraw .at-connection').forEach(function(el){el.classList.toggle('at-dim',el.getAttribute('data-connection')!==AT.edge);});if(edge)$$('#gdraw [data-node]').forEach(function(el){el.classList.toggle('at-endpoint',el.dataset.node===edge.s||el.dataset.node===edge.t);});}
};
renderInspector=function(){
  if(!AT.edge){originalInspector();return;}
  var edge=atOriginalEdges().find(function(x){return atEdgeKey(x)===AT.edge;});if(!edge){originalInspector();return;}
  var removed=atMissing().some(function(x){return atEdgeKey(x)===AT.edge;});
  $('#insp').innerHTML='<div class="at-inspector"><span class="id">SELECTED CONNECTION / '+(removed?'REMOVED IN SCENARIO':'UNVERIFIED SNAPSHOT ASSOCIATION')+'</span><h3>'+esc(label(edge.s))+' → '+esc(label(edge.t))+'</h3><dl><dt>Source node</dt><dd>'+esc(edge.s)+'</dd><dt>Target node</dt><dd>'+esc(edge.t)+'</dd><dt>Operation</dt><dd>'+esc(edge.op||'Not supplied')+'</dd><dt>Source label</dt><dd>'+esc(edge.kind)+'</dd>'+(edge.first?'<dt>First observed event</dt><dd>'+esc(edge.first)+'</dd>':'')+(edge.last?'<dt>Last observed event</dt><dd>'+esc(edge.last)+'</dd>':'')+'</dl><p>'+(removed?'This connection was removed only from the browser scenario. No observed ending/deletion timestamp or reason was supplied. The endpoint entities have not been deleted.':'Observed/inferred flags and event windows do not establish verification or current validity. Original evidence IDs, valid_from/valid_to and deletion events are not supplied by this snapshot.')+'</p>'+(edge.why?'<p>Supplied inference: '+esc(edge.why)+'</p>':'')+'<button class="btn" id="at-clear-edge">Clear connection selection</button></div>';
  $('#at-clear-edge').onclick=function(){AT.edge=null;draw(1);renderInspector();};
};
var mapSection=$('#gsvg').closest('section');
$('.legend',mapSection).textContent='Dashed amber: unverified supplied association · Grey: removed only in scenario. Event windows are not validity intervals.';
var controls=document.createElement('div');controls.className='at-controls';controls.innerHTML='<div class="at-mode"><button class="btn" id="at-current" aria-pressed="true">Current scenario</button><button class="btn" id="at-history" aria-pressed="false">Historical scenario</button></div><div><button class="btn" id="at-minus" aria-label="Zoom original graph out">−</button><button class="btn" id="at-plus" aria-label="Zoom original graph in">+</button><button class="btn" id="at-fit">Fit graph</button><button class="btn" id="at-reset-view">Reset view</button><button class="btn" id="at-clear">Clear focus</button></div>';
mapSection.insertBefore(controls,$('.gwrap',mapSection));
var provenance=document.createElement('div');provenance.className='at-provenance';provenance.textContent='PRESERVED ORIGINAL HTML / SAME SVG RENDERER · Imported aggregate snapshot. All removal controls change a local scenario only. Use Identity Constellation for evidence-backed validity history.';$('#panel-graph').insertBefore(provenance,$('#panel-graph').firstChild);
$('#at-current').onclick=function(){AT.history=false;this.setAttribute('aria-pressed','true');$('#at-history').setAttribute('aria-pressed','false');draw(1);};
$('#at-history').onclick=function(){AT.history=true;this.setAttribute('aria-pressed','true');$('#at-current').setAttribute('aria-pressed','false');draw(1);};
$('#at-plus').onclick=function(){AT.zoom=Math.min(2.5,AT.zoom+.15);draw(1);};$('#at-minus').onclick=function(){AT.zoom=Math.max(.4,AT.zoom-.15);draw(1);};
function atResetView(){AT.zoom=1;AT.pan={x:0,y:0};draw(1);}$('#at-fit').onclick=atResetView;$('#at-reset-view').onclick=atResetView;
$('#at-clear').onclick=function(){AT.edge=null;S.inspect=null;draw(1);renderInspector();};
$('#gsvg').addEventListener('click',function(e){var connection=e.target.closest('[data-connection]');if(connection){AT.edge=AT.edge===connection.dataset.connection?null:connection.dataset.connection;S.inspect=null;draw(1);renderInspector();}else if(e.target.closest('[data-node]')){AT.edge=null;draw(1);renderInspector();}else{AT.edge=null;S.inspect=null;draw(1);renderInspector();}});
$('#gsvg').addEventListener('keydown',function(e){var edge=e.target.closest('[data-connection]');if(edge&&(e.key==='Enter'||e.key===' ')){e.preventDefault();AT.edge=edge.dataset.connection;draw(1);renderInspector();}});
document.addEventListener('keydown',function(e){if(e.key==='Escape'){AT.edge=null;S.inspect=null;draw(1);renderInspector();}});
var atDrag=null;$('#gsvg').addEventListener('pointerdown',function(e){if(e.target.closest('[data-node],[data-connection]'))return;atDrag={x:e.clientX,y:e.clientY,pan:Object.assign({},AT.pan)};this.setPointerCapture(e.pointerId);});$('#gsvg').addEventListener('pointermove',function(e){if(!atDrag)return;var scale=this.viewBox.baseVal.width/this.getBoundingClientRect().width;AT.pan={x:atDrag.pan.x+(e.clientX-atDrag.x)*scale,y:atDrag.pan.y+(e.clientY-atDrag.y)*scale};$('#gdraw').setAttribute('transform','translate('+AT.pan.x+' '+AT.pan.y+') scale('+AT.zoom+')');});$('#gsvg').addEventListener('pointerup',function(){atDrag=null;});$('#gsvg').addEventListener('pointercancel',function(){atDrag=null;});
var oldSync=syncSel;syncSel=function(){oldSync();$('#b-delete').textContent='Preview scenario removal ('+S.sel.size+')';};
var originalConfirm=confirmUI;confirmUI=function(){originalConfirm();var b=$('#b-ok');if(b)b.textContent='Apply to scenario';};
if(new URLSearchParams(location.search).get('embed')==='graph')document.documentElement.classList.add('at-graph-only');
