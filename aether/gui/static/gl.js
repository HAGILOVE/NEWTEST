/* Aether Desktop — 3-D modeller viewport.
 *
 * A self-contained WebGL renderer. No CDN, no library: the workspace has to
 * run on an air-gapped engineering workstation, so every line it needs ships
 * with it. It draws shaded solids with per-object transparency, a wireframe
 * overlay, a scalar field colour map, the ground grid and the orientation
 * triad, and it handles arcball rotate / pan / zoom.
 */
'use strict';

/* ------------------------------------------------------------- mat4/vec3 */
const M4 = {
  ident: () => new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]),
  mul(a, b) {
    const o = new Float32Array(16);
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k];
      o[i * 4 + j] = s;
    }
    return o;
  },
  perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([f / aspect,0,0,0, 0,f,0,0,
      0,0,(far + near) * nf,-1, 0,0,2 * far * near * nf,0]);
  },
  lookAt(eye, ctr, up) {
    const z = V3.norm(V3.sub(eye, ctr));
    const x = V3.norm(V3.cross(up, z));
    const y = V3.cross(z, x);
    return new Float32Array([
      x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0,
      -V3.dot(x,eye), -V3.dot(y,eye), -V3.dot(z,eye), 1]);
  },
  invTranspose3(m) {
    // inverse-transpose of the upper 3x3, for normals
    const a=m[0],b=m[1],c=m[2],d=m[4],e=m[5],f=m[6],g=m[8],h=m[9],i=m[10];
    const A=e*i-f*h, B=-(d*i-f*g), C=d*h-e*g;
    let det = a*A + b*B + c*C;
    if (!det) det = 1;
    const id = 1/det;
    return new Float32Array([
      A*id, B*id, C*id,
      (-(b*i-c*h))*id, (a*i-c*g)*id, (-(a*h-b*g))*id,
      (b*f-c*e)*id, (-(a*f-c*d))*id, (a*e-b*d)*id]);
  }
};
const V3 = {
  sub: (a,b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]],
  add: (a,b) => [a[0]+b[0], a[1]+b[1], a[2]+b[2]],
  scale: (a,s) => [a[0]*s, a[1]*s, a[2]*s],
  dot: (a,b) => a[0]*b[0]+a[1]*b[1]+a[2]*b[2],
  cross: (a,b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]],
  len: a => Math.hypot(a[0],a[1],a[2]),
  norm(a) { const l = V3.len(a) || 1; return [a[0]/l, a[1]/l, a[2]/l]; }
};

/* ------------------------------------------------------------- shaders */
const VS_SOLID = `
attribute vec3 aPos; attribute vec3 aNrm; attribute float aScalar;
attribute float aHi;
uniform mat4 uProj, uView; uniform mat3 uNormal;
varying vec3 vN; varying vec3 vP; varying float vS; varying float vH;
void main(){ vN = normalize(uNormal * aNrm); vP = aPos; vS = aScalar;
  vH = aHi;
  gl_Position = uProj * uView * vec4(aPos, 1.0); }`;

const FS_SOLID = `
precision highp float;
varying vec3 vN; varying vec3 vP; varying float vS; varying float vH;
uniform vec3 uColor; uniform float uAlpha; uniform float uSelected;
uniform float uUseScalar; uniform vec3 uEye;
vec3 turbo(float t){
  t = clamp(t, 0.0, 1.0);
  vec3 c = vec3(0.0);
  c.r = smoothstep(0.35, 0.65, t) + 0.7*smoothstep(0.85, 1.0, t);
  c.g = smoothstep(0.0, 0.45, t) - smoothstep(0.65, 1.0, t) * 0.85;
  c.b = 1.0 - smoothstep(0.1, 0.55, t) + 0.25*smoothstep(0.9, 1.0, t);
  return clamp(c, 0.0, 1.0);
}
void main(){
  vec3 base = mix(uColor, turbo(vS), uUseScalar);
  vec3 N = normalize(vN);
  vec3 V = normalize(uEye - vP);
  if (dot(N, V) < 0.0) N = -N;                 /* two-sided lighting */
  vec3 L1 = normalize(vec3(0.45, 0.35, 0.82));
  vec3 L2 = normalize(vec3(-0.6, -0.45, 0.35));
  float d = 0.72*max(dot(N,L1),0.0) + 0.28*max(dot(N,L2),0.0);
  vec3 H = normalize(L1 + V);
  float spec = pow(max(dot(N,H),0.0), 42.0) * 0.30;
  vec3 col = base * (0.30 + 0.78*d) + vec3(spec);
  col = mix(col, vec3(1.0, 0.86, 0.35), uSelected*0.32);
  /* a picked face is highlighted on its own, without the whole body */
  col = mix(col, vec3(0.24, 0.72, 1.0), clamp(vH, 0.0, 1.0) * 0.62);
  gl_FragColor = vec4(col, uAlpha + clamp(vH,0.0,1.0) * (1.0 - uAlpha) * 0.75);
}`;

const VS_LINE = `
attribute vec3 aPos; uniform mat4 uProj, uView;
void main(){ gl_Position = uProj * uView * vec4(aPos, 1.0);
  gl_Position.z -= 0.00025 * gl_Position.w; }`;
const FS_LINE = `
precision mediump float; uniform vec4 uColor;
void main(){ gl_FragColor = uColor; }`;

/* ------------------------------------------------------------- renderer */
/* A line a -> b with an arrow head at b: the shaft and two barbs, as three
   GL_LINES segments. The head points from ground to signal on a port. */
function arrowSegments(a, b) {
  const d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const L = Math.hypot(d[0], d[1], d[2]) || 1;
  const u = d.map(v => v / L);
  const ax = [Math.abs(u[0]), Math.abs(u[1]), Math.abs(u[2])];
  const r = ax[0] <= ax[1] && ax[0] <= ax[2] ? [1, 0, 0] : ax[1] <= ax[2] ? [0, 1, 0] : [0, 0, 1];
  let s = [u[1] * r[2] - u[2] * r[1], u[2] * r[0] - u[0] * r[2], u[0] * r[1] - u[1] * r[0]];
  const sl = Math.hypot(...s) || 1; s = s.map(v => v / sl);
  const h = 0.28 * L, w = 0.12 * L;
  const back = [b[0] - u[0] * h, b[1] - u[1] * h, b[2] - u[2] * h];
  return new Float32Array([...a, ...b,
    ...b, back[0] + s[0] * w, back[1] + s[1] * w, back[2] + s[2] * w,
    ...b, back[0] - s[0] * w, back[1] - s[1] * w, back[2] - s[2] * w]);
}

class Viewport {
  constructor(canvas) {
    this.canvas = canvas;
    const gl = this.gl = canvas.getContext('webgl', {
      antialias: true, alpha: false, preserveDrawingBuffer: true });
    if (!gl) throw new Error('WebGL is not available in this browser');
    this.progSolid = this._program(VS_SOLID, FS_SOLID);
    this.progLine = this._program(VS_LINE, FS_LINE);
    this.objects = [];
    this.wire = null;
    this.selection = new Set();
    this.assign = [];
    this.showAssignments = true;
    // the radiation box wraps the whole model and hides fields and patterns
    // drawn inside it; it is available on request, not by default
    this.showRadiation = false;
    this.opaque = false;
    this.solidParts = false;          // parts opaque, regions (air, vacuum) left see-through
    this.userAlpha = new Set();       // objects whose transparency the user set by hand
    this.mode = 'shaded';          // shaded | wireframe | shadedEdges
    this.showGrid = true;
    this.showTriad = true;
    this.bbox = [[-1,-1,-1],[1,1,1]];
    this.center = [0,0,0];
    this.dist = 4;
    this.yaw = -0.72; this.pitch = 0.52;
    this.pan = [0,0];
    this.hover = null;
    this._rebuildGrid();
    this.gridStep=null; // first actual model sets the fixed world-grid spacing
    this._bindInput();
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }

