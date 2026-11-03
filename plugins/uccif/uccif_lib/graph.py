"""Self-contained HTML view of the code graph (`uccif index graph`).

One file, no network, no libraries: the graph data is embedded as JSON and drawn on a
canvas with a small force layout. Nodes are source files, edges are resolved imports and
calls (the same edges `--impact` and `--path` walk). The file is written next to the index
(outside the repo); if that is read-only (Claude Code's Bash sandbox), to the git-ignored
.claude/uccif/.local/ instead. Nothing is ever written to tracked files.
"""

import json
from pathlib import Path, PurePosixPath

from uccif_lib import index
from uccif_lib.paths import ensure_local

DEFAULT_MAX_NODES = 300
HARD_MAX_NODES = 2000
_ROOT_DIRS = ("src", "app", "lib", "packages")


def group_of(path):
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        return "(root)"
    if parts[0] in _ROOT_DIRS and len(parts) > 2:
        return parts[1]
    return parts[0]


# Edge families drawn by the view (bit flags on each drawn link; 512 = only inferred edges).
FAMILIES = ((1, "imports", ("imports",)),
            (2, "calls", ("calls", "passes_callback", "uses_composable")),
            (4, "components", ("renders", "passes_prop", "listens")),
            (8, "stores", ("calls_action", "reads_state", "uses_store")),
            (16, "routes", ("routes_to", "navigates_to")),
            (32, "css", ("uses_css_var", "defines_css_var", "uses_class")),
            (64, "types", ("references_type",)),
            (128, "variables", ("reads", "writes")),
            (256, "inheritance", ("extends", "implements")))
BIT = {k: b for b, _, kinds in FAMILIES for k in kinds}
INFERRED = 512


def _flags(rows, keep):
    """{(a, b): flags} from (src, dst, kind, confidence) rows whose endpoints pass keep()."""
    flags, certain = {}, set()
    for a, b, kind, conf in rows:
        if a == b or not keep(a) or not keep(b) or kind not in BIT:
            continue
        flags[(a, b)] = flags.get((a, b), 0) | BIT[kind]
        if conf == "extracted":
            certain.add((a, b))
    for pair in flags:
        if pair not in certain:
            flags[pair] |= INFERRED
    return flags


def graph_data(project, max_nodes=DEFAULT_MAX_NODES, mode="files", file=None):
    """{'nodes': [...], 'edges': [[a, b, flags]], 'families': [[bit, name, count]], 'mode', ...}.
    An edge a -> b means a uses b. mode: 'files' (default), 'components' (.vue render tree), or
    'symbols' for one `file`: its functions / components and what they touch, one hop out."""
    max_nodes = max(10, min(int(max_nodes), HARD_MAX_NODES))
    con = index.connect(project, write=False)
    files = {p: (lang, t, n) for p, lang, t, n in
             con.execute("SELECT path, lang, is_test, n_symbols FROM files")}
    meta = {}
    if mode == "symbols":
        rel = index._norm(project, file or "")
        if rel not in files:
            con.close()
            raise index.IndexUnavailable("%s is not in the index" % rel)
        rows = con.execute("SELECT src_id, dst_id, kind, confidence FROM edges WHERE dst_id IS NOT NULL AND "
                           "(src_path=? OR dst_path=?)", (rel, rel)).fetchall()
        flags = _flags(rows, lambda nid: nid not in files or nid == rel)  # file nodes only for top-level code
        ids = {x for pair in flags for x in pair}
        for (nid,) in con.execute("SELECT id FROM nodes WHERE path=? AND kind<>'file'", (rel,)):
            ids.add(nid)
        for nid in ids:
            r = con.execute("SELECT name, path, kind, line FROM nodes WHERE id=?", (nid,)).fetchone()
            meta[nid] = r or (nid.split("#")[-1], nid.split("#")[0], "?", 0)
        focus = rel
    else:
        rows = con.execute("SELECT src_path, dst_path, kind, confidence FROM edges WHERE dst_path IS NOT NULL").fetchall()
        if mode == "components":
            rows = [r for r in rows if r[2] == "renders"]
            keep = lambda p: p in files and files[p][0] in ("vue", "svelte")  # noqa: E731
        else:
            keep = lambda p: p in files  # noqa: E731
        flags = _flags(rows, keep)
        focus = None
    con.close()
    degree = {}
    for a, b in flags:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    pool = set(degree) | (set(meta) if mode == "symbols" else set())
    connected = sorted(pool, key=lambda p: (-degree.get(p, 0), p))[:max_nodes]
    keep_ids = {p: i for i, p in enumerate(connected)}
    nodes = []
    for p in connected:
        if mode == "symbols":
            name, path, kind, line = meta[p]
            nodes.append({"id": p, "label": name, "g": path, "lang": kind, "test": index.is_test(path), "sym": 0,
                          "deg": degree.get(p, 0), "q": name, "at": "%s:%s" % (path, line)})
        else:
            nodes.append({"id": p, "g": group_of(p), "lang": files[p][0], "test": bool(files[p][1]),
                          "sym": files[p][2], "deg": degree[p], "q": p})
    edges = [[keep_ids[a], keep_ids[b], f] for (a, b), f in sorted(flags.items()) if a in keep_ids and b in keep_ids]
    fams = [[b, name, sum(1 for e in edges if e[2] & b)] for b, name, _ in FAMILIES]
    total = len(meta) if mode == "symbols" else len([p for p in files if mode != "components" or
                                                     files[p][0] in ("vue", "svelte")])
    return {"nodes": nodes, "edges": edges, "total_files": total, "shown": len(nodes),
            "isolated": max(0, total - len(degree)) if mode != "symbols" else 0,
            "families": [f for f in fams if f[2]], "mode": mode, "focus": focus}


