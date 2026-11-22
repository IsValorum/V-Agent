// Issue #2: the interface sends back the rounds and notes exactly as the engine read them
// (the same rules as conversation_codec.model_history, tested in test_prompt_prefix.py).
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync('agent/ui/app/composer.js', 'utf8');
const start = source.indexOf('function conversationForModel(');
const end = source.indexOf('\nasync function compactConversationContext');
assert(start >= 0 && end > start, 'conversationForModel not found');
const ctx = { fileFromDraft: () => null, structuredClone };
vm.createContext(ctx);
vm.runInContext(source.slice(start, end) + '\nthis.conversationForModel=conversationForModel;', ctx);

const turn = [
  { role: 'assistant', content: 'Reading.', reasoning_content: 'plan',
    tool_calls: [{ id: 'abc', type: 'function', function: { name: 'pc__fs_read', arguments: '{"path": "a.txt"}' } }] },
  { role: 'tool', tool_call_id: 'abc', content: 'text' },
];
const saved = [
  { role: 'user', content: 'read a', model_suffix: '\n\n[date 1]' },
  { role: 'assistant', content: 'Reading.\n\nDone.', reasoning_content: 'planthink',
    tool_trace: [{ id: 't1', name: 'pc__fs_read', args: { path: 'a.txt' }, executed: true, result: 'text', round: 1 }],
    model_turn: turn, model_final: { content: 'Done.', reasoning_content: 'think' } },
  { role: 'user', content: 'next', model_suffix: '\n\n[old date]' },
];
const out = JSON.parse(JSON.stringify(ctx.conversationForModel(saved)));
assert.deepStrictEqual(out[0], { role: 'user', content: 'read a\n\n[date 1]' });
assert.deepStrictEqual(out.slice(1, 3), turn);
assert.deepStrictEqual(out[3], { role: 'assistant', content: 'Done.', reasoning_content: 'think' });
assert.deepStrictEqual(out[4], { role: 'user', content: 'next' });
assert.strictEqual(out.length, 5);

// A reply without the engine rounds (stopped, or saved by an older version) is rebuilt from its trace.
const legacy = ctx.conversationForModel([{ role: 'user', content: 'read a' },
  { role: 'assistant', content: 'Done.', tool_trace: [{ id: 't1', name: 'pc__fs_read', args: { path: 'a.txt' }, executed: true, result: 'text', round: 1 }] }]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(legacy.map(m => m.role))), ['user', 'assistant', 'tool', 'assistant']);
console.log('exact history ok');
