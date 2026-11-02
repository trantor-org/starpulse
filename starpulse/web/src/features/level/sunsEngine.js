// The B · Suns board engine, ported verbatim from the approved canvas (SunTracesTC, artifact LKGRip1dE1bjMMp5wTS88z); its yellows are remapped
// (AC #7, design record #29). It draws into a scene `g` and reads and writes view state through `g.self` ({state, setState}); sunsScene.ts hosts it.
/* eslint-disable */
import { BOARD_COLOR, RAMP, onTheme, token } from "../../render/palette";
/* Every colour the scene draws is a role or neutral of the applied theme (render/palette.ts), read again whenever the theme changes, so a
   pack switch repaints with no reload. The yellow `run` role stays unused: this scene remaps its activity yellows to the ink. */
const TIER={},VC={},BC={},KC={},KT={},TASKC={},RAMP_=[];
var C={},PH,PHT,SB,SBT,DG,DGT;
onTheme(function(){
 C={ink:token('ink'),ink2:token('ink-2'),slate:token('slate'),muted:token('muted'),track:token('track'),bg0:token('bg0'),
  ok:token('ok'),okHi:token('ok-hi'),fail:token('fail'),failText:token('fail-text'),waits:token('waits'),
  agent:token('agent'),agentHi:token('agent-hi'),agentText:token('agent-text'),sbHi:token('submachine-hi'),review:BOARD_COLOR.review};
 PH=token('phase');PHT=token('phase-text');SB=token('submachine');SBT=token('submachine-text');DG=C.ok;DGT=C.okHi;
 Object.assign(TIER,{deep:C.agent,standard:C.waits,fast:C.ink});
 Object.assign(VC,{PASS:C.ok,CHANGES:C.fail});
 Object.assign(BC,{new:BOARD_COLOR.new,ready:BOARD_COLOR.ready,waiting:C.ink,in_progress:BOARD_COLOR.intoprogress,review:C.review,needs_attention:BOARD_COLOR.needs_attention,done:BOARD_COLOR.done,archived:BOARD_COLOR.archived});
 Object.assign(KC,{phase:PH,sub:SB,dag:DG,tpl:C.agent});
 Object.assign(KT,{phase:PHT,sub:SBT,dag:DGT,tpl:C.agentText});
 Object.assign(TASKC,{deep:C.agentText,standard:C.waits});
 RAMP_.splice(0,RAMP_.length,...RAMP.map(function(c,i){return i===7?C.ink:c;}));
});
const LENSES=['security','ux','ui','code','simplify'];
const LN={security:'Security',ux:'UX',ui:'UI',code:'Code',simplify:'Simplify'};
const PN={build:'Build',qa:'QA',deliver:'Deliver',review_fix:'Review fix',parked:'Needs attention',done:'Review'};
const STEPS={build:['worktree_ready','red_proven','green','criteria_checked','docs_reconciled'],qa:['reviewing'],deliver:['lint_green','committed','pushed','pr_opened','ci_green','pr_ready'],review_fix:['threads_read','fixes_pushed','review_recorded']};
function L(v,s){return {state:v||'pending',step:v?3:(s||0)};}
function trailOf(j){return j.trail.map(function(s){
 var color=s.phase==='qa'?SBT:(s.phase==='parked'?C.fail:PH);
 return {color:color,label:PN[s.phase]+' · round '+s.round+(s.mins?' · '+s.mins+' min':''),hasWhy:!!s.why,why:s.why||''};});}
function statusOf(j){
 if(j.phase==='parked') return {t:'Needs attention',c:C.failText};
 if(j.phase==='done') return {t:'In Review',c:C.okHi};
 if(j.phase==='qa'){var p=LENSES.filter(function(l){return j.lenses[l].state==='pending';}).length;return {t:'QA '+(LENSES.length-p)+'/'+LENSES.length,c:SBT};}
 return {t:PN[j.phase],c:C.slate};}
function longStatus(j){var s=statusOf(j);
 if(j.phase==='build'||j.phase==='deliver'||j.phase==='review_fix') return {t:PN[j.phase]+' · '+STEPS[j.phase][j.step].replace(/_/g,' ')+' · '+j.mins+' min'+(j.attended?' · attended':''),c:C.slate};
 if(j.phase==='qa') return {t:'QA round '+j.round+' · '+s.t.slice(3)+' lenses reported · '+j.mins+' min',c:SBT};
 return s;}
function fleetOf(self,jobs){return jobs.map(function(j){var on=self.state.sel===j.id,st=statusOf(j);
 return {id:j.id,title:j.title,status:st.t,statusColor:st.c,aria:j.id+' '+j.title+', '+st.t,pick:function(){self.setState({sel:j.id});},
  dot:'width:7px;height:7px;border-radius:50%;flex-shrink:0;background:'+TIER[j.tier]+';box-shadow:0 0 6px '+TIER[j.tier]+(j.attended?',0 0 0 3px '+hexA(C.agent,.35):''),
  rowStyle:'display:flex;flex-direction:column;gap:3px;width:100%;padding:9px 20px;border:none;border-left:2px solid '+(on?C.agent:'transparent')+';background:'+(on?hexA(C.slate,.06):'transparent')+';color:inherit'};});}
function rnd(seedv){var x=seedv;return function(){x=(x*9301+49297)%233280;return x/233280;};}
function starfield(w,h,n){var r=rnd(7),out=[];for(var i=0;i<n;i++){var a=r(),b=r(),c=r();
 out.push({style:'position:absolute;left:'+(a*w).toFixed(1)+'px;top:'+(b*h).toFixed(1)+'px;width:'+(c>.9?2:1)+'px;height:'+(c>.9?2:1)+'px;border-radius:50%;background:var(--ink-2);opacity:'+(.12+c*.4).toFixed(2)+(c>.85?';animation:sd-twinkle '+(3+c*4).toFixed(1)+'s ease-in-out infinite':'')});}return out;}
/* a lens reviews, then records its verdict: the row runs straight and forks in its last stretch, as the mock's */
const LSTEPS=['reviewing','verdict'];
const DSTEPS=['queued','running','succeeded'];
function pt(x,y){return x.toFixed(1)+','+y.toFixed(1);}
function seen(j,p){return p===j.phase||j.trail.some(function(s){return s.phase===p;});}
function fillOf(j,p,n){if(j.phase===p) return p==='qa'?1:j.step+1;return seen(j,p)?n:0;}
function lensOf(j,l){var last=null;j.trail.forEach(function(s){if(s.phase==='qa'&&s.v) last=s;});
 if(j.phase==='qa'){var c=j.lenses[l];return c.state==='pending'?{fill:c.step,state:null,live:c.step>0,at:0}:{fill:3,state:c.state,live:false,at:-1};}
 return last?{fill:3,state:last.v[l],live:false,at:-1}:null;}
function dagOf(j){if(j.phase==='deliver'&&j.step>=4) return j.step===4?{fill:2,live:true}:{fill:3,live:false};
 return (seen(j,'review_fix')||j.phase==='done')?{fill:3,live:false}:null;}
function station(out,x,y,col,filled,r){r=r||3;
 out.push({style:'position:absolute;left:'+(x-r)+'px;top:'+(y-r)+'px;width:'+(2*r)+'px;height:'+(2*r)+'px;border-radius:50%;box-sizing:border-box;'+(filled?'background:'+col+';box-shadow:0 0 6px '+col:'border:1.2px solid '+col+';opacity:.6')});}
function pulsar(out,x,y){out.push({style:'position:absolute;left:'+(x-11)+'px;top:'+(y-11)+'px;width:22px;height:22px;border-radius:50%;border:1.5px solid '+hexA(C.ink,.9)+';box-sizing:border-box;animation:sd-pulse 1.8s ease-out infinite'});}
function jobDot(out,x,y,col,r){r=r||7;out.push({style:'position:absolute;left:'+(x-r)+'px;top:'+(y-r)+'px;width:'+(2*r)+'px;height:'+(2*r)+'px;border-radius:50%;background:radial-gradient(circle at 40% 35%,'+C.ink+','+col+' 55%,'+hexA(C.bg0,.3)+');box-shadow:0 0 16px 3px '+col+';transition:left .9s ease,top .9s ease'});}
function text(out,t,sub,x,y,col,o){o=o||{};
 out.push({text:t,sub:sub||'',subColor:o.subColor||C.slate,style:'position:absolute;left:'+(o.align==='right'?x-220:(o.align==='center'?x-110:x))+'px;top:'+y+'px;width:220px;text-align:'+(o.align||'left')+';font-size:'+(o.size||'.72em')+';font-weight:300;letter-spacing:'+(o.ls||'.02em')+';color:'+col+';white-space:nowrap'});}
function kickReasons(j){var k=j.trail.filter(function(s){return s.phase==='qa'&&s.why;}).map(function(s){return {text:'r'+s.round+' · '+s.why,color:C.failText};});
 if(j.phase==='parked') k.push({text:'Left In Progress: '+j.trail[j.trail.length-1].why,color:C.fail});
 return k.length?k:[{text:'no kickbacks',color:C.muted}];}
/* The Board transitions into In Progress and out of it, laid as a Star Map state level lays them: entries fan in from the left edge to the
   pivot's rim, exits fan out to the right edge, each shaded from its source state's colour to its target's, named "from X" / "to X" at the edge. */
const BN={new:'New',ready:'Ready',waiting:'Waiting',review:'Review',needs_attention:'Needs attention',done:'Done',archived:'Archived'};
const ENTRY=['new','ready','waiting','needs_attention','review','done'],EXITS=['ready','waiting','needs_attention','review','done','archived'];
function qpt(a,c,b,t){var u=1-t;return {x:u*u*a.x+2*u*t*c.x+t*t*b.x,y:u*u*a.y+2*u*t*c.y+t*t*b.y};}
function flows(T,o){var fl={},hot={};
 [[ENTRY,-1,'e',o.inP,o.inR,o.inY],[EXITS,1,'x',o.outP,o.outR,o.outY]].forEach(function(z){var list=z[0],side=z[1],pre=z[2],P=z[3],R=z[4],FY=z[5];
  list.forEach(function(s,i){var off=i-(list.length-1)/2,a=(side<0?Math.PI:0)+side*off*.12,rim={x:P.x+Math.cos(a)*R,y:P.y+Math.sin(a)*R};
   var far={x:side<0?-10:1000,y:FY+off*o.gap},c={x:rim.x+side*o.pull,y:far.y},p0=side<0?far:rim,p1=side<0?rim:far;
   var lit=(side<0?o.litIn:o.litOut)===s,c1=side<0?BC[s]:BC.in_progress,c2=side<0?BC.in_progress:BC[s];
   fl[pre+i]={d:'M'+pt(p0.x,p0.y)+' Q'+pt(c.x,c.y)+' '+pt(p1.x,p1.y),x1:p0.x.toFixed(1),y1:p0.y.toFixed(1),x2:p1.x.toFixed(1),y2:p1.y.toFixed(1),c1:c1,c2:c2,
    op:lit?.95:(s==='archived'?.18:.38),w:lit?2.4:1.1};
   if(lit) hot[side<0?'in':'out']={a:p0,c:c,b:p1};
   text(T,(side<0?'from ':'to ')+BN[s],'',side<0?20:970,far.y-18,lit?C.ink:C.muted,{align:side<0?'left':'right',size:'.7em'});});});
 return {fl:fl,hot:hot};}