  _program(vsrc, fsrc) {
    const gl = this.gl;
    const mk = (t, s) => {
      const sh = gl.createShader(t);
      gl.shaderSource(sh, s); gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS))
        throw new Error(gl.getShaderInfoLog(sh));
      return sh;
    };
    const p = gl.createProgram();
    gl.attachShader(p, mk(gl.VERTEX_SHADER, vsrc));
    gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fsrc));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS))
      throw new Error(gl.getProgramInfoLog(p));
    return p;
  }

  _buf(data, type) {
    const gl = this.gl;
    const b = gl.createBuffer();
    gl.bindBuffer(type || gl.ARRAY_BUFFER, b);
    gl.bufferData(type || gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    return b;
  }

  /* ---------------------------------------------------------- geometry */
  /* Rebuild only what actually changed.
     Uploading a body to the GPU is the cheap half; indexing it for picking
     (the BVH) and tracing its face outlines are not, and the viewport is
     rebuilt after every single edit. The server marks each object with a
     digest of its geometry and returns `unchanged: true` for the ones that
     still match, so moving one box in a twenty-body model now rebuilds one
     box instead of twenty. Everything else about an object -- colour,
     transparency, visibility -- is cheap and always applied. */
  setObjects(list, bbox) {
    const gl = this.gl;
    this.setHover(null); this.setPointSelection([]);
    const previous = new Map();
    for (const o of this.objects) previous.set(o.name, o);
    const next = [];
    for (const o of (list || [])) {
      const old = previous.get(o.name);
      if (o.unchanged && old) {
        this._applyDisplay(old, o);
        next.push(old);
      } else {
        next.push(this._buildObject(o));
      }
    }
    const live = new Set(next);
    for (const o of this.objects) if (!live.has(o)) this._freeObject(o);
    this.objects = next;
    if (bbox) this.bbox = bbox;
    this._rebuildGrid();
  }

  _freeObject(o) {
    const gl = this.gl;
    gl.deleteBuffer(o.pos); gl.deleteBuffer(o.nrm);
    if (o.sca) gl.deleteBuffer(o.sca);
    if (o.hi) gl.deleteBuffer(o.hi);
    if (o.ev) gl.deleteBuffer(o.ev);
    if (o.ei) gl.deleteBuffer(o.ei);
  }

  _applyDisplay(obj, o) {
    obj.color = hex2rgb(o.color || '#8899aa');
    obj.alpha = Math.max(0.08, 1 - (o.transparency == null ? 0.4
      : o.transparency));
    obj.isSheet = !!o.isSheet;
    obj.visible = o.visible !== false;
    obj.material = o.material;
    if (o.digest) obj.digest = o.digest;
  }

  _buildObject(o) {
    const gl = this.gl;
    {
      const n = o.count;
      const scalar = o.scalar ? new Float32Array(o.scalar)
        : new Float32Array(n);
      const obj = {
        name: o.name,
        digest: o.digest || '',
        material: o.material,
        color: hex2rgb(o.color || '#8899aa'),
        alpha: Math.max(0.08, 1 - (o.transparency == null ? 0.4
          : o.transparency)),
        isSheet: !!o.isSheet,
        referenceOnly: !!o.referenceOnly,
        visible: o.visible !== false,
        useScalar: o.scalar ? 1 : 0,
        count: n,
        /* f32/i32: the arrays already arrive as typed data over the binary
           transport, so re-copying them costs a second full-size allocation
           for nothing. */
        cpu: f32(o.position),                /* kept for ray picking */
        pos: this._buf(f32(o.position)),
        nrm: this._buf(f32(o.normal)),
        sca: this._buf(scalar),
        /* which geometric face each triangle belongs to, and what those
           faces are: this is what turns a ray hit into "the top of the
           patch" instead of "triangle 412". */
        faceOf: o.faceOf ? i32(o.faceOf) : null,
        faces: o.faces || [],
        faceEdges: o.faceEdges || [],
        edgeGroups: o.cadEdges?.length?o.cadEdges:buildEdgeGroups(o.faceEdges||[],o.edgeVerts||[]),
        pickTree: buildPickTree(o.position),
        snapPoints: o.snapPoints || [], snapKind: o.snapKind || "vertex",
        snapMids: o.snapMids || [], snapCenters: o.snapCenters || [],
        hiCpu: new Float32Array(n),
        hi: this._buf(new Float32Array(n)),
        centroid: centroid(o.position.length ? o.position : (o.edgeVerts || []))
      };
      if (o.edges && o.edgeVerts) {
        obj.evCpu = f32(o.edgeVerts);
        obj.ev = this._buf(obj.evCpu);
        // Draw model boundaries, not every interior surface-mesh triangle.
        // `edges` may arrive as a typed array (binary transport), which has no
        // flatMap; normalise to a plain array before the index-width fallbacks.
        const outline=o.faceEdges?.length?Array.from(new Map(Array.from({length:o.faceEdges.length/3},(_,i)=>[o.faceEdges[3*i]+':'+o.faceEdges[3*i+1],[o.faceEdges[3*i],o.faceEdges[3*i+1]]])).values()).flat():Array.from(o.edges);
        obj.ec=outline.length;obj.u32=!!gl.getExtension('OES_element_index_uint');
        if(obj.u32)obj.ei=this._buf(new Uint32Array(outline),gl.ELEMENT_ARRAY_BUFFER);
        else if(outline.every(i=>i<65536))obj.ei=this._buf(new Uint16Array(outline),gl.ELEMENT_ARRAY_BUFFER);
        else {gl.deleteBuffer(obj.ev);obj.ev=this._buf(new Float32Array(outline.flatMap(i=>Array.from(o.edgeVerts.slice(3*i,3*i+3)))));obj.edgeFlat=true;}

      }
      return obj;
    }
  }

  /* Boundaries and ports, drawn on the faces they cover.
     Nudged toward the camera along their own normal so they sit on the
     surface rather than fighting it for the same depth. */
  setAssignments(items) {
    const gl = this.gl;
    for (const a of (this.assign || [])) gl.deleteBuffer(a.b);
    this.assign = [];
    for (const it of (items || [])) {
      if ((!it.position || !it.position.length) && !it.line) continue;
      const p = new Float32Array(it.position || []);
      this.assign.push({
        b: this._buf(p), n: p.length / 3, name: it.name, type: it.type,
        color: hex2rgb(it.color || '#ff4fa3'),
        center: it.center,
        line: it.line || null,
        lineBuf: it.line ? this._buf(arrowSegments(it.line[0], it.line[1])) : null
      });
    }
  }

  setWire(w) {
    const gl = this.gl;
    if (this.wire) { gl.deleteBuffer(this.wire.v); gl.deleteBuffer(this.wire.i); }
    if (!w) { this.wire = null; return; }
    const uint = !!gl.getExtension('OES_element_index_uint');
    this.wire = {
      v: this._buf(new Float32Array(w.verts)),
      i: this._buf(uint ? new Uint32Array(w.edges) : new Uint16Array(w.edges),
        gl.ELEMENT_ARRAY_BUFFER),
      n: w.edges.length, u32: uint
    };
  }

  /* Everything of the current pick kind inside a screen rectangle.
     Selecting one thing at a time is fine for a box and hopeless for a coil:
     a rubber band is how a modeller selects the forty faces of a spiral. Each
     candidate is reduced to one representative point — an object's triangle
     centroids, a face's own centre, an edge's midpoints, a vertex — and the
     test is whether that point projects inside the rectangle. */
  selectInBox(box, mode) {
    const lo = { x: Math.min(box.x0, box.x1), y: Math.min(box.y0, box.y1) };
    const hi = { x: Math.max(box.x0, box.x1), y: Math.max(box.y0, box.y1) };
    const inside = p => {
      const s = this.project(p);
      return !!s && s.x >= lo.x && s.x <= hi.x && s.y >= lo.y && s.y <= hi.y;
    };
    const out = { objects: [], faces: [], edges: [], points: [] };
    for (const o of this.objects) {
      if (o.visible === false) continue;
      if (mode === 'object') {
        // The way HFSS reads a rubber band: dragged right-to-left it takes only
        // what lies completely inside; left-to-right it also takes whatever the
        // rectangle merely crosses. The object's extent on screen is that of
        // its bounding box.
        const crossing = box.x1 >= box.x0;
        const bb = this._objectBox(o);
        if (bb) {
          const sc = bb.map(c => this.project(c)).filter(Boolean);
          if (sc.length) {
            const bx0 = Math.min(...sc.map(q => q.x)), bx1 = Math.max(...sc.map(q => q.x));
            const by0 = Math.min(...sc.map(q => q.y)), by1 = Math.max(...sc.map(q => q.y));
            const fully = bx0 >= lo.x && bx1 <= hi.x && by0 >= lo.y && by1 <= hi.y;
            const apart = bx1 < lo.x || bx0 > hi.x || by1 < lo.y || by0 > hi.y;
            if (!crossing) { if (fully && sc.length === 8) out.objects.push(o.name); continue; }
            if (apart) continue;
            if (fully) { out.objects.push(o.name); continue; }
          }
        }
        // sample the triangles rather than every vertex: a hit anywhere in
        // the rectangle is a hit, and a million-vertex body must not cost a
        // million projections
        const n = o.cpu ? o.cpu.length / 9 : 0;
        const step = Math.max(1, Math.floor(n / 400));
        let hit = false;
        for (let t = 0; t < n && !hit; t += step) {
          const i = t * 9;
          hit = inside([(o.cpu[i] + o.cpu[i + 3] + o.cpu[i + 6]) / 3,
                        (o.cpu[i + 1] + o.cpu[i + 4] + o.cpu[i + 7]) / 3,
                        (o.cpu[i + 2] + o.cpu[i + 5] + o.cpu[i + 8]) / 3]);
        }
        if (!hit && o.centroid) hit = inside(o.centroid);
        if (hit) out.objects.push(o.name);
      } else if (mode === 'face') {
        (o.faces || []).forEach((f, k) => {
          if (f && f.point && inside(f.point))
            out.faces.push(Object.assign({ object: o.name, face: k }, f));
        });
      } else if (mode === 'edge') {
        (o.edgeGroups || []).forEach(g => {
          const segs = g.segments || [];
          if (!segs.length) return;
          const mid = segs[Math.floor(segs.length / 2)];
          const p = [(mid[0][0] + mid[1][0]) / 2, (mid[0][1] + mid[1][1]) / 2,
                     (mid[0][2] + mid[1][2]) / 2];
          if (!inside(p)) return;
          const ends = edgeEndpoints(segs);
          out.edges.push({ object: o.name, face: g.face, a: ends[0],
                           b: ends[1], length: g.length, segments: segs });
        });
      } else if (mode === 'point') {
        for (const p of (o.snapPoints || [])) if (inside(p)) out.points.push(p);
      }
    }
    return out;
  }

  /* Is any part of the object, inside this screen rectangle, the thing a click
     there would actually hit (not hidden behind another object)? */
  frontIn(name, box) {
    const o = this.objects.find(x => x.name === name);
    if (!o || !o.cpu) return false;
    const lo = { x: Math.min(box.x0, box.x1), y: Math.min(box.y0, box.y1) };
    const hi = { x: Math.max(box.x0, box.x1), y: Math.max(box.y0, box.y1) };
    const n = o.cpu.length / 9, step = Math.max(1, Math.floor(n / 120));
    for (let t = 0; t < n; t += step) {
      const i = t * 9;
      const q = this.project([(o.cpu[i] + o.cpu[i + 3] + o.cpu[i + 6]) / 3,
        (o.cpu[i + 1] + o.cpu[i + 4] + o.cpu[i + 7]) / 3, (o.cpu[i + 2] + o.cpu[i + 5] + o.cpu[i + 8]) / 3]);
      if (!q || q.x < lo.x || q.x > hi.x || q.y < lo.y || q.y > hi.y) continue;
      const h = this.pick(q.x, q.y);
      if (h && h.name === name) return true;
    }
    return false;
  }

  /* the eight corners of an object's bounding box (cached) */
  _objectBox(o) {
    if (o._bb !== undefined) return o._bb;
    const c = o.cpu;
    if (!c || !c.length) return (o._bb = null);
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < c.length; i += 3) for (let a = 0; a < 3; a++) {
      const v = c[i + a]; if (v < lo[a]) lo[a] = v; if (v > hi[a]) hi[a] = v;
    }
    const pts = [];
    for (const x of [lo[0], hi[0]]) for (const y of [lo[1], hi[1]]) for (const z of [lo[2], hi[2]]) pts.push([x, y, z]);
    return (o._bb = pts);
  }

  setSelection(names) { this.selection = new Set(names || []); }

  /* Picked faces, as {object, face} pairs. Highlighting is a per-vertex
     attribute rather than a second draw pass, so it costs one buffer upload
     when the pick changes and nothing per frame. */
  setFaceSelection(picks) {
    const gl = this.gl;
    const want = new Map();
    for (const p of (picks || [])) {
      if (!want.has(p.object)) want.set(p.object, new Set());
      want.get(p.object).add(p.face);
    }
    for (const o of this.objects) {
      const set = want.get(o.name);
      const previewObject=this.hover?.mode==='face'&&this.hover.name===o.name;
      if(!set&&!previewObject&&!o.hasFaceHighlight)continue;
      o.hasFaceHighlight=!!set||previewObject;
      const hi = o.hiCpu;
      let changed = false;
      for (let t = 0; t < hi.length / 3; t++) {
        const selected=set && o.faceOf && set.has(o.faceOf[t]);
        const preview=this.hover?.mode==='face' && this.hover.name===o.name && o.faceOf && this.hover.face===o.faceOf[t];
        const on=selected?1:preview?0.45:0;
        if (hi[t * 3] !== on) {
          hi[t * 3] = hi[t * 3 + 1] = hi[t * 3 + 2] = on;
          changed = true;
        }
      }
      if (changed) {
        gl.bindBuffer(gl.ARRAY_BUFFER, o.hi);
        gl.bufferData(gl.ARRAY_BUFFER, hi, gl.STATIC_DRAW);
      }
    }
    this.facePicks = picks || [];
  }

  /* Picked edges are drawn thick and bright: "select line" is worth nothing
     if you cannot see which line you got. */
  setEdgeSelection(picks) {
    const gl = this.gl;
    if (this.edgeBuf) { gl.deleteBuffer(this.edgeBuf.b); this.edgeBuf = null; }
    this.edgePicks = picks || [];
    const pts = [];
    for (const e of this.edgePicks) {
      if (!e.a || !e.b) continue;
      pts.push(...(e.segments||[[e.a,e.b]]).flat(2));
    }
    if (pts.length)
      this.edgeBuf = { b: this._buf(new Float32Array(pts)), n: pts.length / 3 };
  }

  /* The measurement line: the two points the reported distance is between. */
  setMeasure(line) {
    const gl = this.gl;
    if (this.measureBuf) {
      gl.deleteBuffer(this.measureBuf.b);
      this.measureBuf = null;
    }
    this.measureLine = line || null;
    if (!line) return;
    const p = [line[0][0], line[0][1], line[0][2],
               line[1][0], line[1][1], line[1][2]];
    this.measureBuf = { b: this._buf(new Float32Array(p)), n: 2 };
  }

  /* Where the cursor lands on the working plane.
     Drawing starts from a point, and a point needs a plane to live on: a
     click on a body gives the point on that body (so a trace starts exactly
     on the substrate), and a click on nothing lands on the working plane,
     which is the grid you can see. */
  planePoint(px, py, plane) {
    const hit = this.pick(px, py);
    if (hit && !plane) return { point: hit.point, on: hit.name };
    const { origin, dir } = this.ray(px, py);
    const p = plane || this.workPlane || { normal: [0, 0, 1],
      point: [0, 0, this.bbox[0][2]] };
    const n = p.normal, q = p.point;
    const denom = n[0]*dir[0] + n[1]*dir[1] + n[2]*dir[2];
    if (Math.abs(denom) < 1e-12) return null;
    const t = ((q[0]-origin[0])*n[0] + (q[1]-origin[1])*n[1]
      + (q[2]-origin[2])*n[2]) / denom;
    if (t <= 0) return null;
    return { point: V3.add(origin, V3.scale(dir, t)), on: null };
  }

  /* The rubber-band shown while a point-to-point draw is in progress. */
  setDraft(pts) {
    const gl = this.gl;
    if (this.draftBuf) { gl.deleteBuffer(this.draftBuf.b); this.draftBuf = null; }
    this.draft = pts || null;
    if (!pts || pts.length < 2) return;
    const flat = [];
    for (const p of pts) flat.push(p[0], p[1], p[2]);
    this.draftBuf = { b: this._buf(new Float32Array(flat)), n: pts.length };
  }

  /* Direction glyphs for a vector field: a flat list of segment endpoints
     [x0,y0,z0,x1,y1,z1, ...], drawn as GL lines over the model. */
  setArrows(flat) {
    const gl = this.gl;
    if (this.arrowBuf) { gl.deleteBuffer(this.arrowBuf.b); this.arrowBuf = null; }
    if (!flat || flat.length < 6) return;
    this.arrowBuf = { b: this._buf(new Float32Array(flat)), n: flat.length / 3 };
  }

  /* Where a world point lands on screen, so the number can be labelled in
     HTML instead of rendered into the framebuffer. */
  project(p) {
    const c = this.canvas;
    const w = c.clientWidth || 1, h = c.clientHeight || 1;
    if (!this._proj || !this._view) return null;
    const m = M4.mul(this._proj, this._view);
    const x = m[0]*p[0] + m[4]*p[1] + m[8]*p[2] + m[12];
    const y = m[1]*p[0] + m[5]*p[1] + m[9]*p[2] + m[13];
    const wclip = m[3]*p[0] + m[7]*p[1] + m[11]*p[2] + m[15];
    if (wclip <= 1e-9) return null;
    return { x: (x / wclip * 0.5 + 0.5) * w,
             y: (1 - (y / wclip * 0.5 + 0.5)) * h };
  }

  /* ------------------------------------------------------------- picking */
  /* Click-to-select, done on the CPU against the same triangles that were
     uploaded for drawing. No colour-ID render pass, so it costs nothing on
     every frame and it cannot be fooled by transparency or by the grid. */
  ray(px, py) {
    const c = this.canvas;
    const w = c.clientWidth || 1, h = c.clientHeight || 1;
    const ndcX = (2 * px / w) - 1;
    const ndcY = 1 - (2 * py / h);
    const { eye, ctr, up } = this._camera();
    const fwd = V3.norm(V3.sub(ctr, eye));
    const right = V3.norm(V3.cross(fwd, up));
    const trueUp = V3.cross(right, fwd);
    const t = Math.tan(0.72 / 2);
    const dir = V3.norm(V3.add(fwd,
      V3.add(V3.scale(right, ndcX * t * (w / h)),
             V3.scale(trueUp, ndcY * t))));
    return { origin: eye, dir };
  }

  pick(px, py) {
    const { origin, dir } = this.ray(px, py);
    let best = null, bestT = Infinity, bestTri = -1;
    for (const o of this.objects) {
      if (o.name === '__field__' || o.visible === false) continue;
      const p = o.cpu;
      for (const i of pickCandidates(o.pickTree,origin,dir,p.length)) {
        const t = rayTriangle(origin, dir,
          p[i], p[i+1], p[i+2], p[i+3], p[i+4], p[i+5], p[i+6], p[i+7], p[i+8]);
        if (t !== null && t > 1e-9 && t < bestT) {
          bestT = t; best = o; bestTri = i / 9;
        }
      }
    }
    if (!best) return null;
    const point = V3.add(origin, V3.scale(dir, bestT));
    const face = best.faceOf ? best.faceOf[bestTri] : -1;
    const out = { name: best.name, distance: bestT, point,
                  tri: bestTri, face,
                  meta: (face >= 0 && best.faces[face]) || null };

    return out;
  }

  /* The edge of the hit object closest to where the ray landed. "Select
     line" in a modeller is exactly this: click near an edge of a face you
     can see, and get that edge. */
  _nearestEdge(o, point) {
    const fe = o.faceEdges, ev = o.evCpu;
    if (!fe || !fe.length || !ev) return null;
    let best = null, bestD = Infinity;
    for (let k = 0; k < fe.length; k += 3) {
      const a = fe[k] * 3, b = fe[k + 1] * 3;
      const A = [ev[a], ev[a+1], ev[a+2]], B = [ev[b], ev[b+1], ev[b+2]];
      const d = pointSegDistance(point, A, B);
      if (d < bestD) {
        bestD = d;
        best = { a: A, b: B, face: fe[k + 2],
                 length: V3.len(V3.sub(B, A)) };
      }
    }
    if (!best) return null;
    // only count as an edge pick when the click is genuinely near it
    const scale = Math.max(1e-9, this.dist * 0.02);
    best.distance = bestD;
    best.near = bestD < scale;
    return best;
  }


  pickFeature(px,py,mode='object') {
    const hit=this.pick(px,py);
    if(mode==='object'||mode==='face')return hit;
    const origin=this.ray(px,py).origin;
    let best=null,bestPixels=mode==='point'?12:8;
    const visible=(o,p)=>{
      const q=this.project(p);if(!q)return false;
      const front=this.pick(q.x,q.y);if(!front)return true;
      const eye=this.ray(q.x,q.y).origin;
      return V3.len(V3.sub(p,eye))<=front.distance+this.dist*1e-5;
    };
    for(const o of this.objects) {
      if(o.visible===false||o.name==='__field__')continue;
      if(mode==='point') {
        // vertices win a tie over mid-points, which win over face centres
        const kinds=[[o.snapPoints,o.snapKind||'vertex',0],[o.snapMids,'edge midpoint',3],[o.snapCenters,'face centre',6]];
        for(const [pts,kind,bias] of kinds) {
          for(const point of (pts||[])) {
            const q=this.project(point);if(!q)continue;
            const d=Math.hypot(q.x-px,q.y-py)+bias;
            if(d<bestPixels&&visible(o,point)){bestPixels=d;best={name:o.name,point:[...point],snapKind:kind,vertex:true};}
          }
        }
      } else {
        const ev=o.evCpu,fe=o.faceEdges?.length?o.faceEdges:[];
        if(!ev)continue;
        for(let k=0;k<fe.length;k+=3) {
          const a=Array.from(ev.slice(fe[k]*3,fe[k]*3+3)),b=Array.from(ev.slice(fe[k+1]*3,fe[k+1]*3+3));
          const A=this.project(a),B=this.project(b);if(!A||!B)continue;
          const dx=B.x-A.x,dy=B.y-A.y,t=Math.max(0,Math.min(1,((px-A.x)*dx+(py-A.y)*dy)/(dx*dx+dy*dy||1)));
          const d=Math.hypot(px-A.x-t*dx,py-A.y-t*dy),point=V3.add(a,V3.scale(V3.sub(b,a),t));
          if(d<bestPixels&&visible(o,point)){bestPixels=d;best={name:o.name,point,face:fe[k+2],edge:{a,b,face:fe[k+2],near:true,length:V3.len(V3.sub(b,a))}};}
        }
      }
    }
    if(best?.edge){
      const o=this.objects.find(o=>o.name===best.name);
      const close=(a,b)=>a.every((v,i)=>Math.abs(v-b[i])<Math.max(1e-9,Math.abs(v)*1e-6));
      const group=o.edgeGroups?.find(g=>(g.cad||g.face===best.face)&&g.segments.some(([a,b])=>(close(a,best.edge.a)&&close(b,best.edge.b))||(close(b,best.edge.a)&&close(a,best.edge.b))));
      if(group){
        const ends=edgeEndpoints(group.segments);
        best.edge={...best.edge,segments:group.segments,length:group.length,a:ends[0],b:ends[1]};
      }
    }
    return best;
  }

  setHover(hit,mode) {
    const key=hit?JSON.stringify([mode,hit.name,hit.face,hit.edge?.a,hit.edge?.b,hit.point && mode==='point'?hit.point:null]):'';
    if(key===this.hoverKey)return;
    this.hoverKey=key;this.hover=hit?{...hit,mode}:null;
    this.setFaceSelection(this.facePicks||[]);
    if(this.hoverBuf){this.gl.deleteBuffer(this.hoverBuf.b);this.hoverBuf=null;}
    let pts=[];
    if(hit?.edge&&mode==='edge')pts=(hit.edge.segments||[[hit.edge.a,hit.edge.b]]).flat(2);
    if(hit?.point&&mode==='point')pts=this._pointCross(hit.point);
    if(pts.length)this.hoverBuf={b:this._buf(new Float32Array(pts)),n:pts.length/3};
  }

  _pointCross(point) {
    const r=this.dist*.006,pts=[];
    for(let i=0;i<3;i++){const a=[...point],b=[...point];a[i]-=r;b[i]+=r;pts.push(...a,...b);}
    return pts;
  }

  setPointSelection(points) {
    if(this.pointBuf){this.gl.deleteBuffer(this.pointBuf.b);this.pointBuf=null;}
    const pts=(points||[]).flatMap(p=>this._pointCross(p));
    if(pts.length)this.pointBuf={b:this._buf(new Float32Array(pts)),n:pts.length/3};
  }

  /* Fit the whole model, or one box of it.
     A patch inside a radiation box is a thousandth of the box, so fitting
     everything leaves the part you care about sub-pixel. Passing a box fits
     that instead. */
  fit(box) {
    const [lo, hi] = box || this.bbox;
    this.center = [(lo[0]+hi[0])/2, (lo[1]+hi[1])/2, (lo[2]+hi[2])/2];
    const r = Math.max(1e-6, V3.len(V3.sub(hi, lo)) / 2);
    this.dist = r * 3.1;
    this.pan = [0, 0];
  }

  /* The bounding box of the named objects, from the buffers already on the
     GPU side — no round trip to the server to answer "where is this?". */
  boundsOf(names) {
    const want = new Set(names || []);
    const lo = [Infinity, Infinity, Infinity];
    const hi = [-Infinity, -Infinity, -Infinity];
    let any = false;
    for (const o of this.objects) {
      if (!want.has(o.name) || !o.cpu || !o.cpu.length) continue;
      any = true;
      for (let i = 0; i < o.cpu.length; i += 3)
        for (let a = 0; a < 3; a++) {
          const v = o.cpu[i + a];
          if (v < lo[a]) lo[a] = v;
          if (v > hi[a]) hi[a] = v;
        }
    }
    return any ? [lo, hi] : null;
  }

  view(name) {
    const v = { top:[0,Math.PI/2-1e-3], bottom:[0,-Math.PI/2+1e-3],
      front:[-Math.PI/2,0], back:[Math.PI/2,0],
      left:[Math.PI,0], right:[0,0], iso:[-0.72,0.52] }[name];
    if (v) { this.yaw = v[0]; this.pitch = v[1]; }
  }

  _rebuildGrid() {
    const gl = this.gl;
    if (this.grid) { gl.deleteBuffer(this.grid.b); }
    const [lo, hi] = this.bbox;
    const sx = Math.max(hi[0]-lo[0], hi[1]-lo[1], 1e-6);
    const step = this.gridStep || (this.gridStep=niceStep(sx / 10));
    const x0 = -20*step, x1 = 20*step;
    const y0 = -20*step, y1 = 20*step;
    const z = 0;
    const pts = [];
    for (let x = x0; x <= x1 + 1e-12; x += step) pts.push(x,y0,z, x,y1,z);
    for (let y = y0; y <= y1 + 1e-12; y += step) pts.push(x0,y,z, x1,y,z);
    this.grid = { b: this._buf(new Float32Array(pts)), n: pts.length/3, step };
  }

  /* ------------------------------------------------------------- input */
  _bindInput() {
    const c = this.canvas;
    let drag = null;
    // Right-click: what is under the cursor goes to the application, which
    // decides what the menu should offer. The browser's own menu is never
    // useful over a 3-D view.
    c.addEventListener('contextmenu', e => {
      e.preventDefault();
      if (!this.onContext) return;
      const r = c.getBoundingClientRect();
      this.onContext(this.pick(e.clientX - r.left, e.clientY - r.top), e);
    });
    let downAt = null;
    c.addEventListener('pointerdown', e => {
      c.setPointerCapture(e.pointerId);
      // Ctrl means "select" everywhere in this application, so Ctrl+drag is
      // a selection rectangle rather than a second way to pan. Shift+drag and
      // the middle button still pan.
      const band = e.button === 0 && (e.ctrlKey || e.metaKey || this.bandArmed);
      drag = { x: e.clientX, y: e.clientY,
        mode: band ? 'band'
          : (e.button === 0 && !e.shiftKey) ? 'rot' : 'pan' };
      const r0 = c.getBoundingClientRect();
      if (band) this.band = { x0: e.clientX - r0.left, y0: e.clientY - r0.top,
                              x1: e.clientX - r0.left, y1: e.clientY - r0.top };
      downAt = { x: e.clientX, y: e.clientY, button: e.button, t: Date.now() };
      c.style.cursor = band ? 'crosshair'
        : drag.mode === 'rot' ? 'grabbing' : 'move';
    });
    c.addEventListener('pointermove', e => {
      if (!drag && this.onHover) {
        const r = c.getBoundingClientRect();
        this.onHover(e.clientX - r.left, e.clientY - r.top, e);
      }
      if (!drag) return;
      if(downAt && Math.hypot(e.clientX-downAt.x,e.clientY-downAt.y)<4)return;
      this.setHover(null);
      if (drag.mode === 'band') {
        const r = c.getBoundingClientRect();
        this.band.x1 = e.clientX - r.left;
        this.band.y1 = e.clientY - r.top;
        if (this.onBandUpdate) this.onBandUpdate(this.band);
        return;
      }
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (drag.mode === 'rot') {
        // A free orbit: the pitch goes on past the poles (the view simply turns
        // upside down) instead of stopping at the vertical, and when it is
        // upside down a horizontal drag still turns the model the way the
        // hand moves.
        const flipped = Math.cos(this.pitch) < 0;
        this.yaw -= dx * 0.0085 * (flipped ? -1 : 1);
        this.pitch += dy * 0.0085;
        const TAU = 2 * Math.PI;
        this.pitch -= TAU * Math.round(this.pitch / TAU);
      } else {
        const k = this.dist * 0.0016;
        this.pan[0] -= dx * k; this.pan[1] += dy * k;
      }
    });
    const stop = e => {
      if (drag && drag.mode === 'band') {
        const box = this.band;
        this.band = null;
        this.bandArmed = false;
        if (this.onBandUpdate) this.onBandUpdate(null);
        const wide = box && Math.abs(box.x1 - box.x0) > 3
          && Math.abs(box.y1 - box.y0) > 3;
        if (wide && this.onBand) this.onBand(box, e);
        downAt = null; drag = null; c.style.cursor = 'default';
        return;
      }
      /* a left click that did not turn into a drag is a selection */
      if (downAt && e && downAt.button === 0 &&
          Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) < 4 &&
          Date.now() - downAt.t < 700 && this.onPick) {
        const r = c.getBoundingClientRect();
        const px = e.clientX - r.left, py = e.clientY - r.top;
        // a draw in progress consumes the click instead of selecting
        if (this.onPickAt && this.onPickAt(px, py)) {
          this.consumedPickAt=Date.now();
          downAt = null; drag = null; c.style.cursor = 'default';
          return;
        }
        this.onPick(this.pickFeature(px, py, this.selectMode || 'object'), e);
      }
      downAt = null;
      drag = null;
      c.style.cursor = 'default';
    };
    c.addEventListener('pointerup', stop);
    c.addEventListener('pointercancel',()=>{downAt=null;drag=null;c.style.cursor='default';});
    c.addEventListener('wheel', e => {
      e.preventDefault();
      this.dist *= Math.exp(Math.sign(e.deltaY) * 0.12);
    }, { passive: false });
    c.addEventListener('dblclick', e => {
      if(e.button!==0 || Date.now()-(this.consumedPickAt||0)<500)return;
      e.preventDefault();
      const r=c.getBoundingClientRect();
      if(this.onDoublePick)this.onDoublePick(this.pick(e.clientX-r.left,e.clientY-r.top),e);
    });
    c.addEventListener('pointerleave',()=>{this.setHover(null);if(this.onLeave)this.onLeave();});
  }

  _camera() {
    const cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
    const dir = [Math.cos(this.yaw)*cp, Math.sin(this.yaw)*cp, sp];
    // Both are continuous through the poles (unlike a fixed world "up"), which
    // is what lets the orbit go all the way round.
    const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw);
    const right = [sy, -cy, 0];
    const up = [-cy*sp, -sy*sp, cp];
    const ctr = V3.add(this.center,
      V3.add(V3.scale(right, this.pan[0]), V3.scale(up, this.pan[1])));
    const eye = V3.add(ctr, V3.scale(dir, this.dist));
    return { eye, ctr, up };
  }

  /* ------------------------------------------------------------ render */
  _loop() {
    this._draw();
    requestAnimationFrame(this._loop);
  }

  _draw() {
    const gl = this.gl, c = this.canvas;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(c.clientWidth * dpr));
    const h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    gl.viewport(0, 0, w, h);
    gl.clearColor(0.13, 0.16, 0.20, 1);
    gl.enable(gl.DEPTH_TEST);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    const { eye, ctr, up } = this._camera();
    const near = Math.max(this.dist * 0.002, 1e-7);
    const proj = M4.perspective(0.72, w / h, near, this.dist * 40 + 10);
    const view = M4.lookAt(eye, ctr, up);
    this._proj = proj; this._view = view; this._eye = eye;

    if (this.showGrid && this.grid) {this._drawGrid(proj, view);this._drawWorldAxes(proj,view);}

    const solids = this.mode === 'wireframe' ? []
      : this.objects.filter(o => o.visible !== false);
    solids.sort((a, b) =>
      V3.len(V3.sub(b.centroid, eye)) - V3.len(V3.sub(a.centroid, eye)));

    gl.useProgram(this.progSolid);
    const P = this.progSolid;
    gl.uniformMatrix4fv(gl.getUniformLocation(P, 'uProj'), false, proj);
    gl.uniformMatrix4fv(gl.getUniformLocation(P, 'uView'), false, view);
    gl.uniformMatrix3fv(gl.getUniformLocation(P, 'uNormal'), false,
      new Float32Array([1,0,0, 0,1,0, 0,0,1]));
    gl.uniform3fv(gl.getUniformLocation(P, 'uEye'), new Float32Array(eye));
    const aPos = gl.getAttribLocation(P, 'aPos');
    const aNrm = gl.getAttribLocation(P, 'aNrm');
    const aSca = gl.getAttribLocation(P, 'aScalar');
    const aHi = gl.getAttribLocation(P, 'aHi');
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    for (const o of solids) {
      const sel = this.selection.has(o.name);
      // Solid Display: air, vacuum and PML regions carry a material
      // transparency near 1, so a model made mostly of them renders as an
      // almost empty window. This forces every body opaque instead.
      const solid = this.opaque || (this.solidParts && o.alpha >= 0.2 && !this.userAlpha.has(o.name));
      const alpha = solid ? Math.max(o.alpha, 0.94) : o.alpha;
      gl.depthMask(alpha > 0.985);
      gl.uniform3fv(gl.getUniformLocation(P, 'uColor'), o.color);
      gl.uniform1f(gl.getUniformLocation(P, 'uAlpha'),
        sel ? Math.min(1, alpha + 0.22) : alpha);
      gl.uniform1f(gl.getUniformLocation(P, 'uSelected'), sel ? 1 : (this.hover?.mode==='object' && this.hover.name===o.name ? 0.6 : 0));
      gl.uniform1f(gl.getUniformLocation(P, 'uUseScalar'), o.useScalar);
      bindAttr(gl, o.pos, aPos, 3);
      bindAttr(gl, o.nrm, aNrm, 3);
      if (aSca >= 0) bindAttr(gl, o.sca, aSca, 1);
      if (aHi >= 0) bindAttr(gl, o.hi, aHi, 1);
      if (o.isSheet) gl.disable(gl.CULL_FACE);
      gl.drawArrays(gl.TRIANGLES, 0, o.count);
    }
    gl.depthMask(true);
    gl.disable(gl.BLEND);

    this._drawEdges(proj, view, this.mode === 'shaded');
    if (this.wire) this._drawWire(proj, view);
    if (this.showAssignments) this._drawAssignments(proj, view);
    this._drawPicks(proj, view);
    if(this.triad)this.triad.style.display=this.showTriad?"block":"none";
    if (this.showTriad) this._drawTriad(w, h);
  }

  _lineSetup(proj, view, rgba) {
    const gl = this.gl, P = this.progLine;
    gl.useProgram(P);
    gl.uniformMatrix4fv(gl.getUniformLocation(P, 'uProj'), false, proj);
    gl.uniformMatrix4fv(gl.getUniformLocation(P, 'uView'), false, view);
    gl.uniform4fv(gl.getUniformLocation(P, 'uColor'), new Float32Array(rgba));
    return gl.getAttribLocation(P, 'aPos');
  }

  _drawGrid(proj, view) {
    const gl = this.gl;
    const a = this._lineSetup(proj, view, [0.42, 0.48, 0.56, 0.45]);
    bindAttr(gl, this.grid.b, a, 3);
    gl.drawArrays(gl.LINES, 0, this.grid.n);
  }

  _drawEdges(proj, view, referencesOnly=false) {
    const gl = this.gl;
    const a = this._lineSetup(proj, view, [0.86, 0.90, 0.96, 0.85]);
    for (const o of this.objects) {
      if ((!o.ei && !o.edgeFlat) || o.visible === false || (referencesOnly && !o.referenceOnly)) continue;
      bindAttr(gl, o.ev, a, 3);
      if(o.edgeFlat){gl.drawArrays(gl.LINES,0,o.ec);continue;}
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, o.ei);
      gl.drawElements(gl.LINES, o.ec,
        o.u32 ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT, 0);
    }
  }

  _drawAssignments(proj, view) {
    const gl = this.gl, P = this.progSolid;
    gl.useProgram(P);
    gl.uniformMatrix4fv(gl.getUniformLocation(P, 'uProj'), false, proj);
    gl.uniformMatrix4fv(gl.getUniformLocation(P, 'uView'), false, view);
    gl.uniformMatrix3fv(gl.getUniformLocation(P, 'uNormal'), false,
      new Float32Array([1,0,0, 0,1,0, 0,0,1]));
    gl.uniform3fv(gl.getUniformLocation(P, 'uEye'), new Float32Array(this._eye));
    gl.uniform1f(gl.getUniformLocation(P, 'uUseScalar'), 0);
    gl.uniform1f(gl.getUniformLocation(P, 'uSelected'), 0);
    const aPos = gl.getAttribLocation(P, 'aPos');
    const aNrm = gl.getAttribLocation(P, 'aNrm');
    const aHi = gl.getAttribLocation(P, 'aHi');
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.depthMask(false);
    gl.disable(gl.DEPTH_TEST);
    for (const a of (this.assign || [])) {
      if (a.type === 'radiation' && !this.showRadiation) continue;
      gl.uniform3fv(gl.getUniformLocation(P, 'uColor'), a.color);
      // a radiation box wraps the whole model and is seen through six faces;
      // at the usual opacity it hides the very thing it surrounds
      gl.uniform1f(gl.getUniformLocation(P, 'uAlpha'),
        a.type === 'radiation' ? 0.07
          : (a.type === 'lumped' || a.type === 'wave') ? 0.75 : 0.38);
      bindAttr(gl, a.b, aPos, 3);
      if (aNrm >= 0) bindAttr(gl, a.b, aNrm, 3);
      if (aHi >= 0) gl.disableVertexAttribArray(aHi);
      gl.drawArrays(gl.TRIANGLES, 0, a.n);
    }
    gl.depthMask(true);
    gl.disable(gl.BLEND);
    // the port's integration line, drawn on top of its face
    for (const a of (this.assign || [])) {
      if (!a.lineBuf) continue;
      const at = this._lineSetup(proj, view, [1, 1, 1, 0.95]);
      bindAttr(gl, a.lineBuf, at, 3);
      gl.lineWidth(3);
      gl.drawArrays(gl.LINES, 0, 6);
      gl.lineWidth(1);
    }
    gl.enable(gl.DEPTH_TEST);
    gl.useProgram(this.progSolid);
  }

  _drawPicks(proj, view) {
    const gl = this.gl;
    gl.disable(gl.DEPTH_TEST);
    for(const [buf,color,mode] of [[this.hoverBuf,[1,0.88,0.2,1],gl.LINES],[this.pointBuf,[0.2,0.9,1,1],gl.LINES],[this.draftBuf,[0.36,0.95,0.55,1],gl.LINE_STRIP]]) {
      if(!buf)continue;const a=this._lineSetup(proj,view,color);bindAttr(gl,buf.b,a,3);gl.drawArrays(mode,0,buf.n);
    }
    if (this.edgeBuf) {
      const a = this._lineSetup(proj, view, [1.0, 0.62, 0.16, 1.0]);
      bindAttr(gl, this.edgeBuf.b, a, 3);
      gl.lineWidth(3);
      gl.drawArrays(gl.LINES, 0, this.edgeBuf.n);
    }
    if (this.arrowBuf) {
      const a = this._lineSetup(proj, view, [0.05, 0.05, 0.05, 1.0]);
      bindAttr(gl, this.arrowBuf.b, a, 3);
      gl.lineWidth(1.5);
      gl.drawArrays(gl.LINES, 0, this.arrowBuf.n);
    }
    if (this.measureBuf && this.measureVisible!==false) {
      const a = this._lineSetup(proj, view, [0.16, 0.78, 1.0, 1.0]);
      bindAttr(gl, this.measureBuf.b, a, 3);
      gl.lineWidth(2);
      gl.drawArrays(gl.LINES, 0, this.measureBuf.n);
    }
    gl.lineWidth(1);
    gl.enable(gl.DEPTH_TEST);
  }

  _drawWire(proj, view) {
    const gl = this.gl;
    const a = this._lineSetup(proj, view, [0.36, 0.85, 0.62, 0.55]);
    bindAttr(gl, this.wire.v, a, 3);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.wire.i);
    gl.drawElements(gl.LINES, this.wire.n,
      this.wire.u32 ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT, 0);
  }

  _drawWorldAxes(proj,view){
    const gl=this.gl,r=20*(this.gridStep||.001);
    for(const [i,color] of [[0,[1,.3,.3,1]],[1,[.3,1,.4,1]],[2,[.3,.6,1,1]]]){
      const pts=[0,0,0,0,0,0];pts[i]=-r;pts[i+3]=r;
      const a=this._lineSetup(proj,view,color),b=this._buf(new Float32Array(pts));bindAttr(gl,b,a,3);gl.drawArrays(gl.LINES,0,2);gl.deleteBuffer(b);
    }
  }

  _drawTriad(w,h) {
    // Screen-anchored SVG uses camera rotation only, never object translation/pan.
    if(!this.triad){
      this.triad=document.createElementNS('http://www.w3.org/2000/svg','svg');
      this.triad.setAttribute('viewBox','0 0 120 120');
      this.triad.style.cssText='position:absolute;left:10px;bottom:30px;width:120px;height:120px;pointer-events:none;z-index:3';
      this.canvas.parentElement.appendChild(this.triad);
    }
    const {eye,ctr,up}=this._camera(),dir=V3.norm(V3.sub(eye,ctr));
    const right=V3.norm(V3.cross(up,dir)),vertical=V3.cross(dir,right);
    this.triad.innerHTML=[['X',[1,0,0],'#ff625b'],['Y',[0,1,0],'#69dc78'],['Z',[0,0,1],'#68a6ff']].map(([label,v,color])=>{
      const dot=(a,b)=>a.reduce((n,x,i)=>n+x*b[i],0);
      const dx=dot(v,right)*38,dy=-dot(v,vertical)*38,x=60+dx,y=60+dy;
      const angle=Math.atan2(dy,dx),a=angle+.45,b=angle-.45;
      return `<path d="M60 60 L${x} ${y} M${x-9*Math.cos(a)} ${y-9*Math.sin(a)} L${x} ${y} L${x-9*Math.cos(b)} ${y-9*Math.sin(b)}" fill="none" stroke="${color}" stroke-width="2.5"/><text x="${x+8*Math.cos(angle)}" y="${y+8*Math.sin(angle)+4}" fill="${color}" font-size="14" font-weight="bold" text-anchor="middle">${label}</text>`;
    }).join('');
  }

  screenshot() { return this.canvas.toDataURL('image/png'); }
}

