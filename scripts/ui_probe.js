/* ClipBlitz UI runtime probe — V1 / V2 / V4 / V6.
 *
 * The law being tested: no element may be stuck below its intended resting
 * state because an animation clock paused. Two failure classes in this
 * project's history:
 *   1. stuck-dim   — opacity:0 entrance with fill:both, frozen invisible
 *   2. flicker     — infinite opacity pulse on chrome
 * Both are impossible by construction here (no keyframe touches opacity),
 * so this probe proves the CONSTRUCTION held, rather than patching symptoms.
 *
 * Method: the old probe slept a fixed 400ms. That is wrong — cards carry a
 * 0.5s animation with up to 390ms of stagger (--i capped at 6), so a fixed
 * sleep reads in-flight animations as "stuck". Instead we wait on the Web
 * Animations API for every finite animation to actually finish, which is the
 * real frozen-clock test: if the clock were paused, `finished` would never
 * resolve and the probe would time out and report the offenders.
 */
(async () => {
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const css = (el) => getComputedStyle(el);

  const isVisible = (el) => {
    const s = css(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (s.contentVisibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };

  /* An element's INTENDED resting opacity is whatever the stylesheet says for
     its current matched state. Any element whose live opacity is below that is
     mid-animation or stuck; either way it is not at rest. */
  const dimAtRest = (root) => {
    const out = [];
    for (const el of root.querySelectorAll('*')) {
      if (!isVisible(el)) continue;
      const s = css(el);
      const o = parseFloat(s.opacity);
      if (o < 0.99) {
        out.push({
          tag: el.tagName,
          cls: String(el.className).slice(0, 70),
          opacity: o,
          anim: s.animationName !== 'none' ? s.animationName : null,
        });
      }
    }
    return out;
  };

  const movedAtRest = (root) => {
    const out = [];
    for (const el of root.querySelectorAll('*')) {
      if (!isVisible(el)) continue;
      const t = css(el).transform;
      if (!t || t === 'none') continue;
      const m = new DOMMatrix(t);
      const off = Math.abs(m.m41) + Math.abs(m.m42);
      const scaled = Math.abs(m.a - 1) > 0.002 || Math.abs(m.d - 1) > 0.002;
      if (off > 0.5 || scaled) {
        out.push({
          tag: el.tagName,
          cls: String(el.className).slice(0, 70),
          transform: t,
          anim: css(el).animationName,
        });
      }
    }
    return out;
  };

  /* ---------------------------------------------------------- V6 first,
     while the Studio screen is the one on display. */
  const studio = document.getElementById('screen-studio');
  const hero = studio && studio.querySelector('.hero .display');
  const hs = hero ? css(hero) : null;
  const panel = document.querySelector('.glass.panel');
  const ps = panel ? css(panel) : null;
  const btn = document.querySelector('.btn:not(.ghost)');
  const bs = btn ? css(btn) : null;

  const v6 = {
    heroFound: !!hero,
    heroText: hero ? hero.textContent.trim().slice(0, 46) : null,
    fontSize: hs && hs.fontSize,
    lineHeight: hs && hs.lineHeight,
    fontWeight: hs && hs.fontWeight,
    letterSpacing: hs && hs.letterSpacing,
    fontFamily: hs && hs.fontFamily,
    panelRadius: ps && ps.borderRadius,
    panelBackdrop: ps && (ps.backdropFilter || ps.webkitBackdropFilter),
    panelBorder: ps && (ps.borderTopColor + ' ' + ps.borderTopWidth),
    primaryBtnRadius: bs && bs.borderRadius,
    fonts: {
      inter: document.fonts.check('15px "Inter"'),
      mono: document.fonts.check('12px "JetBrains Mono"'),
      grotesk: document.fonts.check('20px "Space Grotesk"'),
    },
  };

  /* ------------------------------------------- V1: rapid-switch stress.
     All 5 nav buttons, 4 rounds, 25ms apart — faster than any animation can
     settle, which is the point: we are trying to catch a frozen mid-state. */
  const navs = $$('.snavbtn');
  const clicks = [];
  for (let round = 0; round < 4; round++) {
    for (const b of navs) {
      b.click();
      clicks.push(b.textContent.trim());
      await new Promise((r) => setTimeout(r, 25));
    }
  }

  /* Wait for every finite animation to finish. Infinite ones (aurora drift,
     halo) are excluded by name — they are meant to run forever. */
  const INFINITE = new Set(['cb-aurora-a', 'cb-aurora-b', 'cb-kfill']);
  const finite = () => document.getAnimations().filter((a) => {
    const n = a.animationName || (a.effect && a.effect.getKeyframes && '');
    return !INFINITE.has(n);
  });

  let timedOut = false;
  const pending = finite();
  try {
    await Promise.race([
      Promise.all(pending.map((a) => a.finished.catch(() => {}))),
      new Promise((r) => setTimeout(() => { timedOut = true; r(); }, 4000)),
    ]);
  } catch (e) { timedOut = true; }
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

  const stillRunning = finite()
    .filter((a) => a.playState === 'running')
    .map((a) => a.animationName || '(anon)');

  const active = $$('.screen').find((s) => !s.hidden);
  const bodyDim = dimAtRest(document.body);
  const bodyMoved = movedAtRest(document.body);

  const v1 = {
    clicks: clicks.length,
    animationsTimedOut: timedOut,
    stillRunning,
    dimCount: bodyDim.length,
    dim: bodyDim,
    movedCount: bodyMoved.length,
    moved: bodyMoved,
  };

  /* --------------------------------- V2: frozen-clock probe on the ACTIVE
     screen only — the surface the user is actually looking at. */
  const v2 = active
    ? {
        activeScreen: active.id,
        visible: Array.from(active.querySelectorAll('*')).filter(isVisible).length,
        stuckDim: dimAtRest(active),
        stuckMoved: movedAtRest(active),
      }
    : { activeScreen: null };

  return { v6, v1, v2 };
})()
