// Exports the Material 3 shape set used by Quickshell ii (end-4/rounded-polygon-qmljs, a port of
// androidx.graphics.shapes) to unit-square SVG paths: scripts/material_shapes.json.
// Usage: node scripts/tools/export_material_shapes.js ~/.config/quickshell/ii/modules/common/widgets/shapes > scripts/material_shapes.json
// Loads the shell's QML-JS Material Shapes port in node and prints every shape as an SVG path.
const fs = require('fs'), path = require('path');
const ROOT = process.argv[2];
const cache = {};
function load(file) {
  file = path.resolve(file);
  if (cache[file]) return cache[file];
  let src = fs.readFileSync(file, 'utf8');
  const imports = [];
  src = src.replace(/^\.pragma library\s*$/m, '').replace(/^\.import\s+"([^"]+)"\s+as\s+(\w+)\s*$/mg, (_, p, n) => { imports.push([p, n]); return ''; });
  const names = [...new Set([...src.matchAll(/^(?:function|class|var|const|let)\s+(\w+)/mg)].map(m => m[1]))];
  const mod = {};
  cache[file] = mod;
  const deps = imports.map(([p]) => load(path.join(path.dirname(file), p)));
  const body = src + '\nreturn {' + names.join(',') + '};';
  Object.assign(mod, new Function(...imports.map(i => i[1]), body)(...deps));
  return mod;
}
const MS = load(path.join(ROOT, 'material-shapes.js'));
const out = {};
for (const k of Object.keys(MS)) {
  if (!/^get[A-Z]/.test(k) || typeof MS[k] !== 'function') continue;
  const poly = MS[k]().normalized();
  const c = poly.cubics, f = v => (+v.toFixed(5)).toString();
  let d = `M${f(c[0].anchor0X)} ${f(c[0].anchor0Y)}`;
  for (const q of c) d += `C${f(q.control0X)} ${f(q.control0Y)} ${f(q.control1X)} ${f(q.control1Y)} ${f(q.anchor1X)} ${f(q.anchor1Y)}`;
  out[k.slice(3)] = d + 'Z';
}
console.log(JSON.stringify(out, null, 1));