function litOf(j){return {litIn:seen(j,'review_fix')?'review':'ready',litOut:j.phase==='done'?'review':(j.phase==='parked'?'needs_attention':null)};}
/* Round 4: In Progress is the focal sun (drawn as the Star Map's drawSun draws a state level's sun), the Board flow lines fan into and out of its
   rim left and right, and the job's phase machines grow as straight rays into the top and bottom sectors only, clear of those lines. */
const SR=34,CX=495,CY=478;
const RAY={build:218,qa:270,deliver:322,review_fix:90},SP=26;var R0=114,RING_OUT=92;
function RP(r,d){var a=d*Math.PI/180;return {x:CX+r*Math.cos(a),y:CY+r*Math.sin(a)};}
function sunParts(core,jobs,j){
 var G=SR+5*SR;
 core.push({style:'position:absolute;left:'+(CX-G)+'px;top:'+(CY-G)+'px;width:'+(2*G)+'px;height:'+(2*G)+'px;border-radius:50%;background:radial-gradient(circle closest-side,'+hexA(C.slate,.55)+' 0%,'+hexA(C.slate,.2)+' 25%,'+hexA(C.slate,0)+' 100%)'});
 [SR+9].forEach(function(r){core.push({style:'position:absolute;left:'+(CX-r)+'px;top:'+(CY-r)+'px;width:'+(2*r)+'px;height:'+(2*r)+'px;border-radius:50%;border:1px solid '+hexA(C.slate,.16)+';box-sizing:border-box'});});
 core.push({style:'position:absolute;left:'+(CX-SR)+'px;top:'+(CY-SR)+'px;width:'+(2*SR)+'px;height:'+(2*SR)+'px;border-radius:50%;background:radial-gradient(circle,'+C.agentHi+' 0%,'+hexA(C.slate,.95)+' 50%,'+hexA(C.slate,.6)+' 100%);animation:sd-breathe 3.2s ease-in-out infinite'});
 var others=jobs.filter(function(x){return x.id!==j.id&&x.phase!=='parked';});
 others.forEach(function(o,i){var a=(i/others.length)*2*Math.PI+.3,r=SR+9;core.push({style:'position:absolute;left:'+(CX+r*Math.cos(a)-2.5)+'px;top:'+(CY+r*Math.sin(a)-2.5)+'px;width:5px;height:5px;border-radius:50%;background:'+TIER[o.tier]+';box-shadow:0 0 5px '+TIER[o.tier]});});}
/* A phase ray: a spoke from the rim, its stations along it, its name beside the first station. */
function ray(g,j,p,names,live){var th=RAY[p],n=names.length,s0=RP(SR+4,th),e=RP(R0+(n-1)*SP,th),f=fillOf(j,p,n),here=null;
 g.L.ph.push('M'+pt(s0.x,s0.y)+' L'+pt(e.x,e.y));
 names.forEach(function(nm,i){var q=RP(R0+i*SP,th);station(g.S,q.x,q.y,PH,i<f,3.2);if(live&&i===(p==='qa'?0:j.step)) here={x:q.x,y:q.y,name:nm,a:th};});
 var side=Math.cos(th*Math.PI/180),q0=RP(R0+(p==='qa'?0:SP*.5),th),pa=(th+(side<0?-90:90))*Math.PI/180,lp={x:q0.x+Math.cos(pa)*14,y:q0.y+Math.sin(pa)*14};
 if(p==='qa') lp={x:q0.x+14,y:q0.y+4};
 text(g.T,PN[p].toLowerCase(),'',lp.x,lp.y-8,hexA(PHT,live?.95:.55),{align:p==='qa'?'left':(side<-.2?'right':(side>.2?'left':'center')),size:'.76em'});
 return {here:here,end:e,at:function(i){return RP(R0+i*SP,th);}};}
function lensRows(j){return LENSES.map(function(l){var s=lensOf(j,l);return {l:l,s:s};});}
function arcP(cx,cy,rx,ry,a0,a1){if(a1-a0>=359.9) return arcP(cx,cy,rx,ry,a0,a0+180)+' '+arcP(cx,cy,rx,ry,a0+180,a0+359.9);
 function e(d){var a=d*Math.PI/180;return {x:cx+rx*Math.cos(a),y:cy+ry*Math.sin(a)};}
 var p=e(a0),q=e(a1);return 'M'+pt(p.x,p.y)+' A'+rx.toFixed(1)+','+ry.toFixed(1)+' 0 '+(a1-a0>180?1:0)+' 1 '+pt(q.x,q.y);}
function lensState(j,l){var s=lensOf(j,l);if(!s) return null;return {p:s.fill/3,state:s.state,live:s.live,at:s.at,word:s.state||(s.live?LSTEPS[s.at].replace(/_/g,' '):(j.phase==='qa'?'queued':''))};}
function onRing(r,deg){return RP(r,deg);}
function bucketFor(g,s,w){return s.state?(s.state==='PASS'?g.L[w?'passW':'pass']:g.L[w?'chgW':'chg']):g.L[w?'sbW':'sb'];}
function tdot(out,x,y,j,pinned,r){r=r||3.2;var c=TIER[j.tier];
 out.push({style:'position:absolute;left:'+(x-r)+'px;top:'+(y-r)+'px;width:'+(2*r)+'px;height:'+(2*r)+'px;border-radius:50%;background:'+c+';box-shadow:0 0 6px '+c+(pinned?',0 0 0 2px '+C.bg0+',0 0 0 3.2px '+C.agentHi:'')+';transition:left .9s ease,top .9s ease'});}
function rampCol(i,n){return RAMP_[Math.round((n>1?i/(n-1):0)*(RAMP_.length-1))];}
/* Backtraces always on: every row draws what its round walked, not only on hover. Rows stay compact; there is no expanded view. */
const TRACE_ALL=true,COMPACT_ALL=true;
/* Lines only between groups of rows (phase machines and the lens machines), none inside a group. */
const NO_SEPS=true;
/* Round 12 · Sun: the rounded circuit view with its states drawn as suns. One shape for every state, dim until the task reaches it. Grey for structure, colour only for meaning (blue phase, teal lens, green DAG, green pass,
   rose changes; the task itself in its tier colour). In Progress's own exits leave the template as labelled traces, the way a Star Map drill-in
   shows flow to other states, so no other board state is drawn here. */
const HEX='clip-path:polygon(25% 0,75% 0,100% 50%,75% 100%,25% 100%,0 50%)';
function fR(s,o){if(s&&s.mini) return s.q?3:4.2;return o.big?10:(s.q?5:7);}
function glowOf(g,x,y,R,col,k,a){span(g,'left:'+(x-R*k)+'px;top:'+(y-R*k)+'px;width:'+(R*2*k)+'px;height:'+(R*2*k)+'px;border-radius:50%;background:radial-gradient(circle closest-side,'+hexA(col,a)+',transparent)');}
/* The viewed task at work: the state it rests in lights, filled in its tier colour with a glow; no other task draws on the template. A task
   whose comet is still flying here lights it only once it lands. */
function orbit(g,list,sun,x,y,R){var now=Date.now();list.forEach(function(e){var t=e.job,id=t.id,col=TASKC[t.tier]||C.ink,r=Math.max(R,4)+1;
  if(FLY[id]&&FLY[id].fly.some(function(f){return f.to===sun&&now<f.t+TRAVEL;})) return;
  g.D.push({key:'orb:'+id+':'+sun,style:'position:absolute;left:'+(x-r)+'px;top:'+(y-r)+'px;width:'+(2*r)+'px;height:'+(2*r)+'px;border-radius:50%;box-sizing:border-box;background:'+col+';box-shadow:0 0 14px '+hexA(col,.8)});});}
function disc(g,x,y,r,st){span(g,'left:'+(x-r)+'px;top:'+(y-r)+'px;width:'+(2*r)+'px;height:'+(2*r)+'px;border-radius:50%;box-sizing:border-box;'+st);}
/* Sun: a reached state is a star with a white-hot core and a corona; an unreached one is an unlit slate disc whose ring reads at 3:1 on the
   background; a final state's corona is ringed. */
function hexPad(g,x,y,R,col,fill,o){o=o||{};if(fill) glowOf(g,x,y,R,col,o.glow?3.4:2.2,o.glow?.55:.32);
 if(o.fin) disc(g,x,y,R+4,'border:1px dashed '+hexA(col,o.dim?.8:.6));
 if(fill) disc(g,x,y,R,'background:radial-gradient(circle,'+C.ink+' 0%,'+hexA(col,1)+' 58%,'+hexA(col,.85)+' 100%);box-shadow:0 0 '+(R*.8)+'px '+hexA(col,.7)+(o.glow?';animation:sd-breathe 2.4s ease-in-out infinite':''));
 else disc(g,x,y,R*.85,'background:'+hexA(C.slate,.28)+';border:1.5px solid '+C.slate+';');}
/* Rounded: a run that changes level is one smooth S-curve, level at both ends, instead of an octilinear dogleg. */
function trace(a,b,ta,tb,mode){if(Math.abs(a.y-b.y)<.5) return octi(a,b,ta,tb,mode);var dir=b.x>a.x?1:-1,sx=a.x+dir*ta,ex=b.x-dir*tb,k=(ex-sx)*.55;
 return {d:'M'+sx.toFixed(1)+','+a.y+' C'+(sx+k).toFixed(1)+','+a.y+' '+(ex-k).toFixed(1)+','+b.y+' '+ex.toFixed(1)+','+b.y,mid:{x:(sx+ex)/2,y:(a.y+b.y)/2}};}
