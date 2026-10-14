const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const ctx={window:{},Float32Array,console};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../aether/gui/static/gl.js'),'utf8'),ctx);
// Several mesh segments between two actual corners stay one selectable edge.
let g=ctx.buildEdgeGroups([0,1,0,1,2,0,2,3,0],[0,0,0,.5,0,0,1,0,0,1,1,0]);
assert.equal(g.length,2);assert.equal(g[0].length,1);assert.equal(g[0].segments.length,2);
assert.equal(JSON.stringify(ctx.edgeEndpoints(g[0].segments)),JSON.stringify([[0,0,0],[1,0,0]]));
const p=[];for(let x=0;x<150;x++)for(let y=0;y<150;y++)p.push(x,y,0,x+.8,y,0,x,y+.8,0);
const start=performance.now(),tree=ctx.buildPickTree(p),buildMs=performance.now()-start;
const candidates=[...ctx.pickCandidates(tree,[25.1,30.1,5],[0,0,-1],p.length)];assert(candidates.length<100);assert(candidates.includes((25*150+30)*9));
// Identical nearest hit with / without the BVH for hits, misses and grazing rays.
const v=Object.create(ctx.window.Viewport.prototype);const o={name:'grid',cpu:new Float32Array(p),faces:[],pickTree:tree};v.objects=[o];
for(const origin of [[25.1,30.1,5],[-2,-2,1],[0,0,1],[149.2,149.2,1],[25.9,30.9,1]]){
 v.ray=()=>({origin,dir:[0,0,-1]});o.pickTree=tree;const a=v.pick(0,0);o.pickTree=null;const b=v.pick(0,0);assert.equal(JSON.stringify(a),JSON.stringify(b));
}
console.log(JSON.stringify({triangles:p.length/9,candidates:candidates.length,buildMs,verified:'same nearest hits as exhaustive search'}));
