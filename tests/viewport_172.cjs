// Pure event/geometry tests with stub buffers, not an actual browser render.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ctx={window:{},Float32Array,Uint32Array,Uint16Array,console,Date};
vm.runInNewContext(fs.readFileSync(require('path').join(__dirname,'../aether/gui/static/gl.js'),'utf8'),ctx);
const v=Object.create(ctx.window.Viewport.prototype),events={};
v.canvas={style:{},addEventListener:(k,f)=>events[k]=f,getBoundingClientRect:()=>({left:0,top:0}),setPointerCapture:()=>{}};
v.dist=10;v.yaw=0;v.pitch=0;v.pan=[0,0];v.objects=[];v.gl={deleteBuffer:()=>{}};v._buf=x=>x;v.setHover=()=>{};
v.pick=()=>({name:'Box'});v.pickFeature=v.pick;
let picks=0,doubles=0;v.onPick=()=>picks++;v.onDoublePick=()=>doubles++;
v._bindInput();
const e=(x=10)=>({button:0,clientX:x,clientY:10,pointerId:1,preventDefault(){}});
events.pointerdown(e());events.pointermove(e(12));assert.equal(v.yaw,0);
events.pointercancel(e());events.pointerup(e());assert.equal(picks,0);
events.pointerdown(e());events.pointerup(e());assert.equal(picks,1);
events.dblclick(e());assert.equal(doubles,1);
v.onPickAt=()=>true;events.pointerdown(e());events.pointerup(e());events.dblclick(e());assert.equal(doubles,1);
v.setDraft([[0,0,0],[1,0,0]]);v.setMeasure([[0,0,0],[1,0,0]]); // Former undefined proj/view crash.
delete v.pickFeature;
v.project=p=>({x:p[0],y:p[1]});v.ray=()=>({origin:[0,0,0]});v.pick=()=>null;
v.objects=[{name:'A',snapPoints:[[20,20,1]],evCpu:new Float32Array([10,10,1,30,10,1]),faceEdges:[0,1,0]}];
assert.equal(v.pickFeature(22,20,'point').name,'A');assert.equal(v.pickFeature(50,50,'point'),null);
assert.equal(v.pickFeature(20,12,'edge').edge.length,20);
v.objects[0].visible=false;assert.equal(v.pickFeature(20,20,'point'),null);
v.objects[0].visible=true;v.pick=()=>({name:'Front',distance:1});assert.equal(v.pickFeature(20,20,'point'),null);
console.log('viewport event and snap regressions passed');