/* The task moves the way StarPulse moves one (orbitTasks in machineLedgerDraw.ts), scaled to the ledger's smaller states: at rest it is a
   still dot in its tier colour beside the state it is in; when it steps, a comet runs the flow line in 3 s (ease-out) with
   a fading tail and the edge heated under it, then one ring pulses where it lands. A move is a change in where a row's task sits since
   the last frame; a row seen for the first time, a newly picked task and a scrubbed replay only rest. */
var MOVES={},FLY={},SENT={},LAST_ROWS,PICKED=false,ANIM_UNTIL=0;const TRAVEL=3000,PULSE=1800,DROP=4000;
/* StarPulse's task colours by tier (a task dot is lighter than the tier's own swatch) */
function easeO(u){return 1-Math.pow(1-u,3);}
/* points along an absolute M/L/Q/C path, by length */
function sampler(d){var t=d.match(/[MLQC]|-?[\d.]+/g)||[],pts=[],i=0,cmd,x=0,y=0;function nx(){return +t[i++];}
 while(i<t.length){if(/[MLQC]/.test(t[i])) cmd=t[i++];
  if(cmd==='M'||cmd==='L'){x=nx();y=nx();pts.push({x:x,y:y});}
  else if(cmd==='Q'){var ax=nx(),ay=nx(),bx=nx(),by=nx(),x0=x,y0=y;for(var k=1;k<=10;k++){var u=k/10,v=1-u;pts.push({x:v*v*x0+2*v*u*ax+u*u*bx,y:v*v*y0+2*v*u*ay+u*u*by});}x=bx;y=by;}
  else if(cmd==='C'){var c1x=nx(),c1y=nx(),c2x=nx(),c2y=nx(),ex=nx(),ey=nx(),x1=x,y1=y;for(var m=1;m<=16;m++){var w=m/16,z=1-w;pts.push({x:z*z*z*x1+3*z*z*w*c1x+3*z*w*w*c2x+w*w*w*ex,y:z*z*z*y1+3*z*z*w*c1y+3*z*w*w*c2y+w*w*w*ey});}x=ex;y=ey;}
  else i++;}
 var acc=[0];for(var n=1;n<pts.length;n++) acc.push(acc[n-1]+Math.hypot(pts[n].x-pts[n-1].x,pts[n].y-pts[n-1].y));var len=acc[acc.length-1]||1;
 return function(u){var L=Math.max(0,Math.min(1,u))*len,n=1;while(n<acc.length-1&&acc[n]<L) n++;var a=pts[n-1]||pts[0],b=pts[n]||a,f=(L-acc[n-1])/Math.max(acc[n]-acc[n-1],1e-6);
  return {x:a.x+(b.x-a.x)*f,y:a.y+(b.y-a.y)*f};};}
function moveOf(j,o,state){var now=Date.now(),k=j.id+'|'+o.key,sig=j.phase+':'+j.round+':'+o.node,m=MOVES[k],still=state.at!=null&&!state.replaying;
 if(!m||m.sig!==sig){var t=-1e9;if(!PICKED&&!still) t=m&&m.phase===j.phase&&m.round===j.round?now:now-TRAVEL;if(o.land) t=o.walk?o.land:o.land-TRAVEL;MOVES[k]=m={sig:sig,phase:j.phase,round:j.round,t:t};}
 if(m.t+TRAVEL+PULSE>now) ANIM_UNTIL=Math.max(ANIM_UNTIL,m.t+TRAVEL+PULSE);return o.land>now?-1:now-m.t;}
/* A flow line as StarPulse draws one: thin, dashed, streaming toward its target. */
function flow(g,d,col,a){line(g,d,hexA(col,a||.6),1.3,{dash:'2 5',st:'animation:sd-march 1.4s linear infinite'});}
/* One task's comet across the template, the same 3 s run with its fading tail and heated edge as a row's, then one ring where it lands, in the task's own colour. */
function cometOf(g,f,col,now,SUN){var age=now-f.t;if(age<0) return;
 if(age<TRAVEL){var at=sampler(f.d),u=easeO(age/TRAVEL),h=at(u);line(g,f.d,hexA(col,.22),2.4,{cap:'butt',sharp:true});
  for(var i=0;i<14;i++){var a=at(u-.27*(14-i)/14),b=at(u-.27*(13-i)/14);line(g,'M'+a.x.toFixed(1)+','+a.y.toFixed(1)+' L'+b.x.toFixed(1)+','+b.y.toFixed(1),hexA(col,(i+1)/14*.6),(i+1)/14*2.6,{sharp:true});}
  glowOf(g,h.x,h.y,10,col,1,.7);disc(g,h.x,h.y,3.4,'background:'+hexA(col,.95)+';box-shadow:0 0 6px '+hexA(col,.8));return;}
 var s=SUN[f.to];if(s&&age<TRAVEL+PULSE){var p=(age-TRAVEL)/PULSE,r=3+easeO(p)*18;disc(g,s.x,s.y,s.r+r,'border:'+(2*(1-p)+.4).toFixed(2)+'px solid '+hexA(col,Math.pow(1-p,2)*.85));}}
/* A task reaching a phase or a lens is sent from that state in the template down its stem, along the hairline and the lane to its row: one 4 s
   run over two scenes, the graph's above the lane's top and the rows' below it, since the rows scroll under their own y map. */
function dropOf(g,top,up,down,col,t,now){var age=now-t;if(age<0||age>=DROP) return;
 var cut=HAIR+8,at=sampler(up+down.slice(down.indexOf(' '))),u=easeO(age/DROP),h=at(u),l0=g.L.length,s0=g.S.length,tl0=top.L.length,ts0=top.S.length;function sc(y){return y<=cut?top:g;}
 line(top,up,hexA(col,.22),2.4,{cap:'butt',sharp:true});line(g,down,hexA(col,.22),2.4,{cap:'butt',sharp:true});
 for(var i=0;i<14;i++){var a=at(u-.12*(14-i)/14),b=at(u-.12*(13-i)/14);line(sc(b.y),'M'+a.x.toFixed(1)+','+a.y.toFixed(1)+' L'+b.x.toFixed(1)+','+b.y.toFixed(1),hexA(col,(i+1)/14*.6),(i+1)/14*2.6,{sharp:true});}
 glowOf(sc(h.y),h.x,h.y,10,col,1,.7);disc(sc(h.y),h.x,h.y,3.4,'background:'+hexA(col,.95)+';box-shadow:0 0 6px '+hexA(col,.8));
 g.L.slice(l0).concat(g.S.slice(s0),top.L.slice(tl0),top.S.slice(ts0)).forEach(function(p){p.fx=true;});}
