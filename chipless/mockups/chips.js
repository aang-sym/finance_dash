/* ══════════════════════════════════════════════════════════════
   chips.js — the chip factory, shared by every mockup.
   One source of truth for the tokens: denominations and their
   three-way coding, the four art directions, edge-on stacks, and
   the seeded pot scatter. Written to lift straight into the app,
   which is why the mockups all pull from here rather than each
   carrying their own copy.

   Pages must define --sans / --mono / --serif custom properties;
   the SVG text references them so type stays consistent.
   ══════════════════════════════════════════════════════════════ */

/* ── denominations ────────────────────────────────────────────
   Coded three ways: colour value, edge-spot count, numeral.
   Values sit in three luminance bands, two per band, so within
   a band the spot count is what separates them. Six evenly
   spaced luminance steps would be too tight to read. */
const DENOMS = [
  { key:'25c', label:'25¢', words:'TWENTY-FIVE CENTS', spots:0,  notches:0, mark:'none',  dither:2,  petals:5,  d:1.55 },
  { key:'1',   label:'1',   words:'ONE DOLLAR',        spots:3,  notches:2, mark:'bar',   dither:4,  petals:7,  d:1.62 },
  { key:'5',   label:'5',   words:'FIVE DOLLARS',      spots:4,  notches:3, mark:'dot1',  dither:6,  petals:8,  d:1.70 },
  { key:'25',  label:'25',  words:'TWENTY-FIVE',       spots:6,  notches:4, mark:'dot3',  dither:9,  petals:9,  d:1.66 },
  { key:'100', label:'100', words:'ONE HUNDRED',       spots:8,  notches:6, mark:'ring',  dither:12, petals:11, d:1.74 },
  { key:'500', label:'500', words:'FIVE HUNDRED',      spots:12, notches:8, mark:'cross', dither:15, petals:13, d:1.80 },
];

/* Direction A — traditional poker order, desaturated and warmed.
   Familiar enough to learn in one hand, none of the casino glare. */
/* `mark`  — inner disc + numeral: whatever contrasts with the base.
   `spot`  — edge spots, always the pale ink. Kept separate from `mark`
             because dark bars on a light base made $1 read *darker*
             than $25 in greyscale, inverting the value ladder. Cream
             spots keep the rim light on light chips, so overall
             lightness still tracks denomination. */
const PAL_A = {
  '25c':{ base:'#ded7c6', mark:'#221e18', spot:'#f4efe4', ink2:'#b8ae97' },  /* bone    L≈.84 */
  '1':  { base:'#d9a94e', mark:'#221e18', spot:'#f7f0dd', ink2:'#a8762a' },  /* ochre   L≈.68 */
  '5':  { base:'#c25f4f', mark:'#f4efe4', spot:'#f4efe4', ink2:'#8e3a2c' },  /* oxblood L≈.45 */
  '25': { base:'#2f6650', mark:'#f4efe4', spot:'#f4efe4', ink2:'#1b4234' },  /* pine    L≈.35 */
  '100':{ base:'#4b3560', mark:'#f4efe4', spot:'#f4efe4', ink2:'#2e1f3d' },  /* plum    L≈.24 */
  '500':{ base:'#171512', mark:'#f4efe4', spot:'#f4efe4', ink2:'#000000' },  /* ink     L≈.09 */
};

/* Direction C — wood, stone and bakelite. No poker in the palette. */
const PAL_C = {
  '25c':'#ded5c2', '1':'#c9a06a', '5':'#a86a5c',
  '25':'#6d7f6a', '100':'#4a5560', '500':'#2a2724',
};

const PAPER = '#f4f1ea';

/* ── seeded PRNG ──────────────────────────────────────────────
   The pot scatter must be identical on every player's device —
   shared physical reality is the whole premise of the app, so
   scatter is derived, never random. Same function, same seed,
   same pot. */
