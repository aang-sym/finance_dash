/* ══════════════════════════════════════════════════════════════
   feel.js — the haptic + audio layer.

   One interface, swappable backends, per the architecture note:
     feel.tick()            a single chip
     feel.impact(weight)    a landing / a shove
     feel.cascade(cents)    the payout, length scaled to the pot
     feel.riffle()          shuffling / dealing

   WHY IT LOOKS LIKE THIS — the constraints are severe and none of
   them are obvious:

   1. iOS Safari has no Vibration API. The only route to the Taptic
      Engine is a side-effect of WebKit's <input type=checkbox switch>.
      iOS 26.5 patched *script-triggered* toggles, so only a real
      finger landing on a real control still fires. Hence armTap():
      the switch is invisible and sits over the target, and the
      user's own tap does the work. We never simulate it.

   2. On iOS, Web Audio is routed to the RINGER channel, so a phone
      on silent plays nothing — while <audio> elements are exempt.
      At a poker night every phone is on silent. Fix: keep a silent
      <audio> loop playing, which drags the whole context onto the
      media channel. Without this the entire feel layer is mute for
      most of our users. (WebKit bug 237322.)

   3. Latency is the whole game. One AudioContext, interactive
      latency hint, and every sound synthesised from oscillators and
      noise buffers — nothing decoded, nothing fetched, no
      HTMLAudioElement for effects.

   Synthesis over samples is not a compromise here: pitch, density
   and decay all need to scale continuously with denomination, stack
   height and pot size, which fixed samples cannot do.
   ══════════════════════════════════════════════════════════════ */