def render(data, title):
    # "<" escaped so a file name can never close the script tag
    blob = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    return (_HTML.replace("__DATA__", blob)
                 .replace("__TITLE__", title.replace("&", "&amp;").replace("<", "&lt;")))


def write(project, out=None, max_nodes=DEFAULT_MAX_NODES, mode="files", file=None):
    """Build the graph and write the HTML. Returns (path, data)."""
    data = graph_data(project, max_nodes, mode, file)
    what = {"components": "component tree", "symbols": "functions of %s" % data.get("focus")}.get(mode, "code graph")
    html = render(data, "%s %s" % (project.root.name, what))
    if out:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        return target, data
    for folder in (lambda: project.data_dir / "index", lambda: ensure_local(project)):
        try:
            d = folder()
            d.mkdir(parents=True, exist_ok=True)
            target = d / "graph.html"
            target.write_text(html, encoding="utf-8")
            return target, data
        except OSError:
            continue  # read-only (sandbox): try the git-ignored per-checkout folder
    raise OSError("no writable place for graph.html; pass --out FILE")


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--panel:#ffffff;--ink:#1d1d1b;--mute:#6b6b66;--line:#d9d9d3;--edge:#9a9a93;--hi:#d9480f;--sel:#1971c2}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#17171a;--panel:#212126;--ink:#ececea;--mute:#9a9aa3;--line:#33333a;--edge:#6a6a74;--hi:#ff8a4c;--sel:#74c0fc}}
:root[data-theme="dark"]{--bg:#17171a;--panel:#212126;--ink:#ececea;--mute:#9a9aa3;--line:#33333a;--edge:#6a6a74;--hi:#ff8a4c;--sel:#74c0fc}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,-apple-system,Segoe UI,sans-serif;display:flex;flex-direction:column;height:100vh}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
h1{font-size:15px;margin:0;font-weight:600}
.meta{color:var(--mute);font-size:12px}
input[type=search]{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);min-width:200px;flex:1;max-width:320px}
label{font-size:12px;color:var(--mute);display:flex;gap:4px;align-items:center}
main{flex:1;display:flex;min-height:0}
#stage{flex:1;position:relative;min-width:0}
canvas{width:100%;height:100%;display:block;cursor:grab}
aside{width:300px;border-left:1px solid var(--line);background:var(--panel);padding:12px 16px;overflow:auto;font-size:13px}
aside h2{font-size:13px;margin:12px 0 4px;color:var(--mute);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
aside h2:first-child{margin-top:0}
aside ul{list-style:none;margin:0;padding:0}
aside li{padding:2px 0}
a.n{color:var(--sel);cursor:pointer;word-break:break-all;text-decoration:none}
a.n:hover{text-decoration:underline}
.path{word-break:break-all;font-weight:600}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px}
.legend span{display:inline-flex;gap:5px;align-items:center;font-size:12px}
.legend i{width:10px;height:10px;border-radius:50%;display:inline-block}
.tag{color:var(--mute);font-size:12px}
@media (max-width:700px){main{flex-direction:column}aside{width:auto;max-height:40%;border-left:0;border-top:1px solid var(--line)}}
</style></head><body>
<header>
<h1>__TITLE__</h1>
<span class="meta" id="stats"></span>
<input type="search" id="q" placeholder="Find a file…" aria-label="Find a file">
<label><input type="checkbox" id="tests" checked> tests</label>
<label><input type="checkbox" id="inf" checked> inferred</label>
<span id="fams" class="legend"></span>
</header>
<main>
<div id="stage"><canvas id="c" aria-label="Code graph"></canvas></div>
<aside id="side"><h2>Legend</h2><div class="legend" id="legend"></div>
<h2>How to read</h2>
<p class="tag" id="how">Each dot is a source file; a line means one file uses the other (import, call, render, store, route, CSS, type…; tick the kinds above). Dashed lines are only inferred (matched by name or pattern). Bigger dot = more connections. Click a dot to see what it uses and what uses it. Drag to pan, scroll to zoom. The index is a lead: read the file before relying on an edge.</p>
<div id="info"></div></aside>
</main>
<script>
"use strict";
var D=__DATA__;
var cv=document.getElementById("c"),ctx=cv.getContext("2d");
var N=D.nodes,E=D.edges,sel=-1,hov=-1,query="",showTests=true,showInf=true,mask=1023;
var FAM=D.families||[[1,"imports",0],[2,"calls",0]];
function lab(n){return n.label||n.id.split("/").pop()}
function famNames(f){return FAM.filter(function(x){return f&x[0]}).map(function(x){return x[1]}).join("+")+(f&512?" ~inferred":"")}
var view={x:0,y:0,k:1},alpha=1,drag=null,dpr=window.devicePixelRatio||1;
var dark=function(){var r=document.documentElement.getAttribute("data-theme");return r?r==="dark":window.matchMedia("(prefers-color-scheme: dark)").matches};
var groups=[];N.forEach(function(n){if(groups.indexOf(n.g)<0)groups.push(n.g)});
function color(g){var h=(groups.indexOf(g)*137.5)%360;return "hsl("+h+","+(dark()?"65%,62%":"60%,42%")+")"}
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim()}
var out=N.map(function(){return[]}),inn=N.map(function(){return[]});
E.forEach(function(e){out[e[0]].push(e);inn[e[1]].push(e)});
N.forEach(function(n,i){var a=i*2.399963,r=14*Math.sqrt(i+1);n.x=r*Math.cos(a);n.y=r*Math.sin(a);n.vx=0;n.vy=0;n.r=3+Math.min(9,Math.sqrt(n.deg)*1.6)});
function vis(i){return showTests||!N[i].test}
function evis(e){return vis(e[0])&&vis(e[1])&&(e[2]&mask&511)&&(showInf||!(e[2]&512))}
function tick(){
 var n=N.length,i,j,a,b,dx,dy,d2,f,e;
 for(i=0;i<n;i++){a=N[i];for(j=i+1;j<n;j++){b=N[j];dx=a.x-b.x;dy=a.y-b.y;d2=dx*dx+dy*dy+.01;if(d2>90000)continue;f=900/d2*alpha;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f}}
 for(i=0;i<E.length;i++){e=E[i];a=N[e[0]];b=N[e[1]];dx=b.x-a.x;dy=b.y-a.y;var d=Math.sqrt(dx*dx+dy*dy)||1;f=(d-46)*.02*alpha;dx=dx/d*f;dy=dy/d*f;a.vx+=dx;a.vy+=dy;b.vx-=dx;b.vy-=dy}
 for(i=0;i<n;i++){a=N[i];a.vx-=a.x*.004*alpha;a.vy-=a.y*.004*alpha;if(drag&&drag.node===i){a.vx=a.vy=0;continue}a.vx*=.82;a.vy*=.82;a.x+=a.vx;a.y+=a.vy}
 alpha*=.992;if(alpha<.02)alpha=0;
}
function fit(){var minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9;N.forEach(function(n){minx=Math.min(minx,n.x);maxx=Math.max(maxx,n.x);miny=Math.min(miny,n.y);maxy=Math.max(maxy,n.y)});
 if(!N.length)return;var w=cv.width/dpr,h=cv.height/dpr,k=Math.min(w/(maxx-minx+80),h/(maxy-miny+80));view.k=Math.max(.15,Math.min(k,2.5));view.x=w/2-(minx+maxx)/2*view.k;view.y=h/2-(miny+maxy)/2*view.k}