/* Moller-Trumbore ray/triangle intersection; returns the ray parameter or null */
function pointSegDistance(p, a, b) {
  const ab = V3.sub(b, a), ap = V3.sub(p, a);
  const l2 = ab[0]*ab[0] + ab[1]*ab[1] + ab[2]*ab[2];
  const t = l2 > 0 ? Math.max(0, Math.min(1,
    (ap[0]*ab[0] + ap[1]*ab[1] + ap[2]*ab[2]) / l2)) : 0;
  return V3.len(V3.sub(p, V3.add(a, V3.scale(ab, t))));
}

function rayTriangle(o, d, ax, ay, az, bx, by, bz, cx, cy, cz) {
  const e1x = bx - ax, e1y = by - ay, e1z = bz - az;
  const e2x = cx - ax, e2y = cy - ay, e2z = cz - az;
  const px = d[1] * e2z - d[2] * e2y;
  const py = d[2] * e2x - d[0] * e2z;
  const pz = d[0] * e2y - d[1] * e2x;
  const det = e1x * px + e1y * py + e1z * pz;
  if (det > -1e-14 && det < 1e-14) return null;      /* parallel */
  const inv = 1 / det;
  const tx = o[0] - ax, ty = o[1] - ay, tz = o[2] - az;
  const u = (tx * px + ty * py + tz * pz) * inv;
  if (u < -1e-7 || u > 1 + 1e-7) return null;
  const qx = ty * e1z - tz * e1y;
  const qy = tz * e1x - tx * e1z;
  const qz = tx * e1y - ty * e1x;
  const v = (d[0] * qx + d[1] * qy + d[2] * qz) * inv;
  if (v < -1e-7 || u + v > 1 + 1e-7) return null;
  const t = (e2x * qx + e2y * qy + e2z * qz) * inv;
  return t > 0 ? t : null;
}