function arrowHead(g,x,y,col){line(g,'M'+(x-5)+','+(y-3.5)+' L'+x+','+y+' L'+(x-5)+','+(y+3.5),col,1.3,{cap:'round',sharp:true});}
const STYLE={M:{base:24,step:8,back:'below',skip:'above',lab:24},MINI:{base:12,step:6,lane:.8,minH:60,pad:16},
 state:function(g,s,o){var R=fR(s,o),col=s.q?s.c:KC[o.kind];if(o.dot) return;
  hexPad(g,s.x,s.y,R,o.on?col:C.muted,o.on,{fin:s.fin,glow:o.cur,dim:!o.on});
  /* a state's name sits where no line runs: above it, or below it when a loop leaves upward, or up and to the right when loops leave both ways */
  var lx=s.x,ly=s.y-R-17,al='center';if((o.legUp||o.init)&&!o.legDown) ly=s.y+R+4;else if(o.legUp&&o.legDown){lx=s.x+R+5;ly=s.y-R-14;al='left';}
  if(s.q){lx=s.x+R+6;ly=s.y-8;al='left';}
  /* folded: above the state if no loop runs over it, else below, else above the highest loop */
  else if(s.mini){lx=s.x;al='center';ly=!o.upLv?s.y-R-14:(!o.downLv?s.y+R+3:s.y-(o.M.base+o.upLv*o.M.step)-13);}
  /* a folded row names only the state its task is in */
  if((s.mini?o.cur:o.label)&&!(s.q&&!o.on)) name(g,o.name,lx,ly,{align:al,size:s.q?'.66em':'.68em',col:s.q?hexA(s.c,.9):(o.on?hexA(C.ink2,.8):hexA(C.slate,.5))});},
 edge:function(g,a,b,o){var c=trace(a,b,fR(a,{})+3,fR(b,{})+3);if(o.on) line(g,c.d,b.q?b.c:KC[o.kind],1.8,{cap:'butt'});else flow(g,c.d,b.q?b.c:KC[o.kind],.45);},
 loop:function(g,a,b,off,o){var R=fR(a,{}),dir=b.x>a.x?1:-1,y=a.y+off,s=off<0?-1:1;
  flow(g,'M'+a.x+','+(a.y+s*R)+' L'+a.x+','+(y-s*5)+' L'+(a.x+dir*5)+','+y+' L'+(b.x-dir*5)+','+y+' L'+b.x+','+(y-s*5)+' L'+b.x+','+(b.y+s*R),C.muted,.7);},
 task:function(g,cur,prev,j,o){var col=TASKC[j.tier]||C.ink,R=fR(cur,{}),k=cur.mini?.5:.7,age=moveOf(j,o,g.self.state);if(age<0) return;
  if(age<TRAVEL){var d=roundPath(trace(prev,cur,fR(prev,{})+3,R+3).d,ROUND_R),at=sampler(d),u=easeO(age/TRAVEL),h=at(u);
   line(g,d,hexA(col,.22),cur.mini?1.8:2.4,{cap:'butt'});
   for(var i=0;i<14;i++){var a=at(u-.27*(14-i)/14),b=at(u-.27*(13-i)/14);line(g,'M'+a.x.toFixed(1)+','+a.y.toFixed(1)+' L'+b.x.toFixed(1)+','+b.y.toFixed(1),hexA(col,(i+1)/14*.6),(i+1)/14*2.6*k/.7,{sharp:true});}
   glowOf(g,h.x,h.y,14*k,col,1,.7);disc(g,h.x,h.y,6*k*.75,'background:'+hexA(col,.95)+';box-shadow:0 0 '+(6*k)+'px '+hexA(col,.8));return;}
  if(age<TRAVEL+PULSE){var p=(age-TRAVEL)/PULSE,r=(3+easeO(p)*18)*k/.7;disc(g,cur.x,cur.y,R+r,'border:'+(2*(1-p)+.4).toFixed(2)+'px solid '+hexA(col,Math.pow(1-p,2)*.85));}
  disc(g,cur.x,cur.y,R+1,'background:'+col+';box-shadow:0 0 14px '+hexA(col,.8));},
 mark:function(g,x,y,col){hexPad(g,x,y,4,col,true);},
 crowd:function(){},
 template:function(g,jobs,j){var Y=TY,X={build:470,fork:548,join:752,deliver:850,review_fix:975},EX=1176,at={},E={},BUS=66,MUTE=C.muted;
  /* where a task is: its phase's sun, each lens still reviewing it, the join once none is, or the exit line it left by */
  function nodesOf(x){if(x.phase==='qa'){var left=LENSES.filter(function(l){return x.lenses[l].state==='pending';});return left.length?left:['join'];}return [x.exit||x.phase];}
  jobs.forEach(function(x){if(!x.settling) nodesOf(x).forEach(function(k){(at[k]=at[k]||[]).push({job:x});});});
  function run(a,b,col,mode,key){var c=trace(a,b,a.r||0,b.r||0,mode);flow(g,c.d,col,.7);if(key) E[key]=roundPath(c.d,ROUND_R);return c;}
  function edge(key,d){E[key]=roundPath(d,ROUND_R);flow(g,d,MUTE,.8);}
  function n(k){return (at[k]||[]).length;}
  /* only the viewed task lights a state and flies */
  function mine(k){return (at[k]||[]).filter(function(e){return e.job.id===j.id;});}
  function tasksIn(k,label,kind){return {title:label,sub:kind+' · '+n(k)+' task'+(n(k)===1?'':'s')+' here now',rows:(at[k]||[]).map(function(e){var x=e.job;return {k:x.id,v:x.title,c:TIER[x.tier]};})};}
  /* in: one streaming line per board state that hands a task to In Progress */
  var ENT=[['Ready','CLAIM','an agent claims the task'],['Waiting','START_WAITING','what it waited on is done'],['Needs Attention','RESUME','a person resumes it'],['Review','SEND_BACK','review sends it back'],['New','CREATE_IN_PROGRESS','created straight into work'],['Done','REOPEN','a closed task is reopened']];
  /* entries come in from the pane's left edge and exits leave at its right edge, each named just above its line at that edge */
  var BACK={1:'parked',2:'needs_attention',3:'review_recorded',5:'finalized'};
  ENT.forEach(function(e,k){var y=Y-70+k*28,d='M262,'+y+' L300,'+y+' Q410,'+y+' 457,'+(Y+(y-Y)*.12);flow(g,d,MUTE,.8);if(BACK[k]) E[BACK[k]+'>build']=d;name(g,e[0],264,y-15,{size:'.66em',col:hexA(C.slate,.75)});
   hv(g,'entry:'+e[0],260,y-16,110,22,{t:'From '+e[0],lines:[e[2]]},{title:'From '+e[0],sub:'board event '+e[1]+' → In Progress',rows:[{k:'lands on',v:'Build'},{k:'when',v:e[2]}]});});
  /* the sequence, the fork and the join */
  run({x:X.build,y:Y,r:13},{x:X.fork,y:Y,r:3},KC.phase,null,'build>fork');run({x:X.join,y:Y,r:3},{x:X.deliver,y:Y,r:13},KC.phase,null,'join>deliver');run({x:X.deliver,y:Y,r:13},{x:X.review_fix,y:Y,r:13},KC.phase,null,'deliver>review_fix');
  LENSES.forEach(function(l){run({x:X.fork,y:Y},{x:650,y:LYT[l],r:12},KC.sub,'early','fork>'+l);run({x:650,y:LYT[l],r:12},{x:X.join,y:Y},KC.sub,'late',l+'>join');});
  [X.fork,X.join].forEach(function(x){span(g,'left:'+(x-3)+'px;top:'+(Y-3)+'px;width:6px;height:6px;border-radius:50%;background:'+KC.sub);});
  hv(g,'fork',X.fork-8,Y-8,16,16,{t:'Fork',lines:['the four lenses start together']},null);hv(g,'join',X.join-8,Y-8,16,16,{t:'Join',lines:['deliver starts when all four pass']},null);
  /* loops */
  edge('review_fix>deliver','M968,'+(Y-9)+' L968,'+(Y-33)+' L963,'+(Y-38)+' L862,'+(Y-38)+' L857,'+(Y-33)+' L857,'+(Y-9));
  hv(g,'loop:fix',857,Y-44,111,14,{t:'Review fix → Deliver',lines:['fixes pushed, deliver runs again']},{title:'Review fix → Deliver',sub:'event LINT_GREEN',rows:[{k:'when',v:'the PR head holds every fix and lint is green'},{k:'fired by',v:'agent-cmd lint, pre-commit hook'}]});
  edge('join>build','M'+X.join+','+(Y+5)+' L'+X.join+','+(LYT.simplify+33)+' L'+(X.join-5)+','+(LYT.simplify+38)+' L510,'+(LYT.simplify+38)+' L505,'+(LYT.simplify+33)+' L505,'+(Y+20)+' L483,'+(Y+7));
  hv(g,'loop:changes',505,LYT.simplify+30,247,16,{t:'QA → Build',lines:['a lens asked for changes','next round, up to 3']},{title:'QA → Build',sub:'a kickback: the next round of build',rows:[{k:'when',v:'any lens returns CHANGES'},{k:'limit',v:'3 rounds, then the task goes to Needs Attention'}]});
  /* out: each exit to the board state it hands the task to; parked leaves from any phase over the top */
  flow(g,'M440,'+BUS+' L'+EX+','+BUS,MUTE,.8);
  [['build',463,440],['deliver',843,820],['review_fix',982,1005]].forEach(function(p){var d='M'+p[1]+','+(Y-8)+' L'+p[2]+','+(Y-31)+' L'+p[2]+','+BUS;flow(g,d,MUTE,.8);E[p[0]+'>parked']=roundPath(d,ROUND_R)+' M'+p[2]+','+BUS+' L'+EX+','+BUS;});
  edge('review_fix>review_recorded','M988,'+Y+' L'+EX+','+Y);
  /* Needs Attention and Done leave Deliver as flat curves, the way the entries arrive: Done dips deeper and sooner, so it stays under Needs Attention */
  edge('deliver>needs_attention','M872,'+(Y+4)+' C905,'+(Y+20)+' 910,'+(Y+74)+' 980,'+(Y+74)+' L'+EX+','+(Y+74));
  edge('deliver>finalized','M866,'+(Y+7)+' C890,'+(Y+20)+' 892,'+(Y+100)+' 970,'+(Y+100)+' L'+EX+','+(Y+100));
  [[BUS,'Waiting','PARK_ON_CRITERIA','parked, from any phase','build, deliver or review fix'],[Y,'Review','REVIEW','review recorded','review fix'],[Y+74,'Needs Attention','DEFER','CI blocked','deliver'],[Y+100,'Done','FINALIZE','finalized, no PR','deliver']].forEach(function(o){
   arrowHead(g,EX,o[0],MUTE);name(g,o[1],EX-14,o[0]-18,{align:'right',size:'.74em',col:hexA(C.ink2,.8)});
   hv(g,'exit:'+o[1],EX-124,o[0]-18,128,24,{t:'To '+o[1],lines:[o[3]],x:EX-210,y:o[0]+8},{title:'To '+o[1],sub:'board event '+o[2],rows:[{k:'leaves from',v:o[4]},{k:'when',v:o[3]}]});});
  /* the task's move: what it left and what it entered since the last draw, each a run along the lines; every task's flight is tracked, and the viewed one's is drawn.
     A task first seen, or whose history is still loading, only rests. The real BUILD_DONE has no line of its own, so it rides the level lens's.
     A stop on an exit line ends one run and the next starts from there, one after the other. */
  E['build>deliver']=[E['build>fork'],E['fork>ui'],E['ui>join'],E['join>deliver']].join(' ');
  var SUN={build:{x:X.build,y:Y,r:10},deliver:{x:X.deliver,y:Y,r:10},review_fix:{x:X.review_fix,y:Y,r:10},join:{x:X.join,y:Y,r:3},parked:{x:EX,y:BUS,r:0},review_recorded:{x:EX,y:Y,r:0},needs_attention:{x:EX,y:Y+74,r:0},finalized:{x:EX,y:Y+100,r:0}};
  LENSES.forEach(function(l){SUN[l]={x:650,y:LYT[l],r:8};});
  var OUT={parked:1,needs_attention:1,review_recorded:1,finalized:1},live={},now=Date.now();
  function routeOf(a,b){var seen={},q=[[a]];seen[a]=1;while(q.length){var p=q.shift(),u=p[p.length-1];if(u===b) return p;Object.keys(E).forEach(function(k){var s=k.split('>');if(s[0]===u&&!seen[s[1]]){seen[s[1]]=1;q.push(p.concat(s[1]));}});}return null;}
  function legs(p,t){var out=[],d=[];p.slice(1).forEach(function(b,i){d.push(E[p[i]+'>'+b]);if(OUT[b]||i===p.length-2){out.push({d:d.join(' '),t:t+out.length*TRAVEL,to:b});d=[];}});return out;}
  jobs.forEach(function(x){live[x.id]=1;if(x.settling){delete FLY[x.id];return;}
   var nodes=nodesOf(x),w=FLY[x.id]||(FLY[x.id]={at:nodes,fly:[]}),gone=w.at.filter(function(a){return nodes.indexOf(a)<0;}),come=nodes.filter(function(a){return w.at.indexOf(a)<0;});
   if(gone.length&&!come.length) come=['join'];
   if(gone.length){(come.length>=gone.length?come.map(function(c){return [gone[0],c];}):gone.map(function(a){return [a,come[0]];})).forEach(function(pr){var r=routeOf(pr[0],pr[1]);if(r) w.fly=w.fly.concat(legs(r,now));});}
   w.at=nodes;w.fly=w.fly.filter(function(f){return now<f.t+TRAVEL+PULSE;});w.fly.forEach(function(f){ANIM_UNTIL=Math.max(ANIM_UNTIL,f.t+TRAVEL+PULSE);});});
  Object.keys(FLY).forEach(function(id){if(!live[id]) delete FLY[id];});
  /* states: names only; counts, lists and the lenses' story wait for hover and click */
  ['build','deliver','review_fix'].forEach(function(k){var cur=j.phase===k&&!j.settling;hexPad(g,X[k],Y,10,KC.phase,true,{glow:cur});orbit(g,mine(k),k,X[k],Y,10);name(g,PN[k],X[k],Y+16,{align:'center',size:'.86em',col:hexA(C.ink2,.8)});
   hv(g,'st:'+k,X[k]-34,Y-14,68,48,{t:PN[k],lines:[n(k)+' task'+(n(k)===1?'':'s')+' here now','phase machine · '+(MD[k].nodes.length)+' states']},tasksIn(k,PN[k],'phase machine'));});
  /* while the lenses review, Deliver waits on them: a ring and a pill counting the lenses passed */
  if(j.phase==='qa'&&!j.settling){var np=LENSES.filter(function(l){return j.lenses[l].state==='PASS';}).length;disc(g,X.deliver,Y,14,'border:1.5px solid '+KC.sub);
   span(g,'left:'+(X.deliver+14)+'px;top:'+(Y-27)+'px;width:28px;height:14px;border-radius:7px;background:'+KC.sub);name(g,np+'/5',X.deliver+28,Y-27,{align:'center',size:'.62em',col:C.bg0});}
  LENSES.forEach(function(l){var s=lensState(j,l),col=s&&s.state?VC[s.state]:KC.sub;hexPad(g,650,LYT[l],8,col,true,{glow:s&&s.live});orbit(g,mine(l),l,650,LYT[l],8);
   name(g,LN[l],650,LYT[l]-27,{align:'center',size:'.74em',col:hexA(C.sbHi,.8)});
   hv(g,'st:lens:'+l,620,LYT[l]-28,60,40,{t:LN[l]+' lens',lines:[n(l)+' task'+(n(l)===1?'':'s')+' reviewing','runs alongside the other four']},tasksIn(l,LN[l]+' lens','lens sub-machine'));});
  [[470,Y+34,KC.phase],[650,LYT.simplify+12,KC.sub],[850,Y+34,KC.phase],[975,Y+34,KC.phase]].forEach(function(t){flow(g,'M'+t[0]+','+t[1]+' L'+t[0]+','+(HAIR-3),t[2],.5);
   span(g,'left:'+(t[0]-2.5)+'px;top:'+(HAIR-2.5)+'px;width:5px;height:5px;border-radius:50%;background:'+t[2]);});
  /* the lens stem starts at the Simplify lens; these carry it up through the others, name to sun, so every lens's task leaves on a line */
  LENSES.forEach(function(l,i){if(i<LENSES.length-1) flow(g,'M650,'+(LYT[l]+11)+' L650,'+(LYT[LENSES[i+1]]-29),KC.sub,.5);});
  /* the stems run left along the hairline, through the dots, to the routing lane, then turn down it; where the lens run shares the
     phase run, their dashes alternate */
  line(g,'M975,'+HAIR+' L392,'+HAIR+' Q384,'+HAIR+' 384,'+(HAIR+8),hexA(KC.phase,.5),1.3,{dash:'2 5',st:'animation:sd-march 1.4s linear infinite'});
  line(g,'M650,'+HAIR+' L392,'+HAIR+' Q384,'+HAIR+' 384,'+(HAIR+8),hexA(KC.sub,.6),1.3,{dash:'2 5',st:'animation:sd-march 1.4s linear infinite;animation-delay:-.35s'});
  g.P.lane.push('M262,'+HAIR+' L'+PANE_R+','+HAIR);
  /* a task past every lens waits at the join, and one that left rests under its exit's arrowhead */
  orbit(g,mine('join'),'join',X.join,Y,3);
  Object.keys(OUT).forEach(function(k){orbit(g,mine(k),k,SUN[k].x,SUN[k].y,0);});
  var l0=g.L.length,s0=g.S.length;
  var w=FLY[j.id];if(w) w.fly.forEach(function(f){cometOf(g,f,TASKC[j.tier]||C.ink,now,SUN);});
  g.L.slice(l0).concat(g.S.slice(s0)).forEach(function(p){p.fx=true;});}};
