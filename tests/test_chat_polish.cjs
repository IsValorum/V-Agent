const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const html = fs.readFileSync('agent/ui/dist/v-agent.html', 'utf8');
for (const id of ['newTempChat', 'tempChatBadge', 'promoteTempChat', 'turnNav', 'turnPrev', 'turnNext', 'turnPos', 'notifyOnDone', 'globalInstructions', 'saveGlobalInstructions', 'openCommandPalette', 'openPromptLibrary', 'setupPolishUI', 'computeLocalUsageStats']) {
  assert(html.includes(id), `Expected ${id} in built UI`);
}

class Element {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.textContent = '';
    this.hidden = false;
    this.disabled = false;
    this.dataset = {};
    this.attributes = {};
    this.offsetTop = 0;
    this.scrolled = 0;
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = [...items]; }
  querySelector(sel) {
    if (sel.includes('.response-model')) return this.children.find(x => x.className === 'response-model') || null;
    return null;
  }
  scrollIntoView() { this.scrolled++; }
}

const nav = new Element('div'), pos = new Element('span'), prev = new Element('button'), next = new Element('button');
const turns = [new Element('div'), new Element('div'), new Element('div')];
turns[0].offsetTop = 0; turns[1].offsetTop = 400; turns[2].offsetTop = 900;
const chatView = { scrollTop: 0, querySelectorAll: () => turns };
const byId = { '#turnNav': nav, '#turnPos': pos, '#turnPrev': prev, '#turnNext': next };
let followValue = true;

const ctx = {
  document: {
    createElement: tag => new Element(tag),
    createTextNode: text => ({ textContent: String(text) }),
  },
  window: { VALI18n: { locale: 'en-US' } },
  uiText: x => x,
  modelNames: { 'm1': 'Demo Model' },
  chatView,
  $: sel => byId[sel] || null,
  setFollow: v => { followValue = v; },
};
vm.createContext(ctx);

// Response model + timestamp
vm.runInContext(
  html.slice(html.indexOf('function formatResponseTime('), html.indexOf('function updateResponsePerformance(')),
  ctx,
);
const row = new Element('div');
ctx.showResponseModel(row, { model: 'm1', generated_at: '2026-11-21T14:35:00Z' });
const label = row.querySelector(':scope > .response-model');
assert(label, 'response-model created');
const timeEl = label.children.find(c => c && c.className === 'response-time');
assert(timeEl && timeEl.dateTime === '2026-11-21T14:35:00Z' && timeEl.textContent.length >= 4, 'response-time rendered');

const rowNoTime = new Element('div');
ctx.showResponseModel(rowNoTime, { model: 'm1' });
assert(!rowNoTime.querySelector(':scope > .response-model').children.some(c => c && c.className === 'response-time'), 'no time when missing');

// Turn navigation
vm.runInContext(
  html.slice(html.indexOf('function turnNodes('), html.indexOf('function addAssistantBox(')),
  ctx,
);
ctx.syncTurnNav();
assert.strictEqual(nav.hidden, false);
assert.strictEqual(pos.textContent, '1 / 3');
assert.strictEqual(prev.disabled, true);
assert.strictEqual(next.disabled, false);

ctx.jumpTurn(1);
assert.strictEqual(turns[1].scrolled, 1);
assert.strictEqual(pos.textContent, '2 / 3');
assert.strictEqual(followValue, false);

chatView.scrollTop = 920;
ctx.syncTurnNav();
assert.strictEqual(pos.textContent, '3 / 3');
assert.strictEqual(next.disabled, true);

turns.length = 1;
ctx.syncTurnNav();
assert.strictEqual(nav.hidden, true);

// Local usage statistics (strictly real figures, never estimated)
const statsCtx = { modelNames: { 'm1': 'Local Qwen' } };
vm.createContext(statsCtx);
vm.runInContext(
  html.slice(html.indexOf('function computeLocalUsageStats('), html.indexOf('window.computeLocalUsageStats =')),
  statsCtx,
);
const usage = statsCtx.computeLocalUsageStats([
  {
    id: 'c1', pinned: true, messages: [
      { role: 'user', content: 'hi' },
      { role: 'assistant', model: 'm1', content: 'hello', performance: { decode: 40, detail: { generated: 120 } } },
    ],
  },
  {
    id: 'c2', archived: true, messages: [
      { role: 'user', content: 'next' },
      { role: 'assistant', model_name: 'Cloud Model', content: 'ok', usage: { completion_tokens: 80 }, performance: { decode: 60 } },
    ],
  },
]);
assert.strictEqual(usage.chats, 2);
assert.strictEqual(usage.pinned, 1);
assert.strictEqual(usage.archived, 1);
assert.strictEqual(usage.userMsgs, 2);
assert.strictEqual(usage.assistantMsgs, 2);
assert.strictEqual(usage.generatedTokens, 200);
assert.strictEqual(usage.avgDecode, 50);
assert.strictEqual(usage.topModels.length, 2);

console.log('Response timestamps, turn navigation, temporary chat, AGENTS.md and Unsloth-inspired screens passed.');
