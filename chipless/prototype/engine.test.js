/* Tests for engine.js. Plain node, no framework:
     node chipless/prototype/engine.test.js
   The evaluator and the pot maths are the only parts of this
   prototype with a provably right answer, so they get tested. */

const E = require('./engine.js');
const { evaluate7, categoryName, parseCard, buildPots, awardPots, Table,
        breakdown, money, straightTop } = E;

let pass = 0, fail = 0;
function ok(cond, label, extra){
  if(cond){ pass++; }
  else { fail++; console.log('  FAIL  ' + label + (extra ? '\n        ' + extra : '')); }
}
function hand(str){ return str.split(' ').map(parseCard); }
function evalStr(str){ return evaluate7(hand(str)); }
function section(n){ console.log('\n' + n); }

/* ── categories ─────────────────────────────────────────────── */
section('categories');
const cases = [
  ['As Ks Qs Js Ts 2c 3d', 'Straight flush'],
  ['9h 9c 9d 9s 2c 5d 7h', 'Quads'],
  ['8h 8c 8d 4s 4c 9d 2h', 'Full house'],
  ['2h 7h 9h Jh Kh 3c 4d', 'Flush'],
  ['5c 6d 7h 8s 9c Ah Kd', 'Straight'],
  ['Qh Qc Qd 2s 7c 9d 4h', 'Trips'],
  ['Ah Ac 8d 8s 3c 5d 9h', 'Two pair'],
  ['Th Tc 4d 7s 9c 2d 3h', 'Pair'],
  ['Ah Kc 9d 7s 4c 2d 3h', 'Straight'],   /* A-2-3-4-... no: 2,3,4,7,9 — see below */
];
/* that last one is a deliberate trap: 2,3,4,7,9,K,A is NOT a straight */
cases[8] = ['Ah Kc 9d 7s 4c 2d 5h', 'High card'];
for(const [h, want] of cases){
  const got = categoryName(evalStr(h));
  ok(got === want, `${h} → ${want}`, `got ${got}`);
}

/* ── the wheel, the classic off-by-one ──────────────────────── */
section('wheel straight (A-2-3-4-5)');
ok(categoryName(evalStr('Ah 2c 3d 4s 5h 9c Kd')) === 'Straight', 'wheel is a straight');
/* the wheel is the WORST straight — 6-high must beat it */
ok(evalStr('2h 3c 4d 5s 6h 9c Kd') > evalStr('Ah 2c 3d 4s 5h 9c Kd'),
   '6-high straight beats the wheel');
/* and the wheel must not be read as ace-high */
ok(evalStr('Ah 2c 3d 4s 5h 9c Kd') < evalStr('Th Jc Qd Ks Ah 2c 3d'),
   'broadway beats the wheel');
ok(straightTop((1<<12)|(1<<0)|(1<<1)|(1<<2)|(1<<3)) === 3, 'wheel top card is the 5');

/* steel wheel — wheel straight flush */
ok(categoryName(evalStr('Ah 2h 3h 4h 5h 9c Kd')) === 'Straight flush', 'steel wheel');

/* ── ordering between categories ────────────────────────────── */
section('category ordering');
const ladder = [
  ['high card', 'Ah Kc 9d 7s 4c 2d 3h'],
  ['pair',      'Th Tc 4d 7s 9c 2d 3h'],
  ['two pair',  'Ah Ac 8d 8s 3c 5d 9h'],
  ['trips',     'Qh Qc Qd 2s 7c 9d 4h'],
  ['straight',  '5c 6d 7h 8s 9c Ah Kd'],
  ['flush',     '2h 7h 9h Jh Kh 3c 4d'],
  ['boat',      '8h 8c 8d 4s 4c 9d 2h'],
  ['quads',     '9h 9c 9d 9s 2c 5d 7h'],
  ['str flush', 'As Ks Qs Js Ts 2c 3d'],
];
for(let i = 1; i < ladder.length; i++){
  ok(evalStr(ladder[i][1]) > evalStr(ladder[i-1][1]),
     `${ladder[i][0]} beats ${ladder[i-1][0]}`);
}
/* the one people always get wrong */
ok(evalStr('2h 7h 9h Jh Kh 3c 4d') > evalStr('5c 6d 7h 8s 9c Ah Kd'),
   'flush beats straight');

/* ── kickers ────────────────────────────────────────────────── */
section('kickers and ties');
ok(evalStr('Ah Ac Kd 7s 4c 2d 3h') > evalStr('Ah Ac Qd 7s 4c 2d 3h'),
   'aces with king kicker beats aces with queen');