function bindAttr(gl, buf, loc, size) {
  if (loc < 0) return;
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
}
function hex2rgb(h) {
  const s = (h || '#889').replace('#', '');
  const t = s.length === 3 ? s.split('').map(c => c + c).join('') : s;
  return new Float32Array([parseInt(t.substr(0,2),16)/255,
    parseInt(t.substr(2,2),16)/255, parseInt(t.substr(4,2),16)/255]);
}
const f32 = a => a instanceof Float32Array ? a : new Float32Array(a);
const i32 = a => a instanceof Int32Array ? a : new Int32Array(a);
function centroid(pos) {
  let x = 0, y = 0, z = 0, n = pos.length / 3;
  for (let i = 0; i < pos.length; i += 3) { x += pos[i]; y += pos[i+1]; z += pos[i+2]; }
  return n ? [x/n, y/n, z/n] : [0,0,0];
}
function niceStep(v) {
  const e = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1e-12))));
  const m = v / e;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * e;
}

window.Viewport = Viewport;

// Connected face-outline components: a rectangle perimeter or one circular rim.
function buildEdgeGroups(faceEdges,vertices){
  const faces=new Map(),groups=[];
  for(let k=0;k<faceEdges.length;k+=3){const f=faceEdges[k+2];if(!faces.has(f))faces.set(f,[]);faces.get(f).push([faceEdges[k],faceEdges[k+1]]);}
  for(const [face,edges] of faces){
    const adjacency=new Map();edges.forEach((e,i)=>e.forEach(v=>{if(!adjacency.has(v))adjacency.set(v,[]);adjacency.get(v).push(i);}));
    const seen=new Set();
    edges.forEach((e,i)=>{if(seen.has(i))return;const queue=[i],segments=[];seen.add(i);
      while(queue.length){const j=queue.pop(),pair=edges[j];segments.push(pair.map(v=>Array.from(vertices.slice(v*3,v*3+3))));
        for(const v of pair){
          const attached=adjacency.get(v);if(attached.length!==2)continue;
          for(const n of attached){if(seen.has(n))continue;
            const other=edges[n],coord=k=>Array.from(vertices.slice(k*3,k*3+3));
            const a=V3.norm(V3.sub(coord(pair[0]===v?pair[1]:pair[0]),coord(v)));
            const b=V3.norm(V3.sub(coord(other[0]===v?other[1]:other[0]),coord(v)));
            if(a.reduce((sum,x,i)=>sum+x*b[i],0)>-Math.cos(Math.PI/9))continue;
            seen.add(n);queue.push(n);
          }
        }}
      groups.push({face,segments,length:segments.reduce((n,[a,b])=>n+V3.len(V3.sub(b,a)),0)});
    });
  }return groups;
}