const ROUND_R=60;
/* Round 10: Z1's layout (the In Progress template over one row per machine the pinned task ran, newest first) with the drawing handed to
   a style. The engine places states, sorts each machine's edges into steps, lane changes, loops back and skips ahead, stacks loops and
   skips into levels so none overlap, and sizes every row to hold its levels, so no arc leaves its row. */
const X0=470,X1=1100,HAIR=392,ROWS_END=846;
/* The mockup's pane is 939 wide and 900 tall; the right edge and the replay bar follow the container (setLayout), the rest is mapped by sunsScene. */
const PANE_R=1180;
function hexA(h,a){return 'color-mix(in srgb, '+h+' '+Math.round(a*100)+'%, transparent)';}
function tc(s){return s.replace(/_/g,' ').replace(/\b[a-z]/g,function(c){return c.toUpperCase();});}
/* Rounded flow lines (the rounded variant sets ROUND_R): a polyline's short chamfers fold into their corner, then every corner
   becomes a quarter curve of radius ROUND_R, so octilinear runs and loops read as smooth curves. Curved paths pass through untouched. */
function roundPath(d,R){if(/[^MLml0-9.,\s-]/.test(d)) return d;var out=[];d.split(/(?=M)/).forEach(function(sub){
 var p=(sub.match(/-?[\d.]+/g)||[]).map(Number),q=[];for(var i=0;i+1<p.length;i+=2) q.push({x:p[i],y:p[i+1]});
 function L(a,b){return Math.hypot(b.x-a.x,b.y-a.y);}
 for(var k=1;k+2<q.length;k++){if(L(q[k],q[k+1])<10){var a=q[k-1],b=q[k],c=q[k+1],e=q[k+2],d1x=b.x-a.x,d1y=b.y-a.y,d2x=e.x-c.x,d2y=e.y-c.y,den=d1x*d2y-d1y*d2x;
  if(Math.abs(den)>1e-6){var t=((c.x-a.x)*d2y-(c.y-a.y)*d2x)/den;q.splice(k,2,{x:a.x+t*d1x,y:a.y+t*d1y});k--;}}}
 if(q.length<3){out.push(sub.trim());return;}
 var s='M'+q[0].x.toFixed(1)+','+q[0].y.toFixed(1);
 for(var j=1;j<q.length-1;j++){var A=q[j-1],B=q[j],C=q[j+1],r=Math.min(R,L(A,B)/2,L(B,C)/2),u=r/L(A,B),v=r/L(B,C);
  s+=' L'+(B.x+(A.x-B.x)*u).toFixed(1)+','+(B.y+(A.y-B.y)*u).toFixed(1)+' Q'+B.x.toFixed(1)+','+B.y.toFixed(1)+' '+(B.x+(C.x-B.x)*v).toFixed(1)+','+(B.y+(C.y-B.y)*v).toFixed(1);}
 s+=' L'+q[q.length-1].x.toFixed(1)+','+q[q.length-1].y.toFixed(1);out.push(s);});return out.join(' ');}
function line(g,d,c,w,o){o=o||{};if(typeof ROUND_R!=='undefined'&&!o.sharp&&typeof d==='string') d=roundPath(d,ROUND_R);g.L.push({d:d,c:c,w:w,dash:o.dash||'none',op:o.op==null?1:o.op,st:o.st||'',cap:o.cap||'round'});}
function span(g,st,layer){(layer||g.S).push({style:'position:absolute;'+st});}
function name(g,t,x,y,o){o=o||{};text(g.T,t,o.sub||'',x,y,o.col||hexA(C.ink2,o.ink||.7),{align:o.align,size:o.size||'.84em',ls:o.ls||'.04em',subColor:o.subColor});}
/* A state's name: beside it, over it or under it, brighter on the walked path; a verdict is named only when reached. */
function slabel(g,s,o,R){if(!o.label||(s.q&&!o.on)) return;var col=o.on||o.tpl?hexA(C.ink2,.8):hexA(C.slate,.5),side=o.side||(s.q?'right':(o.above?'top':'bottom')),sz=o.big?'.86em':(s.q?'.66em':'.68em');
 if(side==='right') name(g,o.name,s.x+R+6,s.y-8,{size:sz,col:s.q?hexA(s.c,.9):col});
 else if(side==='topright') name(g,o.name,s.x+R+4,s.y-R-18,{size:sz,col:col});
 else if(side==='top') name(g,o.name,s.x,s.y-R-(o.big?22:18),{align:'center',size:sz,col:col});
 else name(g,o.name,s.x,s.y+R+3,{align:'center',size:sz,col:col});}
/* Delayed disclosure: a hover target shows a short tip; a click opens its details in the side panel. */
function hv(g,key,x,y,w,h,tip,det,pick){g.V.push({aria:tip?tip.t:key,style:'all:unset;position:absolute;cursor:pointer;left:'+x+'px;top:'+y+'px;width:'+w+'px;height:'+h+'px',
 enter:function(){if(g.self.state.hover!==key) g.self.setState({hover:key});},leave:function(){if(g.self.state.hover===key) g.self.setState({hover:null});},
 pick:pick||function(){if(det) g.self.setState({det:g.self.state.det===key?null:key});}});
 if(tip) g.tips[key]={x:tip.x!=null?tip.x:x+w+8,y:tip.y!=null?tip.y:y,t:tip.t,lines:tip.lines};if(det) g.dets[key]=det;}
function P(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}
/* A quadratic from a to b bowed by `bend` (a share of its length), trimmed `ta` and `tb` px off its ends; mid is its halfway point. */
function qcurve(a,b,bend,ta,tb){var dx=b.x-a.x,dy=b.y-a.y,mx=(a.x+b.x)/2-dy*bend,my=(a.y+b.y)/2+dx*bend;
 function trim(p,q,r){var d=Math.hypot(q.x-p.x,q.y-p.y)||1;return {x:p.x+(q.x-p.x)*r/d,y:p.y+(q.y-p.y)*r/d};}
 var p0=trim(a,{x:mx,y:my},ta||0),p1=trim(b,{x:mx,y:my},tb||0);
 return {d:'M'+P(p0)+' Q'+mx.toFixed(1)+','+my.toFixed(1)+' '+P(p1),mid:{x:.25*p0.x+.5*mx+.25*p1.x,y:.25*p0.y+.5*my+.25*p1.y},p0:p0,p1:p1};}