function match(i){return query&&(N[i].id+" "+(N[i].label||"")).toLowerCase().indexOf(query)>=0}
function nbr(i){var s={};out[i].concat(inn[i]).forEach(function(e){s[e[0]]=1;s[e[1]]=1});return s}
function draw(){
 var w=cv.width/dpr,h=cv.height/dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
 ctx.translate(view.x,view.y);ctx.scale(view.k,view.k);
 var qa=query&&N.some(function(_,i){return match(i)});
 var focus=sel>=0?sel:hov,nb=focus>=0?nbr(focus):null,edge=css("--edge"),hi=css("--hi"),selc=css("--sel"),ink=css("--ink");
 E.forEach(function(e){if(!evis(e))return;var on=nb&&(e[0]===focus||e[1]===focus);
  if(nb&&!on){ctx.globalAlpha=.07}else ctx.globalAlpha=on?.95:.38;
  ctx.strokeStyle=on?(e[0]===focus?hi:selc):edge;ctx.lineWidth=(on?1.6:.8)/view.k+(e[2]&2?.2:0);
  var a=N[e[0]],b=N[e[1]];if(e[2]&512)ctx.setLineDash([3/view.k,3/view.k]);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();ctx.setLineDash([]);
  if(on){var ang=Math.atan2(b.y-a.y,b.x-a.x),px=b.x-Math.cos(ang)*b.r,py=b.y-Math.sin(ang)*b.r,s=5/view.k;
   ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(px-s*Math.cos(ang-.45),py-s*Math.sin(ang-.45));ctx.lineTo(px-s*Math.cos(ang+.45),py-s*Math.sin(ang+.45));ctx.closePath();ctx.fillStyle=ctx.strokeStyle;ctx.fill()}});
 N.forEach(function(n,i){if(!vis(i))return;var dim=(nb&&!nb[i])||(qa&&!match(i));ctx.globalAlpha=dim?.15:1;
  ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,6.2832);ctx.fillStyle=color(n.g);ctx.fill();
  if(n.test){ctx.lineWidth=1.4/view.k;ctx.strokeStyle=ink;ctx.setLineDash([2/view.k,2/view.k]);ctx.stroke();ctx.setLineDash([])}
  if(i===focus||match(i)){ctx.lineWidth=2/view.k;ctx.strokeStyle=i===focus?selc:hi;ctx.stroke()}});
 ctx.globalAlpha=1;ctx.fillStyle=ink;ctx.font=(11/view.k)+"px system-ui,sans-serif";
 N.forEach(function(n,i){if(!vis(i))return;var show=i===focus||match(i)||(nb&&nb[i])||(view.k>1.6&&n.deg>2);
  if(show){ctx.fillText(lab(n),n.x+n.r+3/view.k,n.y+3/view.k)}});
}
function loop(){if(alpha>0){tick();tick()}draw();requestAnimationFrame(loop)}
function resize(){var r=cv.parentNode.getBoundingClientRect();cv.width=r.width*dpr;cv.height=r.height*dpr}
function pos(ev){var r=cv.getBoundingClientRect();return{x:(ev.clientX-r.left-view.x)/view.k,y:(ev.clientY-r.top-view.y)/view.k,sx:ev.clientX-r.left,sy:ev.clientY-r.top}}
function pick(p){var best=-1,bd=1e9;N.forEach(function(n,i){if(!vis(i))return;var d=Math.hypot(n.x-p.x,n.y-p.y);if(d<n.r+4/view.k&&d<bd){bd=d;best=i}});return best}
cv.addEventListener("pointerdown",function(ev){var p=pos(ev),i=pick(p);cv.setPointerCapture(ev.pointerId);drag={node:i,sx:ev.clientX,sy:ev.clientY,vx:view.x,vy:view.y,moved:false};cv.style.cursor="grabbing"});
cv.addEventListener("pointermove",function(ev){var p=pos(ev);
 if(drag){var dx=ev.clientX-drag.sx,dy=ev.clientY-drag.sy;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;
  if(drag.node>=0){if(drag.moved){N[drag.node].x=p.x;N[drag.node].y=p.y;alpha=Math.max(alpha,.3)}}else{view.x=drag.vx+dx;view.y=drag.vy+dy}}
 else{var i=pick(p);if(i!==hov){hov=i;cv.style.cursor=i>=0?"pointer":"grab";tip(i)}}});