// Static triangle BVH. Original triangle indices remain valid for face assignment.
function buildPickTree(p){
  const count=p.length/9;if(!count)return null;
  const ids=Array.from({length:count},(_,i)=>i),bounds=new Float64Array(count*6);
  for(let t=0;t<count;t++)for(let a=0;a<3;a++){
    const i=t*9+a,x=p[i],y=p[i+3],z=p[i+6];
    bounds[t*6+a]=x<y?(x<z?x:z):(y<z?y:z);
    bounds[t*6+a+3]=x>y?(x>z?x:z):(y>z?y:z);
  }
  function build(start,end){
    const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
    for(let j=start;j<end;j++){const i=ids[j]*6;for(let a=0;a<3;a++){const l=bounds[i+a],h=bounds[i+a+3];if(l<lo[a])lo[a]=l;if(h>hi[a])hi[a]=h;}}
    if(end-start<=24)return {lo,hi,ids:ids.slice(start,end).map(i=>i*9)};
    let axis=0;for(let a=1;a<3;a++)if(hi[a]-lo[a]>hi[axis]-lo[axis])axis=a;
    const split=lo[axis]+hi[axis];let mid=start;
    for(let j=start;j<end;j++){const i=ids[j]*6;if(bounds[i+axis]+bounds[i+axis+3]<split){const t=ids[mid];ids[mid++]=ids[j];ids[j]=t;}}
    if(mid-start<(end-start)*.05||end-mid<(end-start)*.05)mid=(start+end)>>1;
    return {lo,hi,left:build(start,mid),right:build(mid,end)};
  }return build(0,count);
}