ok(evalStr('Ah Ac Kd Ks 4c 2d 3h') > evalStr('Ah Ac Qd Qs 4c 2d 3h'),
   'aces-and-kings beats aces-and-queens');
ok(evalStr('Ah Ac Kd 7s 4c 2d 3h') === evalStr('Ad As Kh 7c 4d 2h 3c'),
   'same hand in different suits ties exactly');
/* two pair where the 5th card comes from the third pair */
ok(categoryName(evalStr('Ah Ac Kd Ks Qh Qc 2d')) === 'Two pair',
   'three pairs is still two pair');
ok(evalStr('Ah Ac Kd Ks Qh Qc 2d') === evalStr('Ah Ac Kd Ks Qh 2c 3d'),
   'third pair only contributes its rank as kicker');

/* ── side pots ──────────────────────────────────────────────── */
section('side pots');
{
  /* the mockup's scenario: Sam all-in for 600, three others in for 1000 */
  const players = [
    { id:'you',  contributed:1000, folded:false },
    { id:'jony', contributed:1000, folded:false },
    { id:'mike', contributed:1000, folded:false },
    { id:'sam',  contributed:600,  folded:false },
  ];
  const pots = buildPots(players);
  ok(pots.length === 2, 'two pots', JSON.stringify(pots));
  ok(pots[0].amount === 2400, 'main pot is 4 × 600 = 2400', 'got ' + pots[0].amount);
  ok(pots[0].eligible.length === 4, 'everyone eligible for the main pot');
  ok(pots[1].amount === 1200, 'side pot is 3 × 400 = 1200', 'got ' + pots[1].amount);
  ok(!pots[1].eligible.includes('sam'), 'sam not eligible for the side pot');
  ok(pots[0].amount + pots[1].amount === 3600, 'pots sum to total contributed');

  /* sam wins the main, you win the side */
  const payouts = awardPots(players, pots, { you:5, jony:3, mike:2, sam:9 });
  ok(payouts.sam === 2400, 'sam takes only the main pot', 'got ' + payouts.sam);
  ok(payouts.you === 1200, 'you take the side pot', 'got ' + payouts.you);
}
{
  /* a folded player's money stays in the pot but they can't win it */
  const players = [
    { id:'a', contributed:500, folded:false },
    { id:'b', contributed:500, folded:true  },
  ];
  const pots = buildPots(players);
  const total = pots.reduce((s,p)=>s+p.amount,0);
  ok(total === 1000, 'folded contributions remain in the pot', 'got ' + total);
  const payouts = awardPots(players, pots, { a:7 });
  ok(payouts.a === 1000, 'the last player standing takes it all');
}
{
  /* odd split — no cent may be created or destroyed */
  const players = [
    { id:'a', contributed:501, folded:false },
    { id:'b', contributed:500, folded:false },
  ];
  const pots = buildPots(players);
  const payouts = awardPots(players, pots, { a:5, b:5 });
  const out = payouts.a + payouts.b;
  ok(out === 1001, 'odd split conserves every cent', `${payouts.a}+${payouts.b}=${out}`);
}

/* ── statistical validation of the evaluator ─────────────────
   Hand-picked cases can share a blind spot with the code they're
   testing. Category frequencies over many random 7-card hands
   can't: they only come out right if the evaluator is right.
   Tolerance is ±4 sigma on the Poisson count, so rare categories
   get the wide band they deserve instead of a flat percentage. */
section('category frequencies vs published Hold\'em figures');
{
  const EXPECTED = {                    /* % of C(52,7) */
    'High card':17.412, 'Pair':43.822, 'Two pair':23.496, 'Trips':4.829,
    'Straight':4.619,   'Flush':3.025, 'Full house':2.596, 'Quads':0.168,
    'Straight flush':0.0311,
  };
  const N = 200000, rnd = E.mulberry32(20260808);
  const counts = new Array(9).fill(0);
  const deck = Array.from({length:52},(_,i)=>i);
  for(let n = 0; n < N; n++){
    for(let i = 51; i > 44; i--){       /* partial shuffle: last 7 only */
      const j = Math.floor(rnd()*(i+1));
      [deck[i],deck[j]] = [deck[j],deck[i]];
    }
    counts[E.categoryOf(evaluate7(deck.slice(45)))]++;
  }
  E.CAT_NAMES.forEach((name,i)=>{
    const expCount = EXPECTED[name]/100 * N;
    const band = 4 * Math.sqrt(expCount);
    ok(Math.abs(counts[i] - expCount) <= band,
       `${name} ~ ${EXPECTED[name]}%`,
       `expected ${expCount.toFixed(0)}±${band.toFixed(0)}, got ${counts[i]}`);
  });
}