cv.addEventListener("pointerup",function(ev){if(drag&&!drag.moved){select(drag.node)}drag=null;cv.style.cursor="grab"});
cv.addEventListener("wheel",function(ev){ev.preventDefault();var p=pos(ev),f=Math.exp(-ev.deltaY*.0015),k=Math.max(.1,Math.min(6,view.k*f));
 view.x=p.sx-p.x*k;view.y=p.sy-p.y*k;view.k=k},{passive:false});
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function list(title,items){if(!items.length)return"";return"<h2>"+title+" ("+items.length+")</h2><ul>"+items.slice(0,40).map(function(e){var j=title==="Uses"?e[1]:e[0];
 return'<li><a class="n" data-i="'+j+'">'+esc(N[j].label?N[j].label+" · "+N[j].g:N[j].id)+'</a> <span class="tag">'+esc(famNames(e[2]))+"</span></li>"}).join("")+(items.length>40?'<li class="tag">… +'+(items.length-40)+" more</li>":"")+"</ul>"}
function select(i){sel=i;var el=document.getElementById("info");if(i<0){el.innerHTML="";return}
 var n=N[i];el.innerHTML='<h2>Selected</h2><div class="path">'+esc(n.label||n.id)+'</div><div class="tag">'+esc(n.lang)+(n.test?", test":"")+(n.at?"":", "+n.sym+" symbols · group "+esc(n.g))+"</div>"+
  (n.at?'<div class="tag">'+esc(n.at)+"</div>":"")+
  list("Uses",out[i].filter(evis))+list("Used by",inn[i].filter(evis))+'<p class="tag">Query it: <code>uccif index query --impact '+esc(n.q||n.id)+"</code></p>"}
