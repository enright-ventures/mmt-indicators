// Execute the production Offside tape helpers and 5m handler with synthetic feeds.
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
    .replace(/\.len\b/g, '.length');
}
const context = {
  Math, math: { ...Math, isFinite: Number.isFinite, abs: Math.abs, max: Math.max,
    min: Math.min, floor: Math.floor },
  unix: x => x, int: Math.trunc, float: Number,
  time: { fromUnixSeconds: x => x },
  str: { format: (template, ...values) => template.replace(/\{(\d+)[^}]*\}/g, (_, i) => values[+i]), },
  ensureListed: () => {}, niceStep: x => x, drawTrap: () => {}, events: [],
};
// Production scalar defaults and array capacities (M5 arrays start empty).
const state = source.slice(source.indexOf('state ('), source.indexOf('\nfn niceStep'));
for (const match of state.matchAll(/^  (\w+): (?:float|int|bool|time\??) = (\d+(?:\.\d+)?|true|false|null)$/gm)) {
  context[match[1]] = JSON.parse(match[2]);
}
for (const match of state.matchAll(/^  (\w+) = (?:float|int|bool|time|string)\[\]\(/gm)) context[match[1]] = [];
Object.assign(context, {
  useTrades: true, useChart: true, useAll: false, lsBn: true, lsBb: false, lsOk: false, lsHl: false,
  step: 1, rowSize: 0, tfScale: 1, showTraps: true, pokePct: 0.03, holdBars: 3,
  reclaimBars: 12, trackHours: 24, coin: 'coins', bigUsd: 100000,
  prevC5: 101, lastTrap: new Map(),
  lvP: [100], lvSide: [1], lvExp: [999999], lvState: [0], lvName: ['support'],
  ...input.state,
});
context.addTrap = (side, at, from, qty, ext, pain, lvl, name, stopped, wick, flowOk, pressed, fill, big, back, tradeOk) =>
  context.events.push({side, at, qty, pressed, fill, big, back, tradeOk});
for (const value of Object.values(context)) {
  if (Array.isArray(value)) Object.defineProperty(value, 'clear', {value() { this.length = 0; }});
}
context.bPos = new Map();
vm.createContext(context);
for (const name of ['candleOk', 'flowReady5', 'measureLevel', 'measureAll', 'onTrade', 'volumeMatches', 'venueCovered', 'tradeCoverageReady', 'creditBar']) {
  vm.runInContext(translate(block(`fn ${name}(`)), context);
}
vm.runInContext(translate(block('on p5.close {')), context);
for (const bar of input.bars ?? []) {
  for (const tr of bar.trades ?? []) context.onTrade(tr.price, tr.size, tr.buy, tr.time ?? bar.time, tr.venue ?? 4);
  context.p5 = {time: bar.time, high: 103, low: 99, close: 102, volume: 1, buyVolume: 0, sellVolume: 0, ...bar.candle};
  for (const venue of ['bn5', 'bb5', 'ok5', 'hl5']) context[venue] = { ...context.p5, ...bar[venue] };
  context.oi5 = {time: bar.time, open: 0, close: 0, ...bar.oi};
  context.liq5 = {buyLiq: 0, sellLiq: 0};
  context.closeBar();
}
console.log(JSON.stringify(Object.fromEntries(['events', 'fLive', 'fDone', 'fStatus', 'lvPressed', 'lvBack', 'lvTradeOk', 'measuredTime'].map(k => [k, context[k]]))));