function rayBox(node,origin,dir){
  let near=0,far=Infinity;
  for(let a=0;a<3;a++){
    if(Math.abs(dir[a])<1e-15){if(origin[a]<node.lo[a]-1e-9||origin[a]>node.hi[a]+1e-9)return false;continue;}
    let t0=(node.lo[a]-1e-9-origin[a])/dir[a],t1=(node.hi[a]+1e-9-origin[a])/dir[a];
    if(t0>t1)[t0,t1]=[t1,t0];near=Math.max(near,t0);far=Math.min(far,t1);if(near>far)return false;
  }return true;
}
function* pickCandidates(tree,origin,dir,length){
  if(!tree){for(let i=0;i<length;i+=9)yield i;return;}
  const pending=[tree];while(pending.length){const n=pending.pop();if(!rayBox(n,origin,dir))continue;
    if(n.ids)yield* n.ids;else pending.push(n.left,n.right);
  }
}

function edgeEndpoints(segments){
  const points=new Map();for(const seg of segments)for(const p of seg){const key=p.join(',');const v=points.get(key);if(v)v.count++;else points.set(key,{p,count:1});}
  const ends=[...points.values()].filter(x=>x.count===1).map(x=>x.p);
  return ends.length===2?ends:[segments[0][0],segments[0][0]];
}
