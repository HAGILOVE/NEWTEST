#!/usr/bin/env node
/**
 * Bundle the tool into one self-contained HTML file.
 *
 * The app is plain ES modules with zero dependencies, so "building" is just
 * resolving the import graph and wrapping each module in its own IIFE that
 * returns its exports. Wrapping (rather than flattening into one scope) keeps
 * module-local helper names private, so two modules may each have their own
 * `mm()` or `card()` without colliding.
 *
 * No bundler, no toolchain, no lockfile - the output must still open in a
 * browser years from now.
 *
 *   node tools/build.mjs  ->  dist/rf-antenna-studio.html
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const entry = resolve(root, 'src/ui/app.js');

const IMPORT_RE = /^[ \t]*import[ \t]*\{([^}]*)\}[ \t]*from[ \t]*['"]([^'"]+)['"];?[ \t]*$/gm;

const modules = new Map();   // file -> { id, body, imports:[{names,file}], exports:Set }
let nextId = 0;

function parse(file) {
  if (modules.has(file)) return modules.get(file);
  const raw = readFileSync(file, 'utf8');
  const dir = dirname(file);
  const rec = { id: nextId++, file, imports: [], exports: new Set(), deps: [] };
  modules.set(file, rec);

  for (const m of raw.matchAll(IMPORT_RE)) {
    const spec = m[2];
    if (!spec.startsWith('.')) {
      throw new Error(`Bare specifier "${spec}" in ${relative(root, file)} - the bundle must stay dependency-free`);
    }
    const dep = resolve(dir, spec);
    rec.imports.push({ names: m[1].split(',').map((s) => s.trim()).filter(Boolean), file: dep });
    rec.deps.push(dep);
    parse(dep);
  }

  // collect export names
  for (const m of raw.matchAll(/^export\s+(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)/gm)) {
    rec.exports.add(m[1]);
  }
  for (const m of raw.matchAll(/^export\s*\{([^}]*)\}\s*;?\s*$/gm)) {
    for (const n of m[1].split(',').map((s) => s.trim()).filter(Boolean)) {
      rec.exports.add(n.includes(' as ') ? n.split(/\s+as\s+/)[1].trim() : n);
    }
  }

  // rewrite the body
  let body = raw
    .replace(IMPORT_RE, '')
    .replace(/^export\s*\{[^}]*\}\s*;?\s*$/gm, '')
    .replace(/^export\s+/gm, '');
  rec.body = body.trim();
  return rec;
}

parse(entry);

// topological order (dependencies first)
const order = [];
const state = new Map();
(function visit(file) {
  const st = state.get(file);
  if (st === 'done') return;
  if (st === 'visiting') throw new Error(`Import cycle involving ${relative(root, file)}`);
  state.set(file, 'visiting');
  for (const d of modules.get(file).deps) visit(d);
  state.set(file, 'done');
  order.push(file);
})(entry);

const chunks = order.map((file) => {
  const m = modules.get(file);
  const binds = m.imports
    .map((im) => `const { ${im.names.join(', ')} } = __m${modules.get(im.file).id};`)
    .join('\n');
  const exps = [...m.exports].map((n) => `${n}: typeof ${n} !== 'undefined' ? ${n} : undefined`).join(', ');
  return `/* ===== ${relative(root, file)} ===== */
const __m${m.id} = (function () {
${binds}
${m.body}
return { ${exps} };
})();`;
});

const entryId = modules.get(entry).id;
const css = readFileSync(resolve(root, 'src/styles/main.css'), 'utf8');
const html = readFileSync(resolve(root, 'index.html'), 'utf8');
const title = (html.match(/<title>([^<]*)<\/title>/) || [, 'RF Antenna Studio'])[1];

const out = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<meta name="description" content="Physics-based antenna design tool: antenna-type recommendation, substrate trade studies, efficiency, ground-plane, thermal, tolerance and link-budget analysis.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128225;</text></svg>">
<style>
${css}
</style>
</head>
<body>
<div id="app-root"><noscript>This tool requires JavaScript.</noscript></div>
<script>
(function () {
'use strict';
${chunks.join('\n\n')}

__m${entryId}.boot();
})();
</script>
</body>
</html>
`;

mkdirSync(resolve(root, 'dist'), { recursive: true });
const dest = resolve(root, 'dist/rf-antenna-studio.html');
writeFileSync(dest, out);
console.log(`bundled ${order.length} modules -> ${relative(root, dest)} (${(out.length / 1024).toFixed(0)} kB)`);
