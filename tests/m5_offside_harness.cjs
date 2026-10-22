// Execute the production Offside helpers and 5m handler with synthetic feeds. Each bar's 5m volume profile is built
// from its listed trades summed by price, or given as native levels (bar.levels); bar.profile = false: no profile;
// bar.profileTime: a misaligned one.
// This translates the small shared M5/JavaScript subset; it is not an MMT compiler.
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function block(marker) {
  const start = source.indexOf(marker);
  if (start < 0) throw new Error(`Missing source block: ${marker}`);
  const open = source.indexOf('{', start);
  let depth = 1, end = open + 1;
  while (depth && end < source.length) {
    if (source[end] === '{') depth++;
    if (source[end] === '}') depth--;
    end++;
  }
  return source.slice(start, end);
}
function translate(code) {
  return code.replace(/fn (\w+)\(([^)]*)\)(?: -> \w+\??)?/g, (_, name, args) =>
    `function ${name}(${args.replace(/: (?:float|bool|time|int)\??/g, '')})`)
    .replace(/on p5.close/, 'function closeBar()')
    .replace(/for (\w+) in 0\.\.([^\n{]+)\{/g, 'for (let $1 = 0; $1 < $2; $1++) {')
    .replace(/\bif ([^\n{]+)\{/g, 'if ($1) {')
    // named arguments become positional: f(a, from: b, to: c) -> f(a, b, c)
    .replace(/([,(]\s*)(?:from|to|barsAgo): /g, '$1')
    .replace(/\.len\b/g, '.length');
}
const context = {
  Math, math: { ...Math, isFinite: Number.isFinite, abs: Math.abs, max: Math.max,
    min: Math.min, floor: Math.floor },
  unix: x => x, int: Math.trunc, float: Number,
  time: { fromUnixSeconds: x => x },
  str: { format: (template, ...values) => template.replace(/\{(\d+)[^}]*\}/g, (_, i) => values[+i]),
    concat: (...parts) => parts.join('') },
  ensureListed: () => {}, niceStep: x => x, drawTrap: () => {}, events: [],
};
// Production scalar defaults and array capacities (M5 arrays start empty).
const state = source.slice(source.indexOf('state ('), source.indexOf('\nfn niceStep'));
for (const match of state.matchAll(/^  (\w+): (?:float|int|bool|time\??) = (\d+(?:\.\d+)?|true|false|null)$/gm)) {
  context[match[1]] = JSON.parse(match[2]);
}
for (const match of state.matchAll(/^  (\w+) = (?:float|int|bool|time|string)\[\]\(/gm)) context[match[1]] = [];
Object.assign(context, {
  useChart: true, useAll: false, lsBn: true, lsBb: false, lsOk: false,
  step: 1, rowSize: 0, tfScale: 1, showTraps: true, pokePct: 0.03, holdBars: 3,
  reclaimBars: 12, trackHours: 24, coin: 'coins',
  prevC5: 101, lastTrap: new Map(),
  lvP: [100], lvSide: [1], lvExp: [999999], lvState: [0], lvName: ['support'],
  ...input.state,
});
context.addTrap = (side, at, from, qty, ext, pain, lvl, name, stopped, wick, flowOk, pressed, fill, back, tradeOk) =>
  context.events.push({side, at, qty, pressed, fill, back, tradeOk});
for (const value of Object.values(context)) {
  if (Array.isArray(value)) Object.defineProperty(value, 'clear', {value() { this.length = 0; }});
}
vm.createContext(context);
for (const name of ['candleOk', 'flowReady5', 'flowReadyLive', 'liveFlowReady', 'flowStep', 'priceText', 'readProfile', 'creditBar']) {
  vm.runInContext(translate(block(`fn ${name}(`)), context);
}
vm.runInContext(translate(block('on p5.close {')), context);
for (const bar of input.bars ?? []) {
  // the bar's volume profile as native levels (price, buy, sell), lowest first: bar.levels if given (pooled
  // venues can trade outside the chart candle), else its trades summed by price
  const levels = new Map();
  for (const [price, buy, sell] of bar.levels ?? []) levels.set(price, {price, buy, sell});
  if (!bar.levels) {
    for (const tr of bar.trades ?? []) {
      const lv = levels.get(tr.price) ?? {price: tr.price, buy: 0, sell: 0};
      if (tr.buy) lv.buy += tr.size; else lv.sell += tr.size;
      levels.set(tr.price, lv);
    }
  }
  const sorted = [...levels.values()].sort((a, b) => a.price - b.price);
  const profileTime = bar.profile === false ? null : (bar.profileTime ?? bar.time);
  context.v5 = {
    time: () => profileTime,
    binSize: () => 2.5,
    levels: () => profileTime === null ? null : {length: sorted.length, get: i => sorted[i]},
    // as documented: select levels in [from, to] first, then group them on a grid of whole multiples of step
    bucketsByStep: (step, from, to) => {
      const groups = new Map();
      for (const lv of sorted) {
        if ((from != null && lv.price < from) || (to != null && lv.price > to)) continue;
        const k = Math.floor(lv.price / step);
        const g = groups.get(k) ?? {from: k * step, to: (k + 1) * step, buy: 0, sell: 0};
        g.buy += lv.buy; g.sell += lv.sell; groups.set(k, g);
      }
      const list = [...groups.values()].sort((a, b) => a.from - b.from);
      return list.length ? {length: list.length, get: i => list[i]} : null;
    },
  };
  context.p5 = {time: bar.time, high: 103, low: 99, close: 102, volume: 1, buyVolume: 0, sellVolume: 0, ...bar.candle};
  for (const venue of ['bn5', 'bb5', 'ok5']) context[venue] = { ...context.p5, ...bar[venue] };
  context.oi5 = {time: bar.time, open: 0, close: 0, ...bar.oi};
  context.liq5 = {time: bar.time, buyLiq: 0, sellLiq: 0, ...bar.liq};
  context.closeBar();
}
// Direct calls of production helpers: [{fn, args}] -> results, then any state fields named in `read`.
const calls = (input.calls ?? []).map(c => context[c.fn](...c.args));
console.log(JSON.stringify({...Object.fromEntries(['events', 'fLive', 'fDone', 'fStatus', 'lvPressed', 'lvBack', 'lvTradeOk', 'lvState'].map(k => [k, context[k]])),
  calls, read: Object.fromEntries((input.read ?? []).map(k => [k, context[k]]))}));