function mulberry32(a){
  return function(){
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
const pt  = (x,y) => x.toFixed(2)+','+y.toFixed(2);

/* Points evenly spaced round a rim, starting at 12 o'clock. */
function ring(n, r, phase=0){
  const out=[];
  for(let i=0;i<n;i++){
    const a = phase + (i/n)*Math.PI*2 - Math.PI/2;
    out.push([Math.cos(a)*r, Math.sin(a)*r, a]);
  }
  return out;
}

/* ─────────────────────────────────────────────────────────────
   A — SCREEN-PRINTED TOKEN
   Flat fills, zero gradients. Hard offset shadow (no blur —
   blur is what makes flat art look unsure of itself). One
   deliberate 1px ink misregistration, because a screen print
   that registers perfectly doesn't look printed.
   ───────────────────────────────────────────────────────────── */
function chipA(d, S){
  const p = PAL_A[d.key], r = S/2, c = r;
  const fs = S*(d.label.length>2 ? 0.235 : d.label==='25¢' ? 0.20 : 0.30);
  let s = `<svg class="specimen" width="${S+5}" height="${S+6}" viewBox="-2 -2 ${S+7} ${S+8}">`;

  /* hard shadow */
  s += `<circle cx="${c+2.5}" cy="${c+3.5}" r="${r}" fill="#14120f" opacity="0.17"/>`;

  /* misregistered second ink, peeking out top-left */
  s += `<circle cx="${c-1}" cy="${c-1}" r="${r}" fill="${p.ink2}" opacity="0.55"/>`;

  /* body */
  s += `<circle cx="${c}" cy="${c}" r="${r}" fill="${p.base}"/>`;

  /* edge spots — cut as flat bars through the rim */
  const spotW = d.spots > 8 ? 0.055 : d.spots > 4 ? 0.075 : 0.10;
  ring(d.spots, 0).forEach((_,i)=>{
    const a0 = (i/d.spots)*Math.PI*2 - Math.PI/2 - spotW*Math.PI;
    const a1 = a0 + spotW*Math.PI*2;
    const rO = r, rI = r*0.735;
    s += `<path d="M${pt(c+Math.cos(a0)*rI, c+Math.sin(a0)*rI)}`
      +  `L${pt(c+Math.cos(a0)*rO, c+Math.sin(a0)*rO)}`
      +  `A${rO},${rO} 0 0 1 ${pt(c+Math.cos(a1)*rO, c+Math.sin(a1)*rO)}`
      +  `L${pt(c+Math.cos(a1)*rI, c+Math.sin(a1)*rI)}`
      +  `A${rI},${rI} 0 0 0 ${pt(c+Math.cos(a0)*rI, c+Math.sin(a0)*rI)}Z" fill="${p.spot}"/>`;
  });

  /* inner disc + numeral */
  s += `<circle cx="${c}" cy="${c}" r="${r*0.655}" fill="${p.mark}"/>`;
  s += `<circle cx="${c}" cy="${c}" r="${r*0.585}" fill="none" stroke="${p.base}" stroke-width="${S*0.014}"/>`;
  s += `<text x="${c}" y="${c}" fill="${p.base}" font-family="var(--sans)" font-size="${fs}"`
    +  ` font-weight="700" letter-spacing="-0.03em" text-anchor="middle" dominant-baseline="central">${esc(d.label)}</text>`;

  /* grain, clipped to the disc */
  s += `<clipPath id="cA${d.key}${S}"><circle cx="${c}" cy="${c}" r="${r}"/></clipPath>`
    +  `<g clip-path="url(#cA${d.key}${S})" style="mix-blend-mode:multiply" opacity="0.30">`
    +  `<rect x="0" y="0" width="${S}" height="${S}" filter="url(#grain)"/></g>`;

  return s + '</svg>';
}

/* ─────────────────────────────────────────────────────────────
   B — BANKNOTE / INTAGLIO
   No fills. Everything is line. The rosette is a real
   hypotrochoid, the same curve family engine-turning lathes cut
   into banknote plates — which is why it reads as money and not
   as decoration.
       x = (R−r)·cos t + d·cos(kt)
       y = (R−r)·sin t − d·sin(kt),  k = (R−r)/r
   With r = R/n the curve closes after one turn with n petals.
   ───────────────────────────────────────────────────────────── */
function guilloche(R, petals, dRatio, steps=760){
  const r = R/petals, k = (R-r)/r, d = r*dRatio, out=[];
  for(let i=0;i<=steps;i++){
    const t = (i/steps)*Math.PI*2;
    out.push([ (R-r)*Math.cos(t) + d*Math.cos(k*t), (R-r)*Math.sin(t) - d*Math.sin(k*t) ]);
  }
  return 'M' + out.map(p=>pt(p[0],p[1])).join('L') + 'Z';
}

function chipB(d, S){
  const r = S/2, c = r, big = S >= 110;
  const lw = Math.max(0.32, S*0.0058);
  let s = `<svg class="specimen" width="${S+4}" height="${S+5}" viewBox="-2 -2 ${S+6} ${S+7}">`;

  s += `<circle cx="${c+1}" cy="${c+2}" r="${r}" fill="#14120f" opacity="0.07"/>`;
  s += `<circle cx="${c}" cy="${c}" r="${r}" fill="#f7f3e9"/>`;

  /* engine-turned double border */
  s += `<circle cx="${c}" cy="${c}" r="${r-lw}"       fill="none" stroke="#3d332a" stroke-width="${lw*1.7}"/>`;
  s += `<circle cx="${c}" cy="${c}" r="${r*0.905}" fill="none" stroke="#3d332a" stroke-width="${lw}"/>`;

  /* halftone value ring: dot size carries the denomination */
  const hn = 48, hr = (d.dither/15)*S*0.0125 + S*0.003;
  ring(hn, r*0.955).forEach(([x,y])=>{
    s += `<circle cx="${c+x}" cy="${c+y}" r="${hr.toFixed(2)}" fill="#3d332a" opacity="0.72"/>`;
  });

  /* the rosette, twice, counter-rotated */
  s += `<g transform="translate(${c},${c})" fill="none" stroke="#2f2620" stroke-width="${lw}" stroke-linejoin="round">`
    +  `<path d="${guilloche(r*0.855, d.petals, d.d)}" opacity="0.85"/>`
    +  `<path d="${guilloche(r*0.66,  d.petals, d.d*0.92)}" opacity="0.5" transform="rotate(${180/d.petals})"/>`
    +  `</g>`;

  /* cleared cartouche + numeral */
  s += `<ellipse cx="${c}" cy="${c}" rx="${r*0.40}" ry="${r*0.30}" fill="#f7f3e9" opacity="0.94"/>`;
  s += `<ellipse cx="${c}" cy="${c}" rx="${r*0.40}" ry="${r*0.30}" fill="none" stroke="#2f2620" stroke-width="${lw*0.9}"/>`;
  s += `<text x="${c}" y="${c}" fill="#241d18" font-family="var(--serif)"`
    +  ` font-size="${S*(d.label.length>2?0.20:d.label==='25¢'?0.175:0.26)}" font-weight="600"`
    +  ` text-anchor="middle" dominant-baseline="central">${esc(d.label)}</text>`;

  /* lettering round the rim — only legible at detail size */
  if(big){
    s += `<defs><path id="arc${d.key}${S}" d="M ${c-r*0.79} ${c} A ${r*0.79} ${r*0.79} 0 0 1 ${c+r*0.79} ${c}"/></defs>`
      +  `<text font-family="var(--serif)" font-size="${S*0.052}" letter-spacing="0.22em" fill="#2f2620" opacity="0.8">`
      +  `<textPath href="#arc${d.key}${S}" startOffset="50%" text-anchor="middle">${esc(d.words)}</textPath></text>`;
  }
  return s + '</svg>';
}

/* ─────────────────────────────────────────────────────────────
   C — BOARD-GAME TOKEN
   Go stones and backgammon checkers. Matte, one colour, a 1px
   bevel and nothing else. No numerals anywhere: denomination is
   notch count on the rim plus a centre mark, read like domino
   pips. Notches are genuinely subtracted via a mask rather than
   painted over, so the silhouette is real and stacks correctly.
   ───────────────────────────────────────────────────────────── */
function chipC(d, S){
  const col = PAL_C[d.key], r = S/2, c = r, id = `mC${d.key}${S}`;
  const light = ['25c','1'].includes(d.key);
  const mk = light ? '#2b2620' : 'rgba(255,255,255,.82)';
  let s = `<svg class="specimen" width="${S+4}" height="${S+7}" viewBox="-2 -2 ${S+6} ${S+9}">`;

  /* notch mask */
  s += `<defs><mask id="${id}"><circle cx="${c}" cy="${c}" r="${r}" fill="#fff"/>`;
  ring(d.notches, r).forEach(([x,y])=>{
    s += `<circle cx="${c+x}" cy="${c+y}" r="${S*0.072}" fill="#000"/>`;
  });
  s += `</mask></defs>`;

  s += `<g mask="url(#${id})" filter="url(#matteShadow)">`;
  s += `<circle cx="${c}" cy="${c}" r="${r}" fill="${col}"/>`;
  /* bevel: light from top-left, shade bottom-right */
  s += `<path d="M${pt(c-r*0.707,c-r*0.707)} A${r},${r} 0 0 1 ${pt(c+r*0.707,c-r*0.707)}"`
    +  ` fill="none" stroke="#fff" stroke-opacity="0.30" stroke-width="${S*0.028}"/>`;
  s += `<path d="M${pt(c+r*0.707,c+r*0.707)} A${r},${r} 0 0 1 ${pt(c-r*0.707,c+r*0.707)}"`
    +  ` fill="none" stroke="#000" stroke-opacity="0.20" stroke-width="${S*0.028}"/>`;
  s += `<circle cx="${c}" cy="${c}" r="${r*0.80}" fill="none" stroke="${mk}" stroke-opacity="0.22" stroke-width="${S*0.012}"/>`;
  s += `</g>`;

  /* centre mark — the denomination, read as pips */
  const dot = (x,y,rr)=>`<circle cx="${c+x}" cy="${c+y}" r="${rr}" fill="${mk}"/>`;
  const u = S*0.075;
  /* $1 is a bar, not a dot — a dot here was indistinguishable from $5's
     single pip once colour was removed, which defeated the whole point
     of shape-coding. Bar vs dot vs three-dots reads at any size. */
  if(d.mark==='bar')   s += `<rect x="${c-u*1.5}" y="${c-u*0.28}" width="${u*3}" height="${u*0.56}"`
                          + ` rx="${u*0.28}" fill="${mk}"/>`;
  if(d.mark==='dot1')  s += dot(0,0,u*0.72);
  if(d.mark==='dot3')  s += dot(0,-u*1.5,u*0.56) + dot(-u*1.35,u*0.85,u*0.56) + dot(u*1.35,u*0.85,u*0.56);
  if(d.mark==='ring')  s += `<circle cx="${c}" cy="${c}" r="${u*1.5}" fill="none" stroke="${mk}" stroke-width="${u*0.52}"/>`;
  if(d.mark==='cross') s += `<path d="M${pt(c-u*1.6,c)}L${pt(c+u*1.6,c)}M${pt(c,c-u*1.6)}L${pt(c,c+u*1.6)}"`
                          + ` stroke="${mk}" stroke-width="${u*0.52}" stroke-linecap="round"/>`;
  return s + '</svg>';
}

/* ─────────────────────────────────────────────────────────────
   D — 1-BIT DITHERED
   Two colours, full stop. Every "grey" is a real Bayer 4×4
   ordered dither, generated from the matrix rather than faked
   with noise — so it tiles seamlessly and stays hard-edged.
   The payoff: dither density IS the denomination, so the value
   ladder and the art style are one decision, and it passes the
   greyscale test by construction.
   ───────────────────────────────────────────────────────────── */
const BAYER4 = [[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]];
let ditherReady = false;
function installDither(){
  if(ditherReady) return; ditherReady = true;
  const svgNS='http://www.w3.org/2000/svg';
  const host=document.createElementNS(svgNS,'svg');
  host.setAttribute('width','0'); host.setAttribute('height','0');
  host.style.position='absolute';
  const defs=document.createElementNS(svgNS,'defs');
  [...new Set(DENOMS.map(d=>d.dither))].forEach(k=>{
    const p=document.createElementNS(svgNS,'pattern');
    p.id='dith'+k;
    p.setAttribute('width','4'); p.setAttribute('height','4');
    p.setAttribute('patternUnits','userSpaceOnUse');
    for(let y=0;y<4;y++) for(let x=0;x<4;x++){
      if(BAYER4[y][x] < k){
        const rc=document.createElementNS(svgNS,'rect');
        rc.setAttribute('x',x); rc.setAttribute('y',y);
        rc.setAttribute('width','1'); rc.setAttribute('height','1');
        rc.setAttribute('fill','#fff');
        rc.setAttribute('shape-rendering','crispEdges');
        p.appendChild(rc);
      }
    }
    defs.appendChild(p);
  });
  host.appendChild(defs); document.body.appendChild(host);
}

function chipD(d, S){
  installDither();
  const r=S/2, c=r, sw=Math.max(1.6,S*0.026);
  let s = `<svg class="specimen" width="${S+4}" height="${S+5}" viewBox="-2 -2 ${S+6} ${S+7}">`;
  s += `<g filter="url(#bloom)">`;
  s += `<circle cx="${c}" cy="${c}" r="${r-sw/2}" fill="#000" stroke="#fff" stroke-width="${sw}"/>`;
  s += `<circle cx="${c}" cy="${c}" r="${r-sw}" fill="url(#dith${d.dither})"/>`;
  /* knocked-out centre so the numeral stays readable over dither */
  s += `<circle cx="${c}" cy="${c}" r="${r*0.50}" fill="#000" stroke="#fff" stroke-width="${sw*0.62}"/>`;
  s += `<text x="${c}" y="${c+S*0.006}" fill="#fff" font-family="var(--mono)"`
    +  ` font-size="${S*(d.label.length>2?0.185:d.label==='25¢'?0.155:0.245)}" font-weight="700"`
    +  ` letter-spacing="-0.02em" text-anchor="middle" dominant-baseline="central">${esc(d.label)}</text>`;
  s += `</g>`;
  s += `<circle cx="${c}" cy="${c}" r="${r}" fill="url(#scan)"/>`;
  return s + '</svg>';
}

const CHIP = { A:chipA, B:chipB, C:chipC, D:chipD };

/* ─────────────────────────────────────────────────────────────
   Edge-on stack, ~15° camera.
   This is the view that matters most in the real app: across a
   table you read a stack by its side, not its face. Each chip
   contributes an edge band; only the top chip shows a face. The
   edge stripes are the same code as the face spots, which is
   what lets a stack be legible with no label attached.
   ───────────────────────────────────────────────────────────── */
function stack(dir, d, n, S=52){
  const rx=S/2, ry=S*0.145, step=S*0.113;
  const H = ry*2 + step*(n-1) + 8;
  const edgeCol = dir==='A' ? PAL_A[d.key].base
                : dir==='C' ? PAL_C[d.key]
                : dir==='B' ? '#e6dfd0' : '#000';
  const edgeDark = dir==='A' ? PAL_A[d.key].ink2
                 : dir==='C' ? 'rgba(0,0,0,.26)'
                 : dir==='B' ? '#cfc5b2' : '#000';
  const spotCol = dir==='A' ? PAL_A[d.key].spot
                : dir==='C' ? 'rgba(0,0,0,.34)'
                : dir==='B' ? '#3d332a' : '#fff';

  let s = `<svg class="specimen" width="${S+8}" height="${H+8}" viewBox="-4 -4 ${S+12} ${H+12}">`;

  /* contact shadow on the felt */
  s += `<ellipse cx="${rx}" cy="${H-4}" rx="${rx*1.02}" ry="${ry*0.72}"
         fill="#14120f" opacity="${dir==='D'?0.5:0.16}"/>`;

  for(let i=0;i<n;i++){
    const cy = H - 6 - ry - i*step;
    /* edge band: the cylinder side */
    s += `<path d="M${pt(0,cy)} L${pt(0,cy+step)} A${rx},${ry} 0 0 0 ${pt(S,cy+step)} L${pt(S,cy)}
           A${rx},${ry} 0 0 1 ${pt(0,cy)} Z" fill="${edgeCol}"/>`;
    s += `<path d="M${pt(0,cy+step*0.55)} L${pt(0,cy+step)} A${rx},${ry} 0 0 0 ${pt(S,cy+step)}
           L${pt(S,cy+step*0.55)} A${rx},${ry} 0 0 1 ${pt(0,cy+step*0.55)} Z"
           fill="${edgeDark}" opacity="${dir==='D'?0:0.45}"/>`;
    /* edge stripes: same denomination code, seen from the side */
    if(d.spots){
      const vis = Math.min(d.spots, 9);
      for(let k=0;k<vis;k++){
        const t = (k+0.5)/vis, x = t*S;
        const w = d.spots>8 ? S*0.026 : d.spots>4 ? S*0.036 : S*0.05;
        const yOff = Math.sin(t*Math.PI)*ry*0.30;
        s += `<rect x="${(x-w/2).toFixed(2)}" y="${(cy+step*0.10+yOff*0.4).toFixed(2)}"
               width="${w.toFixed(2)}" height="${(step*0.78).toFixed(2)}" rx="${(w*0.3).toFixed(2)}"
               fill="${spotCol}" opacity="${dir==='D'?0.95:0.82}"/>`;
      }
    }
    /* thin seam between chips */
    s += `<ellipse cx="${rx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="none"
           stroke="${dir==='D'?'#fff':'#14120f'}" stroke-opacity="${dir==='D'?0.9:0.13}" stroke-width="0.7"/>`;
  }

  /* top face, squashed to the camera angle */
  const topY = H - 6 - ry - (n-1)*step;
  const face = CHIP[dir](d, S);
  const inner = face.replace(/^<svg[^>]*>/,'').replace(/<\/svg>$/,'');
  s += `<g transform="translate(${rx},${topY}) scale(1,${(ry*2/S).toFixed(3)}) translate(${-rx},${-rx})">${inner}</g>`;

  return s + '</svg>';
}

/* ─────────────────────────────────────────────────────────────
   Pot cluster — chips scattered in a recessed well.
   Positions come from mulberry32 seeded on the direction, so
   the arrangement is stable across reloads. In the real app the
   seed is (handId, actionIndex) and every device draws the same
   pot down to the pixel.
   ───────────────────────────────────────────────────────────── */
function pot(dir, W=300, H=150){
  const rnd = mulberry32(0x9E37 + dir.charCodeAt(0));
  const S = 44;
  const picks = ['5','5','1','25','1','5','25','100','1','5','25','1','500','5','1'];
  const wrx = W*0.40, wry = H*0.40;
  let s = `<svg class="specimen" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  s += `<ellipse cx="${W/2}" cy="${H/2}" rx="${wrx}" ry="${wry}"
         fill="url(#${dir==='D'?'wellDark':'well'})"/>`;
  /* The lip. Done in SVG rather than a CSS inset box-shadow, which can't
     follow the ellipse and leaves a visible second rim around it. Two
     parts: a hairline all the way round, plus a soft occlusion arc across
     the far edge only — that asymmetry is what makes it read as a hole
     lit from above rather than a flat disc. */
  s += `<ellipse cx="${W/2}" cy="${H/2}" rx="${wrx}" ry="${wry}" fill="none"
         stroke="${dir==='D'?'rgba(255,255,255,.13)':'rgba(20,18,15,.13)'}" stroke-width="1"/>`;
  s += `<path d="M${pt(W/2-wrx*0.985,H/2)} A${wrx*0.985},${wry*0.985} 0 0 1 ${pt(W/2+wrx*0.985,H/2)}"
         fill="none" stroke="${dir==='D'?'rgba(0,0,0,.9)':'rgba(20,18,15,.22)'}"
         stroke-width="5" stroke-linecap="round" opacity="0.85"/>`;

  /* Spread is tuned so the pile fills the well rather than sitting as a
     small heap in a big dish — the pot should look like money has been
     pushed into it, not arranged. */
  const laid = picks.map((k,i)=>{
    const a = rnd()*Math.PI*2, rad = Math.sqrt(rnd());
    return {
      d: DENOMS.find(x=>x.key===k),
      x: W/2 + Math.cos(a)*rad*(wrx-S*0.66) - S/2,
      y: H/2 + Math.sin(a)*rad*(wry-S*0.42) - S*0.30,
      rot: (rnd()-0.5)*44, i
    };
  }).sort((a,b)=>a.y-b.y);

  laid.forEach(o=>{
    const face = CHIP[dir](o.d, S).replace(/^<svg[^>]*>/,'').replace(/<\/svg>$/,'');
    s += `<g transform="translate(${o.x.toFixed(1)},${o.y.toFixed(1)}) rotate(${o.rot.toFixed(1)},${S/2},${S/2})
           scale(1,0.86)" opacity="0.99">${face}</g>`;
  });
  return s + '</svg>';
}


