// Run selected functions and handlers of a production M5 script against stubbed feeds.
// This translates the small M5/JavaScript subset those blocks use; it is not an MMT compiler or scheduler.
// stdin: {blocks: ["fn name(", "on feed.close {"], context: {...}, calls: [{fn, args}], read: ["name"]}
// Handlers become functions named after their target: "on bnM.close {" -> bnM_close().
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
  return code
    .replace(/fn (\w+)\(([^)]*)\)(?: -> [\w?]+)?/g, (_, name, args) =>
      `function ${name}(${args.replace(/: [\w?]+/g, '')})`)
    .replace(/on (\w+)\.(\w+)(?:\(([^)]*)\))? \{/g, (_, feed, ev, args) => `function ${feed}_${ev}(${args ?? ''}) {`)
    .replace(/for (\w+), (\w+) in (\w+) \{/g, 'for (const [$1, $2] of $3) {')
    .replace(/for (\w+) in 0\.\.([^\n{]+)\{/g, 'for (let $1 = 0; $1 < $2; $1++) {')
    .replace(/for (\w+) in (\w+) \{/g, 'for (const $1 of $2) {')
    .replace(/\bif ([^\n{]+)\{/g, 'if ($1) {')
    .replace(/let (\w+): [\w?]+ =/g, 'let $1 =')
    .replace(/map<[^>]*>\(\d+\)/g, 'new Map()')
    // named arguments become positional: f(a, tf: b) -> f(a, b)
    .replace(/([,(]\s*)[a-zA-Z]\w*: /g, '$1')
    .replace(/\.len\b/g, '.length');
}

// A rolling buffer: fixed capacity, oldest first, the oldest evicted on push when full.
class Rolling extends Array {
  constructor(capacity, items = []) { super(); this.capacity = capacity; for (const x of items) this.push(x); }
  push(x) { if (this.length >= this.capacity) this.shift(); return super.push(x); }
  get isFull() { return this.length >= this.capacity; }
  avg() { return this.length ? this.reduce((a, b) => a + b, 0) / this.length : null; }
  max() { return this.length ? Math.max(...this) : null; }
  clear() { this.length = 0; }
  static get [Symbol.species]() { return Array; }
}

const WEEK = 604800, MONDAY = 3 * 86400;
const context = {
  Math, console,
  math: { ...Object.fromEntries(Object.getOwnPropertyNames(Math).map(k => [k, Math[k]])), isFinite: Number.isFinite },
  float: Number, int: Math.trunc, unix: x => x,
  str: { format: (template, ...values) => template.replace(/\{(\d+)[^}]*\}/g, (_, i) => values[+i]),
    concat: (...parts) => parts.join('') },
  // times are unix seconds; a timeframe is its length in seconds (weeks start on Monday, as MMT's UTC weeks)
  time: {
    unixSeconds: t => t, fromUnixSeconds: t => t,
    floor: (t, tf) => tf === WEEK ? Math.floor((t + MONDAY) / WEEK) * WEEK - MONDAY : Math.floor(t / tf) * tf,
    shiftBars: (t, n, tf) => t + n * tf,
  },
  plots: {},
  calls: [],
};
// a plot or drawing records what it is given
context.recorder = name => ({
  plot: v => { (context.plots[name] ??= []).push(v); },
  clear: () => { (context.plots[name] ??= []).push('clear'); },
});
for (const [k, v] of Object.entries(input.context ?? {})) {
  if (v && typeof v === 'object' && v.rolling !== undefined) context[k] = new Rolling(v.rolling, v.items ?? []);
  else if (v && typeof v === 'object' && v.map) context[k] = new Map(Object.entries(v.map));
  else if (v && typeof v === 'object' && v.pairs) context[k] = new Map(v.pairs);
  else context[k] = v;
}
for (const name of input.recorders ?? []) context[name] = context.recorder(name);
vm.createContext(context);
for (const marker of input.blocks ?? []) vm.runInContext(translate(block(marker)), context);
for (const stub of input.stubs ?? []) vm.runInContext(stub, context);
const results = (input.calls ?? []).map(c => vm.runInContext(`${c.fn}(...${JSON.stringify(c.args ?? [])})`, context));
const read = Object.fromEntries((input.read ?? []).map(k => [k, context[k]]));
console.log(JSON.stringify({ results, read, plots: context.plots }));
