/* Inline chips.js, engine.js and feel.js into feel.html to produce a
   single self-contained page.

   Why: an Artifact is served under a strict CSP that blocks every
   external request, so <script src> cannot resolve. Same reason the
   page carries no fonts, no CDN and no fetch.

   Run:  node chipless/prototype/build.js
   Out:  chipless/prototype/dist/clink-feel.html                     */

const fs = require('fs');
const path = require('path');

const here = __dirname;
const SRC  = path.join(here, 'feel.html');
const OUT  = path.join(here, 'dist', 'clink-feel.html');

const files = {
  '../mockups/chips.js': path.join(here, '..', 'mockups', 'chips.js'),
  'engine.js':           path.join(here, 'engine.js'),
  'feel.js':             path.join(here, 'feel.js'),
};

let html = fs.readFileSync(SRC, 'utf8');

for (const [ref, abs] of Object.entries(files)) {
  const tag = `<script src="${ref}"></script>`;
  if (!html.includes(tag)) throw new Error(`expected script tag for ${ref}`);
  const code = fs.readFileSync(abs, 'utf8')
    /* the CommonJS tail is for the node tests; it would throw in a page
       if `module` were ever defined, and it is dead weight regardless */
    .replace(/\nif\s*\(typeof module[\s\S]*$/, '\n');
  /* A REPLACER FUNCTION, not a string. In a string replacement, `$` is
     special: engine.js contains `'$'` (in money()), and `$'` means
     "everything after the match" — which silently duplicated the rest of
     the document, tags and all. A function argument is taken literally. */
  html = html.replace(tag, () => `<script>\n/* ─── inlined: ${ref} ─── */\n${code}\n</script>`);
}

/* the dev page notes it links three scripts; it no longer does */
html = html.replace('<title>Clink — feel prototype</title>',
                    '<title>Clink — feel prototype</title>\n<!-- single file: chips.js, engine.js and feel.js are inlined below -->');

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, html);

const kb = (Buffer.byteLength(html) / 1024).toFixed(1);
console.log(`wrote ${path.relative(process.cwd(), OUT)}  (${kb} KB)`);
if (/<script src=/.test(html)) {
  console.error('FAIL: an external script reference survived');
  process.exit(1);
}
console.log('no external script references remain');
