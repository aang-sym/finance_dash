/* ══════════════════════════════════════════════════════════════
   engine.js — Texas Hold'em, enough of it to be honest.

   Deliberately real rather than scripted: the payout is the thing
   the prototype exists to test, and winning feels different when
   you earned it. An arbitrary win teaches us nothing.

   All money is in INTEGER CENTS. No floats anywhere — a pot that
   drifts by a cent is a pot you can't trust.

   No DOM, no audio, no rendering. Runnable in node, which is how
   it gets tested before the UI exists.
   ══════════════════════════════════════════════════════════════ */

/* ── PRNG ─────────────────────────────────────────────────────
   Same mulberry32 as chips.js. Seeded so a hand can be replayed
   exactly, which matters for both debugging and the shared-pot
   guarantee in the real app. */
function mulberry32(a){
  return function(){
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

/* ── cards ────────────────────────────────────────────────────
   A card is an integer 0..51:  rank = c >> 2  (0=2 … 12=A)
                                suit = c & 3   (0=♣ 1=♦ 2=♥ 3=♠)
   Integers rather than objects because the evaluator runs a lot
   and this keeps it branch-free and cheap. */
const RANK_CH = '23456789TJQKA';
const SUIT_CH = ['♣','♦','♥','♠'];
const rankOf = c => c >> 2;
const suitOf = c => c & 3;
const cardStr = c => RANK_CH[rankOf(c)] + SUIT_CH[suitOf(c)];
/* Accepts either glyph or letter suits — 'As' and 'A♠' both work.
   Letters are what anyone actually types into a test or a console. */
const SUIT_LETTER = 'cdhs';
const parseCard = s => {
  const r = RANK_CH.indexOf(s[0].toUpperCase());
  let u = SUIT_CH.indexOf(s[1]);
  if(u < 0) u = SUIT_LETTER.indexOf(s[1].toLowerCase());
  if(r < 0 || u < 0) throw new Error('bad card: ' + s);
  return r*4 + u;
};

function shuffled(rnd){
  const d = Array.from({length:52}, (_,i)=>i);
  for(let i = 51; i > 0; i--){                 /* Fisher–Yates */
    const j = Math.floor(rnd() * (i+1));
    [d[i], d[j]] = [d[j], d[i]];
  }
  return d;
}

/* ══════════════════════════════════════════════════════════════
   Hand evaluation — best 5 of 7.

   Returns a single comparable integer. Layout, high bits first:
     category (4 bits) then five kickers (4 bits each) = 24 bits.
   Packing into one number means comparing hands is just `>`,
   which removes a whole class of tie-breaking bugs.

   Categories: 8 straight flush, 7 quads, 6 full house, 5 flush,
   4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
   ══════════════════════════════════════════════════════════════ */
const CAT_NAMES = ['High card','Pair','Two pair','Trips','Straight',
                   'Flush','Full house','Quads','Straight flush'];

function score(cat, kickers){
  let v = cat;
  for(let i = 0; i < 5; i++) v = (v << 4) | (kickers[i] || 0);
  return v;
}

/* Highest straight in a 13-bit rank mask, or -1. Returns the rank
   of the straight's TOP card. The wheel (A-2-3-4-5) is the one
   special case: ace plays low, and its top card is the 5. */
function straightTop(mask){
  for(let top = 12; top >= 4; top--){
    let ok = true;
    for(let k = 0; k < 5; k++) if(!(mask & (1 << (top - k)))) { ok = false; break; }
    if(ok) return top;
  }
  /* wheel: A,5,4,3,2 */
  const wheel = (1<<12) | (1<<3) | (1<<2) | (1<<1) | (1<<0);
  if((mask & wheel) === wheel) return 3;   /* top card is the 5 (rank index 3) */
  return -1;
}

function evaluate7(cards){
  if(cards.length < 5) throw new Error('need at least 5 cards');

  const bySuit = [[],[],[],[]];
  const rankCount = new Array(13).fill(0);
  let rankMask = 0;

  for(const c of cards){
    const r = rankOf(c);
    bySuit[suitOf(c)].push(r);
    rankCount[r]++;
    rankMask |= 1 << r;
  }

  /* flush / straight flush */
  let flushSuit = -1;
  for(let s = 0; s < 4; s++) if(bySuit[s].length >= 5) flushSuit = s;

  if(flushSuit >= 0){
    let fMask = 0;
    for(const r of bySuit[flushSuit]) fMask |= 1 << r;
    const st = straightTop(fMask);
    if(st >= 0) return score(8, [st,0,0,0,0]);
    const top5 = bySuit[flushSuit].slice().sort((a,b)=>b-a).slice(0,5);
    return score(5, top5);
  }

  /* straight */
  const st = straightTop(rankMask);
  if(st >= 0) return score(4, [st,0,0,0,0]);

  /* grouped by count then rank, both descending — this ordering is
     exactly the kicker order for every remaining category */
  const ranks = [];
  for(let r = 12; r >= 0; r--) if(rankCount[r]) ranks.push(r);
  const byCount = c => ranks.filter(r => rankCount[r] === c);

  const quads = byCount(4), trips = byCount(3), pairs = byCount(2), singles = byCount(1);

  if(quads.length)
    return score(7, [quads[0], [...trips,...pairs,...singles][0]]);

  if(trips.length >= 2)                       /* two trips: play the lower as a pair */
    return score(6, [trips[0], trips[1]]);

  if(trips.length && pairs.length)
    return score(6, [trips[0], pairs[0]]);

  if(trips.length)
    return score(3, [trips[0], singles[0], singles[1]]);

  if(pairs.length >= 2)
    return score(2, [pairs[0], pairs[1],
                     [...pairs.slice(2), ...singles].sort((a,b)=>b-a)[0]]);

  if(pairs.length)
    return score(1, [pairs[0], singles[0], singles[1], singles[2]]);

  return score(0, singles.slice(0,5));
}

const categoryOf = sc => sc >> 20;
const categoryName = sc => CAT_NAMES[categoryOf(sc)];

/* ══════════════════════════════════════════════════════════════
   Pot resolution with side pots.

   Built from the players' total contributions rather than tracked
   incrementally — deriving it means it cannot drift out of sync
   with the bets, which is the usual source of side-pot bugs.

   Layered at each distinct all-in level: everyone still matching
   contributes to that layer, and only players who reached it are
   eligible for it.
   ══════════════════════════════════════════════════════════════ */
function buildPots(players){
  const live = players.filter(p => p.contributed > 0);
  if(!live.length) return [];

  const levels = [...new Set(live.map(p => p.contributed))].sort((a,b)=>a-b);
  const pots = [];
  let prev = 0;

  for(const lvl of levels){
    const band = lvl - prev;
    let amount = 0;
    for(const p of live) amount += Math.min(Math.max(p.contributed - prev, 0), band);
    /* only players who put in at least this much AND haven't folded can win it */
    const eligible = players.filter(p => !p.folded && p.contributed >= lvl).map(p => p.id);
    if(amount > 0) pots.push({ amount, eligible });
    prev = lvl;
  }

  /* merge adjacent pots with identical eligibility — cosmetic, but it
     stops the UI showing three "side pots" that are really one */
  const merged = [];
  for(const pot of pots){
    const last = merged[merged.length-1];
    if(last && last.eligible.length === pot.eligible.length &&
       last.eligible.every(id => pot.eligible.includes(id))){
      last.amount += pot.amount;
    } else merged.push({ ...pot });
  }
  return merged;
}

/* Award every pot to the best eligible hand, splitting ties.
   Odd cents from a split go to the earliest eligible seat — poker
   convention is first-from-dealer; seat order is close enough here
   and, more importantly, it means no cent is ever destroyed. */
function awardPots(players, pots, showdownScores){
  const payouts = {};
  players.forEach(p => payouts[p.id] = 0);

  for(const pot of pots){
    const contenders = pot.eligible.filter(id => showdownScores[id] != null);
    if(!contenders.length) continue;

    const best = Math.max(...contenders.map(id => showdownScores[id]));
    const winners = contenders.filter(id => showdownScores[id] === best);

    const share = Math.floor(pot.amount / winners.length);
    let remainder = pot.amount - share * winners.length;
    for(const id of winners){
      payouts[id] += share;
      if(remainder > 0){ payouts[id] += 1; remainder--; }
    }
  }
  return payouts;
}

/* ══════════════════════════════════════════════════════════════
   Table — one hand at a time, driven by explicit act() calls.

   Deliberately a state machine rather than a loop with callbacks:
   the UI needs to animate between actions, so it must be able to
   step the hand forward when it's ready rather than being called
   back mid-render.
   ══════════════════════════════════════════════════════════════ */
const STREETS = ['preflop','flop','turn','river','showdown'];

class Table {
  constructor(opts = {}){
    this.sb = opts.sb ?? 100;                 /* $1.00 in cents */
    this.bb = opts.bb ?? 200;
    this.seed = opts.seed ?? 1;
    this.handNo = 0;
    this.button = 0;
    this.players = (opts.players ?? [
      { id:'you',  name:'You',  human:true  },
      { id:'jony', name:'Jony', style:'loose' },
      { id:'mike', name:'Mike', style:'solid' },
      { id:'sam',  name:'Sam',  style:'wild'  },
    ]).map(p => ({ stack: opts.buyin ?? 5000, ...p }));
    this.log = [];
  }

  /* players still in the hand and able to act */
  active(){ return this.players.filter(p => !p.folded && p.stack > 0); }
  inHand(){ return this.players.filter(p => !p.folded); }

  deal(){
    this.handNo++;
    this.rnd = mulberry32(this.seed * 7919 + this.handNo * 104729);
    const deck = shuffled(this.rnd);
    this.deck = deck;
    this.deckAt = 0;

    this.board = [];
    this.street = 'preflop';
    this.log = [];
    this.actionIndex = 0;
    this.lastAggressor = null;

    /* rotate the button, skipping anyone who's busted */
    do { this.button = (this.button + 1) % this.players.length; }
    while(this.players[this.button].stack <= 0 && this.players.some(p=>p.stack>0));

    for(const p of this.players){
      p.folded = p.stack <= 0;           /* busted players sit out */
      p.contributed = 0;                 /* total for the whole hand */
      p.committed = 0;                   /* this betting round only */
      p.allIn = false;
      p.hole = p.folded ? [] : [deck[this.deckAt++], deck[this.deckAt++]];
      p.actedThisRound = false;
    }

    /* blinds. Heads-up posts differently, but with 4 seats the simple
       small-then-big off the button is correct. */
    const order = this.seatOrder();
    const sbSeat = order[0], bbSeat = order[1];
    this.post(sbSeat, this.sb, 'small blind');
    this.post(bbSeat, this.bb, 'big blind');

    this.betToMatch = this.bb;
    this.minRaiseTo = this.bb * 2;
    /* pre-flop action starts left of the big blind */
    this.turnIdx = this.nextActive(this.players.indexOf(bbSeat));
    this.handOver = false;
    this.result = null;
    return this;
  }

  /* seats in betting order starting left of the button */
  seatOrder(){
    const n = this.players.length, out = [];
    for(let i = 1; i <= n; i++){
      const p = this.players[(this.button + i) % n];
      if(p.stack > 0) out.push(p);
    }
    return out;
  }

  post(p, amount, label){
    const paid = Math.min(amount, p.stack);
    p.stack -= paid;
    p.committed += paid;
    p.contributed += paid;
    if(p.stack === 0) p.allIn = true;
    this.log.push({ street:'preflop', who:p.id, action:label, amount:paid });
  }

  nextActive(fromIdx){
    const n = this.players.length;
    for(let i = 1; i <= n; i++){
      const idx = (fromIdx + i) % n;
      const p = this.players[idx];
      if(!p.folded && !p.allIn && p.stack > 0) return idx;
    }
    return -1;
  }

  current(){ return this.turnIdx >= 0 ? this.players[this.turnIdx] : null; }

  /* what the player to act may legally do */
  options(){
    const p = this.current();
    if(!p) return null;
    const toCall = Math.min(this.betToMatch - p.committed, p.stack);
    const canRaise = p.stack > toCall;
    return {
      player: p,
      toCall,
      canCheck: toCall === 0,
      canRaise,
      /* min legal raise, clamped to an all-in shove if the stack is short */
      minRaiseTo: Math.min(Math.max(this.minRaiseTo, this.betToMatch + this.bb),
                           p.committed + p.stack),
      maxRaiseTo: p.committed + p.stack,
      potCents: this.potTotal(),
    };
  }

  potTotal(){ return this.players.reduce((s,p)=>s + p.contributed, 0); }

  /* action: 'fold' | 'check' | 'call' | {raiseTo: cents} */
  act(action){
    const p = this.current();
    if(!p) throw new Error('no player to act');
    const o = this.options();
    this.actionIndex++;

    if(action === 'fold'){
      p.folded = true;
      this.log.push({ street:this.street, who:p.id, action:'folded' });
    } else if(action === 'check'){
      if(!o.canCheck) throw new Error(`${p.id} cannot check, ${o.toCall} to call`);
      this.log.push({ street:this.street, who:p.id, action:'checked' });
    } else if(action === 'call'){
      const paid = o.toCall;
      p.stack -= paid; p.committed += paid; p.contributed += paid;
      if(p.stack === 0) p.allIn = true;
      this.log.push({ street:this.street, who:p.id,
                      action: paid === 0 ? 'checked' : 'called', amount:paid });
    } else if(action && action.raiseTo != null){
      const target = Math.min(action.raiseTo, o.maxRaiseTo);
      if(target < o.minRaiseTo && target < o.maxRaiseTo)
        throw new Error(`raise to ${target} below min ${o.minRaiseTo}`);
      const paid = target - p.committed;
      if(paid > p.stack) throw new Error('raise exceeds stack');
      p.stack -= paid; p.committed += paid; p.contributed += paid;
      if(p.stack === 0) p.allIn = true;
      this.minRaiseTo = target + (target - this.betToMatch);
      this.betToMatch = Math.max(this.betToMatch, target);
      this.lastAggressor = p.id;
      /* a raise reopens the action for everyone behind */
      for(const q of this.players) if(q !== p) q.actedThisRound = false;
      this.log.push({ street:this.street, who:p.id,
                      action: p.allIn ? 'all in' : 'raised', amount:paid, to:target });
    } else throw new Error('unknown action: ' + JSON.stringify(action));

    p.actedThisRound = true;
    this.advance();
    return this;
  }

  advance(){
    /* everyone folded but one — hand ends with no showdown */
    if(this.inHand().length === 1){ this.finish(false); return; }

    const needsToAct = this.players.filter(p =>
      !p.folded && !p.allIn && p.stack > 0 &&
      (!p.actedThisRound || p.committed < this.betToMatch));

    if(needsToAct.length === 0){ this.nextStreet(); return; }

    let idx = this.nextActive(this.turnIdx);
    /* skip anyone already square who has acted */
    let guard = 0;
    while(idx >= 0 && guard++ < 8){
      const q = this.players[idx];
      if(!q.actedThisRound || q.committed < this.betToMatch) break;
      idx = this.nextActive(idx);
    }
    this.turnIdx = idx;
    if(idx < 0) this.nextStreet();
  }

  nextStreet(){
    /* reset the per-round bookkeeping */
    for(const p of this.players){ p.committed = 0; p.actedThisRound = false; }
    this.betToMatch = 0;
    this.minRaiseTo = this.bb;

    const i = STREETS.indexOf(this.street);
    this.street = STREETS[i+1];

    if(this.street === 'flop')  this.board.push(this.deck[this.deckAt++], this.deck[this.deckAt++], this.deck[this.deckAt++]);
    if(this.street === 'turn')  this.board.push(this.deck[this.deckAt++]);
    if(this.street === 'river') this.board.push(this.deck[this.deckAt++]);

    if(this.street === 'showdown'){ this.finish(true); return; }

    /* if nobody can act any more, run the rest of the board out */
    const canAct = this.players.filter(p => !p.folded && !p.allIn && p.stack > 0);
    if(canAct.length <= 1 && this.inHand().length > 1){ this.nextStreet(); return; }

    this.turnIdx = this.nextActive(this.button);
  }

  finish(showdown){
    const pots = buildPots(this.players);
    const scores = {};

    if(showdown){
      for(const p of this.inHand())
        scores[p.id] = evaluate7([...p.hole, ...this.board]);
    } else {
      /* uncontested — the last player standing takes it without showing */
      for(const p of this.inHand()) scores[p.id] = 1;
    }

    const payouts = awardPots(this.players, pots, scores);
    for(const p of this.players) p.stack += payouts[p.id] || 0;

    const winners = Object.entries(payouts).filter(([,v]) => v > 0).map(([id]) => id);

    this.handOver = true;
    this.turnIdx = -1;
    this.result = {
      showdown, pots, payouts, winners, scores,
      potTotal: pots.reduce((s,x)=>s + x.amount, 0),
      bestName: showdown && winners.length
        ? categoryName(scores[winners[0]]) : null,
    };
    return this.result;
  }

  /* ── bot policy ─────────────────────────────────────────────
     Crude on purpose. It does not need to play well; it needs to
     not be obviously fake, because opponents that always fold or
     always call make the whole thing feel like a toy. Strength is
     a rough made-hand/high-card estimate plus noise. */
  botAction(){
    const p = this.current();
    const o = this.options();
    const r = this.rnd;

    const seen = [...p.hole, ...this.board];
    let strength;
    if(this.board.length >= 3){
      const cat = categoryOf(evaluate7(seen));
      strength = Math.min(1, cat / 6 + 0.10);
    } else {
      /* pre-flop: pair, high cards and suitedness */
      const [a,b] = p.hole.map(rankOf);
      const pair = a === b;
      const high = Math.max(a,b) / 12;
      const suited = suitOf(p.hole[0]) === suitOf(p.hole[1]);
      strength = (pair ? 0.62 : 0.20) + high * 0.28 + (suited ? 0.07 : 0);
    }

    const style = { loose:0.14, solid:-0.06, wild:0.24 }[p.style] ?? 0;
    const mood = strength + style + (r() - 0.5) * 0.34;
    const potOdds = o.toCall / Math.max(1, o.potCents + o.toCall);

    if(o.toCall > 0 && mood < potOdds * 1.15 && mood < 0.42) return 'fold';

    /* raise sometimes when strong, occasionally when not (a bluff) */
    if(o.canRaise && (mood > 0.72 || r() < 0.10)){
      const potAfter = o.potCents + o.toCall;
      const target = Math.min(
        o.maxRaiseTo,
        Math.max(o.minRaiseTo, p.committed + o.toCall + Math.round(potAfter * (0.5 + r()))));
      /* round to a whole number of cents divisible by the small blind
         so bots produce chip-friendly numbers, not $3.87 */
      const snapped = Math.max(o.minRaiseTo, Math.round(target / this.sb) * this.sb);
      return { raiseTo: Math.min(snapped, o.maxRaiseTo) };
    }
    return o.canCheck ? 'check' : 'call';
  }
}

/* ── denomination breakdown ───────────────────────────────────
   Greedy largest-first, which for these denominations (25/100/500/
   2500/10000/50000 cents) is optimal and always terminates because
   25 divides every value we ever deal in. */
const DENOM_CENTS = [
  { key:'500', c:50000 }, { key:'100', c:10000 }, { key:'25', c:2500 },
  { key:'5',   c:500   }, { key:'1',   c:100   }, { key:'25c', c:25 },
];
function breakdown(cents){
  const out = [];
  let left = cents;
  for(const d of DENOM_CENTS){
    while(left >= d.c){ out.push(d.key); left -= d.c; }
  }
  return out;   /* largest first; reverse for visual piles */
}

/* ── racking up ───────────────────────────────────────────────
   What a buy-in actually looks like on the rail. A greedy breakdown
   of $50 hands you two $25 chips and nothing you can bet with, so
   instead: reserve a working float of small denominations first,
   then fill the remainder largest-first. This is what "re-racking"
   with the bank does at a real table, and it means you always have
   change.

   Returns { '25c': n, '1': n, … } with only non-zero entries. */
function rack(cents){
  const counts = {};
  let left = cents;
  const take = (key, c, max) => {
    const n = Math.min(max, Math.floor(left / c));
    if(n > 0){ counts[key] = (counts[key]||0) + n; left -= n * c; }
  };
  /* the working float: enough small chips to make any bet */
  take('25c', 25, 8);
  take('1', 100, 8);
  take('5', 500, 6);
  /* remainder, largest first */
  for(const d of DENOM_CENTS) take(d.key, d.c, Infinity);
  return counts;
}

const rackTotal = counts => Object.entries(counts).reduce((s,[k,n]) => {
  const d = DENOM_CENTS.find(x => x.key === k);
  return s + d.c * n;
}, 0);

const centsOf = key => DENOM_CENTS.find(d => d.key === key).c;

const money = cents => '$' + (cents/100).toFixed(2);

/* node + browser */
if(typeof module !== 'undefined' && module.exports){
  module.exports = { mulberry32, evaluate7, categoryOf, categoryName, CAT_NAMES,
                     buildPots, awardPots, Table, breakdown, money, rack, rackTotal, centsOf,
                     cardStr, parseCard, rankOf, suitOf, shuffled, straightTop,
                     DENOM_CENTS };
}