/* A loop or skip held to a band: out of a, along the band `off` px above (-) or below (+) the row line, into b. */
function band(a,b,off,r){var y=a.y+off,s=off<0?-1:1,k=Math.min(10,Math.abs(off)*.6),dir=b.x>a.x?1:-1;
 return {d:'M'+a.x+','+(a.y+s*r)+' L'+a.x+','+(y-s*k)+' Q'+a.x+','+y+' '+(a.x+dir*k)+','+y+' L'+(b.x-dir*k)+','+y+' Q'+b.x+','+y+' '+b.x+','+(y-s*k)+' L'+b.x+','+(b.y+s*r),mid:{x:(a.x+b.x)/2,y:y}};}
/* An octilinear run: level, then a 45 degree diagonal, then level again. */
function octi(a,b,ta,tb,mode){if(Math.abs(a.y-b.y)<.5){var dir=b.x>a.x?1:-1;return {d:'M'+(a.x+dir*ta)+','+a.y+' L'+(b.x-dir*tb)+','+b.y,mid:{x:(a.x+b.x)/2,y:a.y}};}
 var dy=Math.abs(b.y-a.y),dir=b.x>a.x?1:-1;
 if(mode==='early') return {d:'M'+(a.x+dir*ta)+','+a.y+' L'+(a.x+dir*(ta+dy))+','+b.y+' L'+(b.x-dir*tb)+','+b.y,mid:{x:a.x+dir*(ta+dy/2),y:(a.y+b.y)/2}};
 if(mode==='late') return {d:'M'+(a.x+dir*ta)+','+a.y+' L'+(b.x-dir*(tb+dy))+','+a.y+' L'+(b.x-dir*tb)+','+b.y,mid:{x:b.x-dir*(tb+dy/2),y:(a.y+b.y)/2}};
 var xm=(a.x+b.x)/2,h=Math.min(dy,Math.abs(b.x-a.x)-ta-tb)/2;
 return {d:'M'+(a.x+dir*ta)+','+a.y+' L'+(xm-dir*h)+','+a.y+' L'+(xm+dir*h)+','+b.y+' L'+(b.x-dir*tb)+','+b.y,mid:{x:xm,y:(a.y+b.y)/2}};}
/* ---- the machines ---- */
function ch(ns){var e=[];for(var i=1;i<ns.length;i++) e.push([ns[i-1],ns[i]]);return e;}
function def(kind,nodes,extra,o){o=o||{};var pos={};nodes.forEach(function(n,i){pos[n]=(o.pos&&o.pos[n])||{c:i,l:0};});
 return {kind:kind,nodes:nodes,pos:pos,edges:(o.edges||ch(o.main||nodes)).concat(extra||[]),final:o.final||[nodes[nodes.length-1]],x1:o.x1||X1,quiet:o.quiet||[]};}
const MD={
 build:def('phase',['start'].concat(STEPS.build),[['green','red_proven'],['criteria_checked','red_proven'],['worktree_ready','criteria_checked'],['worktree_ready','docs_reconciled']]),
 deliver:def('phase',['start'].concat(STEPS.deliver),[['lint_green','start'],['pushed','committed']]),
 review_fix:def('phase',['start'].concat(STEPS.review_fix),[]),
 lens:def('sub',['reviewing','verdict','PASS','CHANGES'],[['verdict','CHANGES']],{main:['reviewing','verdict','PASS'],final:['PASS','CHANGES'],pos:{PASS:{c:1.2,l:-.5},CHANGES:{c:1.2,l:.5}},quiet:['PASS','CHANGES']}),
 triage:def('sub',['start','audit_active','dismissal_replied','audit_recorded','approval_requested','fix_verified','fix_replied','completed'],[],
  {edges:[['start','audit_active'],['audit_active','dismissal_replied'],['dismissal_replied','audit_active'],['audit_active','audit_recorded'],['audit_recorded','approval_requested'],['start','fix_verified'],['fix_verified','fix_replied'],['fix_replied','start'],['start','completed']],
   pos:{audit_active:{c:1,l:0},dismissal_replied:{c:1.5,l:-1},audit_recorded:{c:2,l:0},approval_requested:{c:3,l:0},completed:{c:3,l:-1},fix_verified:{c:1,l:1},fix_replied:{c:2,l:1}},final:['completed']}),
 dag:def('dag',['queued','running','succeeded','failed'],[['running','failed']],{main:['queued','running','succeeded'],final:['succeeded','failed'],pos:{succeeded:{c:2,l:-.5},failed:{c:2,l:.5}},quiet:['succeeded','failed']})};
function stateCol(d,n,c,mc){if(n==='PASS'||n==='succeeded') return C.ok;if(n==='CHANGES'||n==='failed') return C.fail;return KC[d.kind];}
/* Lay a machine out on its row: positions, edges sorted into kinds, loops and skips stacked into levels, and the room they need. */
function geom(d,M,o){o=o||{};var mc=0,xy={},lane=o.lane||34;d.nodes.forEach(function(n){mc=Math.max(mc,d.pos[n].c);});
 d.nodes.forEach(function(n){var p=d.pos[n];xy[n]={w:(d.x1-X0)/mc,ci:p.c,mc:mc,x1:d.x1,x:X0+p.c*(d.x1-X0)/mc,l:p.l*lane,c:stateCol(d,n),q:d.quiet.indexOf(n)>=0,fin:d.final.indexOf(n)>=0,n:n};});
 var E=d.edges.map(function(e){var A=d.pos[e[0]],B=d.pos[e[1]],dc=B.c-A.c,k=A.l!==B.l?'lane':(dc===1?'step':(dc<0?'back':'skip'));
  return {a:e[0],b:e[1],k:k,side:k==='back'?M.back:(k==='skip'?M.skip:null),lo:Math.min(A.c,B.c),hi:Math.max(A.c,B.c),lv:0};});
 var lv={above:0,below:0};['above','below'].forEach(function(side){var placed=[];
  E.filter(function(e){return e.side===side;}).sort(function(x,y){return (x.hi-x.lo)-(y.hi-y.lo);}).forEach(function(e){
   var L=1;while(placed.some(function(p){return p.lv===L&&p.lo<e.hi&&e.lo<p.hi;})) L++;e.lv=L;placed.push(e);lv[side]=Math.max(lv[side],L);});});
 var minL=0,maxL=0;d.nodes.forEach(function(n){minL=Math.min(minL,xy[n].l);maxL=Math.max(maxL,xy[n].l);});
 var lab=o.labels!==false,top=-minL+(minL<0&&lab?26:12)+(lv.above?M.base+lv.above*M.step:0),bot=maxL+(lab?M.lab:10)+(lv.below?M.base+(M.back==='below'&&lab?0:0)+lv.below*M.step:0);
 return {xy:xy,E:E,top:top,bot:bot,lane:lane,M:M};}
function place(G,y){Object.keys(G.xy).forEach(function(n){G.xy[n].y=y+G.xy[n].l;});}
/* Draw one row through the style: edges, then the walked path over them, then states, then the task. */
function drawRow(g,S,d,G,o){var xy=G.xy,path=o.path||[],tp=Array.isArray(o.trace)?o.trace:path,on={},walked={};tp.forEach(function(n){on[n]=1;});for(var i=1;i<tp.length;i++) walked[tp[i-1]+'>'+tp[i]]=i;
 G.E.forEach(function(e){var a=xy[e.a],b=xy[e.b],w=walked[e.a+'>'+e.b];
  if(e.k==='back'||e.k==='skip') S.loop(g,a,b,(e.side==='above'?-1:1)*(G.M.base+e.lv*G.M.step),{kind:d.kind,k:e.k,on:!!w,G:G});
  else S.edge(g,a,b,{kind:d.kind,k:e.k,on:!!w,num:w&&o.nums?o.nums[w-1]:''});});
 var leg={};G.E.forEach(function(x){if(x.k==='back'||x.k==='skip'){[x.a,x.b].forEach(function(n){(leg[n]=leg[n]||{})[x.side]=1;});}});
 /* the highest loop that runs over each state, per side, so a label can clear it */
 function over(n,side){var c=xy[n].ci,m=0;G.E.forEach(function(x){if(x.side===side&&x.lo<=c&&c<=x.hi) m=Math.max(m,x.lv);});return m;}
 d.nodes.forEach(function(n,i){var s=xy[n];S.state(g,s,{upLv:over(n,'above'),downLv:over(n,'below'),M:G.M,legUp:!!(leg[n]&&leg[n].above),legDown:!!(leg[n]&&leg[n].below),kind:d.kind,on:!!on[n],cur:o.now&&n===path[path.length-1],init:i===0,label:o.labels!==false||s.q,name:s.q?n.toLowerCase():tc(n),above:s.l<0});});
 if(o.now&&path.length){var cur=xy[path[path.length-1]],prev=path.length>1?xy[path[path.length-2]]:{x:cur.x-60,y:cur.y},l0=g.L.length,s0=g.S.length;S.task(g,cur,prev,o.job,{live:o.live,key:o.key,node:path[path.length-1],land:o.land,walk:path.length===2});g.L.slice(l0).concat(g.S.slice(s0)).forEach(function(p){p.fx=true;});}}
function head(g,y,nm,col,s1,s2,s2c){name(g,nm,272,y-14,{col:col,size:'.88em'});if(s1) name(g,s1,272,y+4,{size:'.7em',col:hexA(C.slate,.62)});if(s2) name(g,s2,272,y+18,{size:'.7em',col:s2c||hexA(C.slate,.62)});}
/* ---- the template ---- */
const TY=214,LYT={security:110,ux:162,ui:214,code:266,simplify:318};
function tpl(){var T={build:{x:X0,y:TY,n:'Build'},fork:{x:548,y:TY,n:'',dot:1},join:{x:752,y:TY,n:'',dot:1},deliver:{x:850,y:TY,n:'Deliver'},review_fix:{x:975,y:TY,n:'Review Fix'},
 review_recorded:{x:1100,y:TY,n:'Review Recorded',fin:1},parked:{x:850,y:112,n:'Parked',fin:1,exit:1},needs_attention:{x:975,y:112,n:'Needs Attention',fin:1,exit:1},finalized:{x:975,y:316,n:'Finalized',fin:1,exit:1}};
 LENSES.forEach(function(l){T[l]={x:650,y:LYT[l],n:LN[l]+' Lens',lens:1};});Object.keys(T).forEach(function(k){T[k].c=T[k].lens||T[k].dot?KC.sub:(T[k].exit?C.review:KC.tpl);T[k].k=k;});return T;}