function tip(i){cv.title=i>=0?N[i].id+" ("+N[i].deg+" links)":""}
document.getElementById("info").addEventListener("click",function(ev){var t=ev.target;if(t.dataset&&t.dataset.i){select(+t.dataset.i);var n=N[+t.dataset.i];view.x=cv.width/dpr/2-n.x*view.k;view.y=cv.height/dpr/2-n.y*view.k}});
document.getElementById("q").addEventListener("input",function(ev){query=ev.target.value.trim().toLowerCase();var m=-1;if(query){for(var i=0;i<N.length;i++)if(match(i)){m=i;break}}
 if(m>=0){select(m);view.x=cv.width/dpr/2-N[m].x*view.k;view.y=cv.height/dpr/2-N[m].y*view.k}});
document.getElementById("tests").addEventListener("change",function(ev){showTests=ev.target.checked;select(-1)});
document.getElementById("inf").addEventListener("change",function(ev){showInf=ev.target.checked;select(sel)});
document.getElementById("fams").innerHTML=FAM.map(function(f){return'<label><input type="checkbox" data-b="'+f[0]+'" checked> '+esc(f[1])+' <span class="tag">'+f[2]+"</span></label>"}).join("");
document.getElementById("fams").addEventListener("change",function(ev){var b=+ev.target.dataset.b;mask=ev.target.checked?(mask|b):(mask&~b);select(sel)});
if(D.mode==="components")document.getElementById("how").textContent="Each dot is a component; a line means the parent renders the child (dashed: matched by file name only). Click a component for its parents and children.";
if(D.mode==="symbols")document.getElementById("how").textContent="Functions, components, stores, props… of "+D.focus+" and the symbols they touch one hop away, coloured by file. Click one for what it uses and what uses it.";
document.getElementById("legend").innerHTML=groups.slice(0,30).map(function(g){return'<span><i style="background:'+color(g)+'"></i>'+esc(g)+"</span>"}).join("")+(groups.length>30?'<span class="tag">+'+(groups.length-30)+" more</span>":"");
document.getElementById("stats").textContent=D.shown+" of "+D.total_files+(D.mode==="symbols"?" symbols":D.mode==="components"?" components":" files")+" shown"+(D.isolated?" · "+D.isolated+" unconnected hidden":"")+" · "+E.length+" links";
window.addEventListener("resize",function(){resize();fit()});
if(window.matchMedia)window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change",function(){document.getElementById("legend").innerHTML=groups.slice(0,30).map(function(g){return'<span><i style="background:'+color(g)+'"></i>'+esc(g)+"</span>"}).join("")});
resize();for(var s=0;s<260;s++)tick();fit();loop();
if(!N.length){document.getElementById("info").innerHTML='<p class="tag">No import or call links in the index yet.</p>'}
</script></body></html>
"""