/* ─────────────────────────────────────────────────────────────
   Shared SVG defs — grain, matte shadow, CRT bloom, scanlines and
   the recessed felt gradients. Injected once per document so the
   ids referenced by the chip builders always resolve.
   ───────────────────────────────────────────────────────────── */
function installDefs(){
  if(document.getElementById("chipDefs")) return;
  const host = document.createElement("div");
  host.id = "chipDefs";
  host.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
  host.innerHTML = `<svg width="0" height="0" aria-hidden="true"><defs>

    <!-- riso-ish grain, multiplied over direction A -->
    <filter id="grain" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.82" numOctaves="4" stitchTiles="stitch" result="n"/>
      <feColorMatrix in="n" type="saturate" values="0"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.55" intercept="0"/></feComponentTransfer>
    </filter>

    <!-- soft matte shadow for direction C -->
    <filter id="matteShadow" x="-40%" y="-40%" width="180%" height="180%">
      <feDropShadow dx="0" dy="2.5" stdDeviation="2.6" flood-color="#3a3226" flood-opacity="0.30"/>
    </filter>

    <!-- CRT bloom for direction D -->
    <filter id="bloom" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="1.5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>

    <!-- scanlines for direction D -->
    <pattern id="scan" width="3" height="3" patternUnits="userSpaceOnUse">
      <rect width="3" height="1.1" fill="#000" opacity="0.34"/>
    </pattern>

    <!-- Recessed felt well. Vertical, not radial: light comes from above,
         so the far inner wall sits in shadow and the near lip catches it.
         A radial dark-in-the-centre gradient reads as a mound, not a hole. -->
    <linearGradient id="well" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#c2b9a4"/>
      <stop offset="38%"  stop-color="#d6cebb"/>
      <stop offset="100%" stop-color="#eae4d7"/>
    </linearGradient>
    <linearGradient id="wellDark" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#000"/>
      <stop offset="42%"  stop-color="#0d0d0f"/>
      <stop offset="100%" stop-color="#202024"/>
    </linearGradient>

  </defs></svg>`;
  document.body.insertBefore(host, document.body.firstChild);
}
if(document.readyState === "loading"){
  document.addEventListener("DOMContentLoaded", installDefs);
} else { installDefs(); }