function template(g,S,jobs,j){if(S.template) return S.template(g,jobs,j);var T=tpl(),ed=function(a,b,o){S.edge(g,T[a],T[b],Object.assign({kind:'tpl',k:'step'},o||{}));};
 ed('build','fork');LENSES.forEach(function(l){ed('fork',l,{k:'lane'});ed(l,'join',{k:'lane'});});ed('join','deliver');ed('deliver','review_fix');ed('review_fix','review_recorded');
 ['build','deliver','review_fix'].forEach(function(k){ed(k,'parked',{k:'exit'});});ed('deliver','needs_attention',{k:'exit'});ed('deliver','finalized',{k:'exit'});
 S.loop(g,T.review_fix,T.deliver,-(S.M.base+S.M.step),{kind:'tpl',k:'back',label:'Lint Green'});
 S.loop(g,T.join,T.build,LYT.simplify-TY+30,{kind:'tpl',k:'back',label:'Changes'});
 Object.keys(T).forEach(function(k){var s=T[k];if(s.dot){S.state(g,s,{kind:'sub',dot:true});return;}
  var ls=s.lens?lensState(j,s.k):null;if(ls&&ls.state) s.c=VC[ls.state];
  S.state(g,s,{kind:s.lens?'sub':'tpl',on:true,big:true,label:true,name:s.n,init:k==='build',side:s.lens||k==='finalized'?'right':(s.exit||k==='review_recorded'?'top':'bottom'),cur:ls&&ls.live,tpl:true});});
 name(g,'four lenses at once',T.fork.x+52,84,{align:'center',size:'.66em',col:hexA(C.slate,.55)});
 var at={};jobs.forEach(function(x){if(x.phase==='qa'){LENSES.forEach(function(l){if(x.lenses[l].state==='pending') (at[l]=at[l]||[]).push(x);});return;}var p=x.phase==='done'?'review_recorded':x.phase;(at[p]=at[p]||[]).push(x);});
 Object.keys(at).forEach(function(k){if(T[k]) S.crowd(g,T[k],at[k],j.id);});
 g.P.lane.push('M262,'+HAIR+' L'+PANE_R+','+HAIR);
 [X0,650,850,975,1100].forEach(function(x){g.P.guide.push('M'+x+','+(HAIR+6)+' L'+x+','+ROWS_END);});}
/* The rows: one per machine, in the template's order, never one per run. A machine the task ran more than once keeps one row, and its
   rounds are pills under its name: the selected round's path is drawn (the newest by default) and a lens's pills carry its verdict. The
   machine the task is in now is open; the rest fold to a small, unlabelled copy of their graph. Click a name to open or fold a row. */
function rows(g,S,j,top){var Y=HAIR+4,stop=false,open=g.open||{},pick=g.pick||{},qa=[],bl=[],dl=[],rf=[];
 /* a task newly picked, a scrub entered or left, or its history landing, only rests; any other change is a real move */
 var shown=j.id+(g.self.state.at!=null?'@':'')+(j.settling?'~':'');PICKED=LAST_ROWS!==shown;LAST_ROWS=shown;
 j.trail.forEach(function(t,i){var e={t:t,i:i,now:i===j.trail.length-1&&j.phase===t.phase};({qa:qa,build:bl,deliver:dl,review_fix:rf}[t.phase]||[]).push(e);});

 function sep(x){g.P.lane.push('M'+(x||262)+','+Y+' L'+PANE_R+','+Y);}
 function toggle(k,v){return function(){var o=Object.assign({},g.self.state.open||{});o[k]=v;g.self.setState({open:o});};}
 function choose(k,v){return function(){var o=Object.assign({},g.self.state.pick||{});o[k]=v;g.self.setState({pick:o});};}
 /* rounds as pills: r1 r2 r3, the selected one lit; `vc` colours a lens round by its verdict. Three fit left of the rail, so with more the
    first says how many older rounds are held back and steps to the one before; the selected round and the one after it follow. */
 function pills(k,ents,sel,y,vc){var from=ents.length>3?Math.min(sel,ents.length-2):0,x=272;
  function pill(text,aria,n,c,on){g.Q.push({text:text,aria:aria,pick:choose(k,n),style:'all:unset;cursor:pointer;position:absolute;left:'+x+'px;top:'+y+'px;height:14px;padding:0 6px;border-radius:7px;font-size:10px;line-height:13px;box-sizing:border-box;'+
   'color:'+(on?C.bg0:hexA(c,.9))+';background:'+(on?c:'transparent')+';border:1px solid '+hexA(c,on?1:.45)});x+=34;}
  if(from) pill('\u2039'+from,k+' '+from+' older rounds',from-1,KC.phase,false);
  ents.slice(from,from+(from?2:3)).forEach(function(e,i){pill('r'+e.t.round+(e.now?' •':''),k+' round '+e.t.round,from+i,vc?vc(e):KC.phase,from+i===sel);});}
 /* one machine row: open (full graph, names) or folded (small graph); `paths(e)` says what a round walked */
 function row(k,label,col,d,ents,paths,o){if(stop||!ents.length) return;o=o||{};var sel=pick[k]!=null&&pick[k]<ents.length?pick[k]:ents.length-1,e=ents[sel],isOpen=typeof COMPACT_ALL!=='undefined'?false:open[k]!=null?open[k]:!!o.active;
  var MI=S.MINI||{base:7,step:3,lane:.3,minH:38,pad:8},path=paths(e),M=isOpen?S.M:{base:MI.base,step:MI.step,back:S.M.back,skip:S.M.skip,lab:6},G=geom(d,M,{labels:isOpen&&o.labels!==false,lane:isOpen?(o.lane||34):(o.lane||34)*MI.lane});
  var h=Math.max(isOpen?66:MI.minH,G.top+G.bot+(isOpen?18:2*MI.pad)),y0=Y;
  var y=Y+G.top+(isOpen?10:MI.pad);if(!isOpen) Object.keys(G.xy).forEach(function(n){G.xy[n].mini=true;});place(G,y);
  /* the backtrace is drawn on hover or once picked: over the row, or over the task where it is now */
  var hk=g.self.state.hover,dk=g.self.state.det,live=e.now&&(o.isLive?o.isLive(e):true),rk=function(x){return x==='row:'+k||x==='row:'+k+':g';},lit=typeof TRACE_ALL!=='undefined'||rk(hk)||rk(dk)||(live&&(hk==='task'||dk==='task'));
  if(o.stem!=null){var f=G.xy[d.nodes[0]],sx=o.stem;var lx=384;
   /* every stem reaches the routing lane along the hairline (the template draws that run, through the stems' dots); here it runs down
      the lane beside the round pills, then into the row */
   /* phase and lens stems share one track; a lens stem's dashes sit in the phase stem's gaps */
   line(g,'M'+lx+','+(HAIR+8)+' L'+lx+','+f.y+' L'+(f.x-(isOpen?11:6))+','+f.y,hexA(KC[d.kind],isOpen?.55:.3),1.3,{dash:'2 5',st:'animation:sd-march 1.4s linear infinite'+(d.kind==='phase'?'':';animation-delay:-.35s')});}
  /* a task newly live in this row was sent here: it leaves its state once any flight landing there is over; a newly picked task, a scrub, or a
     round pill read back only rests */
  var land=0;if(o.stem!=null&&sel===ents.length-1){var sk=j.id+'|'+k,was=SENT[sk],now=Date.now(),fired=was?was.fly:0;
   if(live&&(!was||!was.live||was.i!==e.i)&&!PICKED&&!j.settling&&(g.self.state.at==null||g.self.state.replaying)){fired=now;((FLY[j.id]||{}).fly||[]).forEach(function(x){if(x.to===o.sun) fired=Math.max(fired,x.t+TRAVEL);});delete MOVES[j.id+'|'+k];}
   SENT[sk]={live:live,i:e.i,fly:fired};
   if(fired&&now<fired+DROP){ANIM_UNTIL=Math.max(ANIM_UNTIL,fired+DROP);land=fired+DROP;
    dropOf(g,top,'M'+o.stem+','+o.from+' L'+o.stem+','+HAIR+' L392,'+HAIR+' Q384,'+HAIR+' 384,'+(HAIR+8),roundPath('M384,'+(HAIR+8)+' L384,'+f.y+' L'+(f.x-(isOpen?11:6))+','+f.y,ROUND_R),TASKC[j.tier]||C.ink,fired,now);}}
  drawRow(g,S,d,G,{path:path,trace:lit?path:path.slice(-1),labels:isOpen&&o.labels!==false,now:live,live:true,job:j,key:k,land:land});
  var ty=isOpen?y-16:Y+h/2-17,info=o.info?o.info(e):'';name(g,label,272,ty,{col:hexA(col,isOpen?1:.8),size:'.82em'});
  var hasPills=ents.length>1||o.pillsAlways,cy=hasPills?ty+9:ty;if(hasPills) pills(k,ents,sel,ty+18,o.vc);
  var tip={t:label+' · round '+e.t.round,lines:[info],x:272,y:y0+h+2},det={title:label,sub:'round '+e.t.round+' of '+ents.length+(e.now?' · running now':''),
   rows:[{k:'status',v:info,c:o.vc?o.vc(e):''},{k:'walked',v:path.map(tc).join(' → ')}].concat(o.more?o.more(e):[])};
  hv(g,'row:'+k,272,ty-2,180,16,tip,det);hv(g,'row:'+k+':g',460,y0+2,PANE_R-460,h-4,null,det);
  if(live&&path.length){var c=G.xy[path[path.length-1]],at=tc(path[path.length-1]),tr=isOpen?12:9;
   hv(g,'task',c.x-tr,c.y-tr,2*tr,2*tr,{t:j.id,lines:['at '+at+' · '+j.mins+' min']},{title:j.id,sub:j.title,rows:[{k:'tier',v:j.tier,c:TIER[j.tier]},{k:'machine',v:label},{k:'state',v:at},{k:'round',v:j.round+' of '+j.limit},{k:'in state',v:j.mins+' min'},{k:'spec',v:j.spec}]});}
  if(typeof COMPACT_ALL==='undefined'){g.H.push({aria:(isOpen?'Fold ':'Open ')+label,pick:toggle(k,!isOpen),style:'all:unset;position:absolute;cursor:pointer;left:254px;top:'+(cy-1)+'px;width:16px;height:16px'});
   text(g.T,isOpen?'▾':'▸','',258,cy+1,hexA(C.slate,.55),{size:'.7em'});}Y+=h;if(typeof NO_SEPS==='undefined') sep(o.inner?470:262);else if(!o.inner) sep(262);}
 function phasePath(p){return function(e){var n=MD[p].nodes;return e.now?n.slice(0,j.step+2):n;};}
 function doneSub(p){return function(e){return e.now?'at '+tc(MD[p].nodes[j.step+1])+' · '+j.mins+' min':'done in '+e.t.mins+' min';};}
 row('build','Build',KT.phase,MD.build,bl,phasePath('build'),{stem:470,sun:'build',from:TY+34,active:j.phase==='build',info:doneSub('build')});
 if(qa.length&&!stop){var y0=Y;LENSES.forEach(function(l,li){
   function v(e){return e.now?lensState(j,l):(e.t.v?{state:e.t.v[l]}:null);}
   function why(e){return e.t.why&&e.t.why.indexOf(LN[l]+':')===0?e.t.why.slice(LN[l].length+2):'';}
   var ST=LSTEPS;
   row('lens:'+l,LN[l]+' lens',KT.sub,MD.lens,qa,function(e){var s=v(e);return s&&s.state?ST.concat(s.state):(s&&s.live?ST.slice(0,s.at+1):[]);},
    {stem:650,sun:l,from:LYT[l]+11,active:j.phase==='qa',lane:24,lens:true,last:li===LENSES.length-1,labels:li===0,isLive:function(e){var s=v(e);return !!(s&&s.live);},inner:li<LENSES.length-1,pillsAlways:true,vc:function(e){var s=v(e);return s&&s.state?VC[s.state]:KC.sub;},
     info:function(e){var s=v(e);return s&&s.state?(s.state==='PASS'?'passed':'asked for changes'):(s&&s.live?'reviewing now':'waiting to start');},
     more:function(e){var w=why(e);return w?[{k:'why',v:w,c:VC.CHANGES}]:[];}});});
  }
 if(dl.length&&!stop){var y1=Y,de=dl[dl.length-1],ip=de.now&&j.step<5,run=de.now&&j.step===4,act=j.phase==='deliver';
  row('deliver','Deliver',KT.phase,MD.deliver,dl,phasePath('deliver'),{stem:850,sun:'deliver',from:TY+34,active:act,info:doneSub('deliver'),inner:true});
  if(!de.now||j.step>=3) row('triage','Review triage',KT.sub,MD.triage,dl,function(e){return e.now&&ip?['start','audit_active']:['start','audit_active','audit_recorded','approval_requested'];},{stem:850,sun:'deliver',from:TY+34,active:act,lane:30,inner:true,isLive:function(e){return e.now&&ip;},info:function(e){return e.now&&ip?'auditing while the PR is open':'approval requested';}});
  if(!de.now||j.step>=4) row('dag','ci-validate',KT.dag,MD.dag,dl,function(e){return e.now&&run?['queued','running']:['queued','running','succeeded'];},{stem:850,sun:'deliver',from:TY+34,active:act,lane:22,labels:false,isLive:function(e){return e.now&&run;},info:function(e){return 'DAG · '+(e.now&&run?'running':'passed');}});
  }
 row('review_fix','Review fix',KT.phase,MD.review_fix,rf,phasePath('review_fix'),{stem:975,sun:'review_fix',from:TY+34,active:j.phase==='review_fix',info:doneSub('review_fix')});
 var last=j.trail[j.trail.length-1];if(!stop&&(last.phase==='parked'||last.phase==='done')){var pk=last.phase==='parked',to=pk?'Needs Attention':'Review';
  name(g,'→ '+to,272,Y+10,{size:'.8em',col:pk?C.failText:C.okHi});
  if(pk&&last.round>=3) name(g,'round '+last.round+' of 3 failed · approve more rounds, or merge as is',272,Y+28,{size:'.74em',col:C.failText});
  hv(g,'left',268,Y+8,130,18,{t:'Left In Progress',lines:[pk?(last.why||'').split(':')[0]||'deferred':'review recorded']},{title:'Left In Progress',sub:'to '+to,rows:[{k:'why',v:last.why||(pk?'deferred':'review recorded'),c:pk?C.failText:C.okHi},{k:'round',v:String(last.round)}]});}
 return Y;}