/* ── full hands: chip conservation ───────────────────────────
   The invariant that catches almost everything. Play a lot of
   hands with bots on both sides and assert the total money on the
   table never changes. */
section('chip conservation over 400 hands');
{
  let worstDrift = 0, handsPlayed = 0, showdowns = 0, allIns = 0, folds = 0;
  let errors = [];

  for(let seed = 1; seed <= 400; seed++){
    const t = new Table({ seed, buyin: 5000 });
    const startTotal = t.players.reduce((s,p)=>s+p.stack, 0);

    try {
      for(let h = 0; h < 6; h++){
        if(t.players.filter(p=>p.stack>0).length < 2) break;
        t.deal();
        let guard = 0;
        while(!t.handOver && guard++ < 200){
          const p = t.current();
          if(!p) break;
          t.act(t.botAction());
        }
        if(guard >= 200) errors.push(`seed ${seed} hand ${h}: action loop did not terminate`);
        handsPlayed++;
        if(t.result && t.result.showdown) showdowns++;
        if(t.result && !t.result.showdown) folds++;
        if(t.players.some(p=>p.allIn)) allIns++;

        const now = t.players.reduce((s,p)=>s+p.stack, 0);
        const drift = Math.abs(now - startTotal);
        if(drift > worstDrift) worstDrift = drift;
        if(drift !== 0) errors.push(`seed ${seed} hand ${h}: drift ${drift} cents`);

        if(t.players.some(p=>p.stack < 0))
          errors.push(`seed ${seed} hand ${h}: negative stack`);
      }
    } catch(e){
      errors.push(`seed ${seed}: threw ${e.message}`);
    }
  }

  ok(errors.length === 0, `${handsPlayed} hands, no errors`,
     errors.slice(0,6).join('\n        ') + (errors.length>6?`\n        …and ${errors.length-6} more`:''));
  ok(worstDrift === 0, 'total chips never drift', 'worst drift ' + worstDrift);
  /* sanity: the bots must actually be doing different things */
  ok(showdowns > 0 && folds > 0, `mix of outcomes (${showdowns} showdowns, ${folds} uncontested)`);
  ok(allIns > 0, `all-ins do occur (${allIns} hands)`);
  console.log(`  ${handsPlayed} hands · ${showdowns} showdowns · ${folds} uncontested · ${allIns} with an all-in`);
}

/* ── denomination breakdown ─────────────────────────────────── */
section('chip breakdown');
{
  const cases = [[1200,'$12.00'], [25,'$0.25'], [5000,'$50.00'], [3775,'$37.75']];
  for(const [cents] of cases){
    const chips = breakdown(cents);
    const sum = chips.reduce((s,k)=>{
      const d = E.DENOM_CENTS.find(x=>x.key===k); return s + d.c;
    }, 0);
    ok(sum === cents, `breakdown(${money(cents)}) sums back exactly`,
       `${chips.join('+')} = ${sum}`);
  }
  ok(breakdown(1200).join(',') === '5,5,1,1', '$12 is two $5 and two $1',
     breakdown(1200).join(','));
  ok(breakdown(0).length === 0, 'zero is no chips');
}

/* ── racking ────────────────────────────────────────────────── */
section('racking a buy-in');
{
  for(const cents of [5000, 2500, 10000, 175, 0, 33325]){
    const r = E.rack(cents);
    ok(E.rackTotal(r) === cents, `rack(${money(cents)}) sums back exactly`,
       JSON.stringify(r) + ' = ' + E.rackTotal(r));
  }
  const fifty = E.rack(5000);
  ok((fifty['1'] || 0) >= 4, '$50 buy-in includes small chips you can actually bet',
     JSON.stringify(fifty));
  ok(Object.keys(fifty).length >= 3, '$50 buy-in spans several denominations',
     JSON.stringify(fifty));
  console.log('  $50 racks as', Object.entries(fifty).map(([k,n])=>`${n}×${k}`).join(', '));
}

/* ── summary ────────────────────────────────────────────────── */
console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail ? 1 : 0);
