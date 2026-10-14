const vm=require('vm'),fs=require('fs'),assert=require('assert'),path=require('path');
const ctx={window:{},Float32Array,console,Date};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../aether/gui/static/gl.js'),'utf8'),ctx);
const groups=ctx.buildEdgeGroups([0,1,0,1,2,0,2,3,0,3,0,0,4,5,0],[0,0,0,1,0,0,1,1,0,0,1,0,3,0,0,4,0,0]);
assert.equal(groups.length,5);assert(groups.every(g=>g.length===1 && g.segments.length===1));
const v=Object.create(ctx.window.Viewport.prototype);v.gl={deleteBuffer(){}};v._buf=x=>x;
v.bbox=[[0,0,0],[1,1,1]];v._rebuildGrid();const before=Array.from(v.grid.b);
v.bbox=[[4,6,8],[5,7,9]];v._rebuildGrid();assert.deepEqual(Array.from(v.grid.b),before);
assert(before.every((x,i)=>i%3!==2||x===0));
// Only camera orientation reaches the screen corner triad.
v.canvas={parentElement:{appendChild(){}}};ctx.document={createElementNS:()=>({style:{},setAttribute(){}})};
v._camera=()=>({eye:[1,2,3],ctr:[0,0,0],up:[0,0,1]});v._drawTriad(1000,800);const initial=v.triad.innerHTML;
v._camera=()=>({eye:[11,22,33],ctr:[10,20,30],up:[0,0,1]});v._drawTriad(1000,800);
assert.equal(v.triad.innerHTML,initial);for(const label of ['X','Y','Z'])assert(initial.includes('>'+label+'</text>'));
assert(initial.includes('<path'));
console.log('world frame, closed outlines and labelled triad passed');