/* ---- replay ---- */
/* A replay bar under the rows, for the pinned task only (one task's 24h is ~120 events, so the client folds it in ~1-2 ms). The axis spans
   the task's history up to 24h, with a tick per machine entry. Hover anywhere on the bar for the time and where the task was; click to
   put the playhead there, and the template and rows show the task as it was. ▶ plays forward from the playhead; Live returns to now. */
var NOW_M=5*60+30;
const SX0=330;let SX1=1176,SY=866;
function setLayout(w,h){SX1=1176+w-939;SY=866+h-900;}
function hhmm(ago){var m=((NOW_M-Math.round(ago))%1440+1440)%1440;return ('0'+Math.floor(m/60)).slice(-2)+':'+('0'+(m%60)).slice(-2);}
function entriesOf(x){var out=[],ago=x.mins;for(var i=x.trail.length-1;i>=0;i--){var t=x.trail[i];if(i<x.trail.length-1) ago+=t.mins||0;
  if(t.phase!=='parked'&&t.phase!=='done') out.unshift({t:t,i:i,ago:ago,dur:i===x.trail.length-1?x.mins:(t.mins||0)});}
 var n={};out.forEach(function(e){n[e.t.phase]=n[e.t.phase]||0;e.k=n[e.t.phase]++;});return out;}
function spanOf(j){var es=entriesOf(j);return Math.min(1440,(es.length?es[0].ago:10)*1.06+2);}
/* The task as it was `ago` minutes back: its trail cut at that moment, the step inside the machine it was in, and its lenses so far. */
function jobAt(j,ago){if(ago==null||ago<.5) return j;var es=entriesOf(j),e=null;es.forEach(function(x){if(x.ago>=ago) e=x;});if(!e) e=es[0];if(!e) return j;
 var r=Object.assign({},j),frac=Math.max(0,Math.min(1,(e.ago-ago)/Math.max(e.dur,1))),n=(STEPS[e.t.phase]||['x']).length;
 r.trail=j.trail.slice(0,e.i+1);r.phase=e.t.phase;r.round=e.t.round;r.mins=Math.max(0,Math.round(e.ago-ago));r.step=Math.min(n-1,Math.floor(frac*n));
 if(e.t.phase==='qa'){var cur=e.i===j.trail.length-1;r.lenses={};LENSES.forEach(function(l,li){var v=cur?(j.lenses[l]&&j.lenses[l].state!=='pending'?j.lenses[l].state:null):(e.t.v?e.t.v[l]:null);
  r.lenses[l]=v&&frac>=.55+li*.1?L(v):L(null,Math.floor(frac*2));});}
 return r;}
function replay(g,j,at,playing){var tw=spanOf(j),es=entriesOf(j);function xOf(ago){return SX1-(ago/tw)*(SX1-SX0);}
 g.P.lane.push('M'+SX0+','+SY+' L'+SX1+','+SY);
 name(g,hhmm(tw),SX0,SY+6,{size:'.6em',col:hexA(C.slate,.45)});name(g,'now',SX1,SY+6,{align:'center',size:'.6em',col:hexA(C.slate,.45)});
 es.forEach(function(e){var x=xOf(e.ago),past=at!=null&&e.ago<at;span(g,'left:'+(x-1)+'px;top:'+(SY-8)+'px;width:2px;height:8px;border-radius:1px;background:'+hexA(e.t.phase==='qa'?KC.sub:KC.phase,past?.3:.95));});
 var px=xOf(at==null?0:at);
 if(at!=null){span(g,'left:'+px+'px;top:'+(SY-1)+'px;width:'+(SX1-px)+'px;height:2px;background:'+hexA(C.slate,.12));
  span(g,'left:'+(px-1)+'px;top:'+(SY-20)+'px;width:2px;height:24px;background:'+C.ink+';box-shadow:0 0 6px '+C.ink);name(g,hhmm(at),px,SY-36,{align:'center',size:'.66em',col:C.ink});}
 else span(g,'left:'+(px-3.5)+'px;top:'+(SY-3.5)+'px;width:7px;height:7px;border-radius:50%;background:'+C.ok+';box-shadow:0 0 6px '+C.ok);
 /* scrub targets: hover for the time and where the task was, click to move the playhead there */
 var N=96,w=(SX1-SX0)/N;for(var i=0;i<N;i++){(function(i){var ago=tw*(1-(i+.5)/N),r=jobAt(j,ago),ph=r.phase==='qa'?'QA lenses':(PN[r.phase]||r.phase);
  hv(g,'scrub:'+i,SX0+i*w,SY-22,w,30,{t:hhmm(ago),lines:[ph+' · r'+r.round],x:Math.max(SX0,SX0+i*w-40),y:SY-74},null,function(){g.self.setState({at:ago,det:null});});})(i);}
 g.H.push({aria:playing?'Pause replay':'Play replay',pick:function(){var st=g.self.state;g.self.setState({replaying:!playing,at:st.at==null?tw:st.at});},
  style:'all:unset;cursor:pointer;position:absolute;left:272px;top:'+(SY-9)+'px;width:18px;height:18px'});
 text(g.T,playing?'❚❚':'▶','',275,SY-8,playing?C.ink:hexA(C.ink2,.8),{size:'.72em'});
 if(at!=null){g.H.push({aria:'Back to live',pick:function(){g.self.setState({at:null,replaying:false});},style:'all:unset;cursor:pointer;position:absolute;left:294px;top:'+(SY-9)+'px;width:30px;height:18px'});
  text(g.T,'Live','',297,SY-8,C.okHi,{size:'.7em'});}}
/** Pins the clock the scrubber labels count back from, in local minutes past midnight. */
function setNowMinutes(m){NOW_M=m;}
export { LENSES, LN, PN, STEPS, TIER, TASKC, ROWS_END, statusOf, starfield, STYLE, PANE_R, HAIR, setLayout, ANIM_UNTIL, template, rows, hhmm, spanOf, jobAt, replay, setNowMinutes };