const Feel = (() => {

  const state = {
    haptics: true, audio: true, motion: true,
    ready: false,
    ctx: null, master: null,
    noise: null,                 /* shared white-noise buffer */
    tapCount: 0,
    lastLatency: null,
    backend: 'none',             /* 'switch' | 'vibrate' | 'none' */
    scriptTicksWork: null,       /* null = untested (pre-26.5 path) */
    silentEl: null,
  };

  /* ── capability detection ─────────────────────────────────── */
  const supportsSwitch = (() => {
    const el = document.createElement('input');
    el.type = 'checkbox';
    /* `switch` is a real IDL attribute in Safari 17.4+; in browsers
       without it the property is simply undefined */
    return 'switch' in el;
  })();
  const supportsVibrate = typeof navigator !== 'undefined' &&
                          typeof navigator.vibrate === 'function';
  const isFramed = (() => { try { return window.self !== window.top; }
                            catch(e){ return true; } })();

  state.backend = supportsVibrate ? 'vibrate' : (supportsSwitch ? 'switch' : 'none');

  function iosVersion(){
    const m = navigator.userAgent.match(/OS (\d+)[._](\d+)/);
    if(m) return `${m[1]}.${m[2]}`;
    const v = navigator.userAgent.match(/Version\/(\d+\.\d+)/);
    return v ? 'Safari ' + v[1] : 'n/a';
  }

  /* ══════════════════════════════════════════════════════════
     AUDIO
     ══════════════════════════════════════════════════════════ */

  /* A 1-frame silent WAV. Looped forever, this is what moves Web
     Audio off the ringer channel on iOS so a silenced phone still
     plays our sounds. 44 bytes of header plus two zero samples. */
  const SILENT_WAV = 'data:audio/wav;base64,UklGRiwAAABXQVZFZm10IBAAAAABAAEAR' +
                     'KwAAIhYAQACABAAZGF0YQgAAAAAAAAAAAAAAA==';

  function unlock(){
    if(state.ready) return state.ready;

    const AC = window.AudioContext || window.webkitAudioContext;
    if(!AC) return false;

    state.ctx = new AC({ latencyHint: 'interactive' });
    state.master = state.ctx.createGain();
    state.master.gain.value = 0.9;
    state.master.connect(state.ctx.destination);

    /* shared noise buffer — the body of every chip sound */
    const len = Math.floor(state.ctx.sampleRate * 0.35);
    state.noise = state.ctx.createBuffer(1, len, state.ctx.sampleRate);
    const ch = state.noise.getChannelData(0);
    for(let i = 0; i < len; i++) ch[i] = Math.random() * 2 - 1;

    /* the silent-loop trick — see note 2 at the top of this file */
    try {
      const el = document.createElement('audio');
      el.src = SILENT_WAV;
      el.loop = true;
      el.setAttribute('playsinline', '');
      el.volume = 0.001;                /* not 0 — some builds skip muted media */
      el.play().catch(()=>{});
      state.silentEl = el;
    } catch(e){ /* not fatal: sound still works with the ringer on */ }

    /* a silent tick through the graph, which some iOS builds need
       before they will schedule anything audible */
    const s = state.ctx.createBufferSource();
    s.buffer = state.ctx.createBuffer(1, 1, state.ctx.sampleRate);
    s.connect(state.master); s.start(0);

    state.ready = true;
    return true;
  }

  function resume(){
    if(state.ctx && state.ctx.state === 'suspended') state.ctx.resume();
    if(state.silentEl && state.silentEl.paused) state.silentEl.play().catch(()=>{});
  }

  /* ── one chip against another ──────────────────────────────
     Two layers: a bright transient (band-passed noise burst, very
     short) and a resonant body (two detuned partials). Real chips
     are clay, so the body is dull and dies fast — a long ring
     sounds like glass, which reads as wrong immediately. */
  function clink({ pitch = 1, gain = 0.5, bright = 1 } = {}){
    if(!state.audio || !state.ready) return;
    resume();
    const ctx = state.ctx, t = ctx.currentTime;
    const out = ctx.createGain();
    out.gain.value = gain;
    out.connect(state.master);

    /* transient */
    const src = ctx.createBufferSource();
    src.buffer = state.noise;
    src.playbackRate.value = 0.8 + Math.random() * 0.4;
    const bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = 2600 * pitch * bright;
    bp.Q.value = 1.4;
    const env = ctx.createGain();
    env.gain.setValueAtTime(0.0001, t);
    env.gain.exponentialRampToValueAtTime(0.9, t + 0.002);
    env.gain.exponentialRampToValueAtTime(0.0001, t + 0.045);
    src.connect(bp); bp.connect(env); env.connect(out);
    src.start(t); src.stop(t + 0.08);

    /* body — detuned pair, slightly inharmonic so it reads as a
       disc rather than a tuned note */
    [1, 1.47].forEach((mult, i) => {
      const o = ctx.createOscillator();
      o.type = i ? 'triangle' : 'sine';
      /* ±3% detune per hit so repeated taps never machine-gun */
      o.frequency.value = 430 * pitch * mult * (1 + (Math.random()-0.5) * 0.06);
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(i ? 0.10 : 0.22, t + 0.004);
      g.gain.exponentialRampToValueAtTime(0.0001, t + (i ? 0.09 : 0.16));
      o.connect(g); g.connect(out);
      o.start(t); o.stop(t + 0.2);
    });
  }

  /* ── chip onto felt: no ring, just a soft thud ─────────────── */
  function thud({ gain = 0.5, pitch = 1 } = {}){
    if(!state.audio || !state.ready) return;
    resume();
    const ctx = state.ctx, t = ctx.currentTime;
    const src = ctx.createBufferSource();
    src.buffer = state.noise;
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 420 * pitch;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.004);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);
    src.connect(lp); lp.connect(g); g.connect(state.master);
    src.start(t); src.stop(t + 0.2);
  }

  /* ── sub-bass for an all-in shove ─────────────────────────── */
  function boom(){
    if(!state.audio || !state.ready) return;
    resume();
    const ctx = state.ctx, t = ctx.currentTime;
    const o = ctx.createOscillator();
    o.type = 'sine';
    o.frequency.setValueAtTime(120, t);
    o.frequency.exponentialRampToValueAtTime(38, t + 0.5);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.55, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.7);
    o.connect(g); g.connect(state.master);
    o.start(t); o.stop(t + 0.8);
  }

  /* ── riffle: many tiny transients in ~250ms ───────────────── */
  function riffle(){
    if(!state.audio || !state.ready) return;
    resume();
    const ctx = state.ctx, t0 = ctx.currentTime;
    for(let i = 0; i < 22; i++){
      const t = t0 + i * 0.011 + Math.random() * 0.004;
      const src = ctx.createBufferSource();
      src.buffer = state.noise;
      src.playbackRate.value = 1.6 + Math.random();
      const bp = ctx.createBiquadFilter();
      bp.type = 'bandpass';
      bp.frequency.value = 3200 + Math.random() * 2200;
      bp.Q.value = 2;
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.10, t + 0.001);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.02);
      src.connect(bp); bp.connect(g); g.connect(state.master);
      src.start(t); src.stop(t + 0.04);
    }
  }

  /* ── THE PAYOUT ────────────────────────────────────────────
     The moment the whole design is built around. Length and density
     scale with the pot: a $4 pot is a handful of clinks, an $80 pot
     is a multi-second avalanche. Scaling the reward to the number
     is exactly what Balatro does, and why its payouts land.

     Pitch rises across the cascade so it reads as a climb rather
     than a pile, and the tail thickens toward the end so it lands
     rather than fading out. */
  function cascade(cents, { winner = true } = {}){
    if(!state.audio || !state.ready) return 0;
    resume();
    const ctx = state.ctx, t0 = ctx.currentTime;

    /* everyone hears the pot move; only the winner gets the full
       avalanche. The asymmetry IS the reward. */
    const chips = winner
      ? Math.max(6, Math.min(64, Math.round(cents / 100)))
      : Math.max(3, Math.min(10, Math.round(cents / 400)));
    const dur = winner ? Math.min(3.4, 0.5 + chips * 0.055) : 0.5;

    for(let i = 0; i < chips; i++){
      const f = i / Math.max(1, chips - 1);
      /* ease-out: dense at the start, spacing out, then a cluster
         at the very end so the tail has a shape */
      const at = t0 + Math.pow(f, 0.72) * dur + (Math.random()-0.5) * 0.012;
      const pitch = winner ? (0.82 + f * 0.62) : 0.7;
      const gain = (winner ? 0.30 : 0.16) * (0.7 + Math.random() * 0.5);
      scheduleClink(at, pitch, gain);
    }
    if(winner){
      /* the landing */
      const t = t0 + dur + 0.05;
      const o = ctx.createOscillator();
      o.type = 'sine';
      o.frequency.setValueAtTime(180, t);
      o.frequency.exponentialRampToValueAtTime(52, t + 0.4);
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.42, t + 0.015);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.55);
      o.connect(g); g.connect(state.master);
      o.start(t); o.stop(t + 0.6);
    }
    return dur;
  }

  /* scheduled variant of clink() — cascade needs absolute times */
  function scheduleClink(t, pitch, gain){
    const ctx = state.ctx;
    const src = ctx.createBufferSource();
    src.buffer = state.noise;
    src.playbackRate.value = 0.8 + Math.random() * 0.5;
    const bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = 2500 * pitch;
    bp.Q.value = 1.3;
    const env = ctx.createGain();
    env.gain.setValueAtTime(0.0001, t);
    env.gain.exponentialRampToValueAtTime(gain, t + 0.002);
    env.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
    src.connect(bp); bp.connect(env); env.connect(state.master);
    src.start(t); src.stop(t + 0.09);

    const o = ctx.createOscillator();
    o.type = 'sine';
    o.frequency.value = 420 * pitch * (1 + (Math.random()-0.5)*0.05);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain * 0.5, t + 0.004);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.11);
    o.connect(g); g.connect(state.master);
    o.start(t); o.stop(t + 0.14);
  }

  /* ── count-up pitch ladder for the winner's stack ─────────── */
  function step(i, of){
    if(!state.audio || !state.ready) return;
    resume();
    const f = of > 1 ? i / (of - 1) : 1;
    clink({ pitch: 0.9 + f * 0.9, gain: 0.16, bright: 1.2 });
  }

  /* ══════════════════════════════════════════════════════════
     HAPTICS
     ══════════════════════════════════════════════════════════ */

  /* Attach a real, invisible native switch over `el` so the user's
     own tap lands on it and iOS fires a system tick. Nothing else
     in the app should know this exists.

     The clip-path matters: overflow:hidden clips the visual but
     leaves a rectangular hit area, so a round chip would take taps
     from its corners. */
  function armTap(el, onTap){
    el.classList.add('feel-tap');

    if(supportsVibrate || !supportsSwitch){
      /* Android and desktop: a normal listener plus vibrate */
      el.addEventListener('pointerdown', ev => {
        if(state.haptics && supportsVibrate) navigator.vibrate(8);
        fire(onTap, ev);
      });
      return el;
    }

    /* iOS: the real control does the work */
    const sw = document.createElement('input');
    sw.type = 'checkbox';
    sw.setAttribute('switch', '');
    sw.className = 'feel-switch';
    sw.tabIndex = -1;
    sw.setAttribute('aria-hidden', 'true');
    el.appendChild(sw);

    sw.addEventListener('change', ev => {
      /* it toggles; we don't care about the value, only the tick */
      fire(onTap, ev);
    });
    return el;
  }

  function fire(onTap, ev){
    const t = performance.now();
    state.tapCount++;
    if(onTap) onTap(ev);
    /* measured on the next frame: how long from the tap until we'd
       have got a sound onto the graph */
    state.lastLatency = performance.now() - t;
  }

  /* Programmatic tick. Works on Android always, and on iOS only
     before 26.5 — we try once and remember whether it did anything
     we can observe. It is never the primary path. */
  function tick(strength = 8){
    if(!state.haptics) return;
    if(supportsVibrate){ navigator.vibrate(strength); return; }
    if(!supportsSwitch) return;
    /* the pre-26.5 script path: toggling a detached switch */
    try {
      if(!state._probe){
        const p = document.createElement('input');
        p.type = 'checkbox'; p.setAttribute('switch','');
        p.className = 'feel-switch feel-probe';
        document.body.appendChild(p);
        state._probe = p;
      }
      state._probe.checked = !state._probe.checked;
      state._probe.dispatchEvent(new Event('change'));
    } catch(e){ /* ignore */ }
  }

  function impact(weight = 'medium'){
    if(!state.haptics) return;
    if(supportsVibrate){
      navigator.vibrate({ light:6, medium:14, heavy:[18,30,22] }[weight] || 14);
    } else tick();
  }

  /* ══════════════════════════════════════════════════════════
     VISUAL — the third channel, and the only one that always works
     ══════════════════════════════════════════════════════════ */
  let kickEl = null;
  function kick(px = 3){
    if(!state.motion || !kickEl) return;
    kickEl.style.transition = 'none';
    kickEl.style.transform = `translate3d(0,${px}px,0)`;
    requestAnimationFrame(() => {
      kickEl.style.transition = 'transform .16s cubic-bezier(.2,.9,.25,1)';
      kickEl.style.transform = 'translate3d(0,0,0)';
    });
  }
  function setKickTarget(el){ kickEl = el; }

  /* ══════════════════════════════════════════════════════════
     COMPOSITE EVENTS — what the UI actually calls
     ══════════════════════════════════════════════════════════ */
  const api = {
    unlock, resume, armTap, setKickTarget,
    tick, impact, kick, clink, thud, boom, riffle, cascade, step,

    /* one chip lifted onto the pile. `n` is how many are already
       there, which drives the rising pitch — this is the core loop. */
    chipUp(n = 0){
      clink({ pitch: 1 + Math.min(n, 12) * 0.055, gain: 0.42 });
      kick(1);
    },
    chipDown(){ thud({ gain: 0.34 }); },
    commit(cents){
      thud({ gain: 0.5, pitch: 0.85 });
      clink({ pitch: 0.8, gain: 0.3 });
      impact('medium');
      kick(3);
    },
    allIn(){ boom(); riffle(); impact('heavy'); kick(5); },
    deal(){ riffle(); },
    fold(){ thud({ gain: 0.22, pitch: 0.7 }); },

    /* diagnostics for the drawer */
    report(){
      return {
        backend: state.backend,
        framed: isFramed,
        switchSupported: supportsSwitch,
        vibrateSupported: supportsVibrate,
        platform: iosVersion(),
        audioReady: state.ready,
        audioState: state.ctx ? state.ctx.state : 'none',
        sampleRate: state.ctx ? state.ctx.sampleRate : null,
        baseLatency: state.ctx && state.ctx.baseLatency != null
          ? Math.round(state.ctx.baseLatency * 1000) : null,
        outputLatency: state.ctx && state.ctx.outputLatency
          ? Math.round(state.ctx.outputLatency * 1000) : null,
        taps: state.tapCount,
        lastCallbackMs: state.lastLatency != null
          ? state.lastLatency.toFixed(1) : null,
        silentLoop: state.silentEl ? !state.silentEl.paused : false,
      };
    },
    set(k, v){ state[k] = v; if(k === 'audio' && v) resume(); },
    get(k){ return state[k]; },
  };

  return api;
})();

if(typeof module !== 'undefined' && module.exports) module.exports = Feel;
