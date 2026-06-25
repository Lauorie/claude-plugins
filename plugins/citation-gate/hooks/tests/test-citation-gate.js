const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const gate = require('../citation-gate.js');

// --- decide() ---
{
  const r = gate.decide({ hardFail: [{ index: 40, message: 'authors/year fabricated; 正确: Muhao Chen IJCAI 2018' }], softWarn: [], skip: [] }, 0, 3);
  assert.strictEqual(r.block, true);
  assert.ok(r.message.includes('40'));
  assert.ok(r.message.includes('Muhao Chen'));
}
{
  const r = gate.decide({ hardFail: [], softWarn: [{ index: 1, message: 'unverified' }], skip: [] }, 0, 3);
  assert.strictEqual(r.block, false);
}
{ // 达到上限：硬错仍在也放行（防死锁），但提示人工
  const r = gate.decide({ hardFail: [{ index: 9, message: 'x' }], softWarn: [], skip: [] }, 3, 3);
  assert.strictEqual(r.block, false);
  assert.ok(/人工|manual/i.test(r.message));
}

// --- collectCandidateFiles() ---
{
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cg-'));
  const paper = path.join(tmp, 'paper.md');
  fs.writeFileSync(paper, '[1] A. Author. Title. ICML, 2020.');
  const other = path.join(tmp, 'note.txt');
  fs.writeFileSync(other, 'irrelevant');
  const tr = path.join(tmp, 'transcript.jsonl');
  fs.writeFileSync(tr, [
    JSON.stringify({ type: 'assistant', message: { content: [
      { type: 'tool_use', name: 'Write', input: { file_path: paper } },
      { type: 'tool_use', name: 'Edit', input: { file_path: other } },
    ] } }),
    JSON.stringify({ type: 'user', message: { content: 'hi' } }),
  ].join('\n'));
  const files = gate.collectCandidateFiles(tr);
  assert.deepStrictEqual(files, [paper]); // 只留存在的 .md，.txt 被滤掉
}

// --- hasCitationSignal() + skip 标记 ---
{
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cg-'));
  const withCite = path.join(tmp, 'a.md');
  fs.writeFileSync(withCite, 'see [12] Foo Bar. Baz. AAAI, 2019.');
  assert.strictEqual(gate.hasCitationSignal(withCite), true);
  const skipped = path.join(tmp, 'b.md');
  fs.writeFileSync(skipped, '<!-- citation-gate: skip -->\n[1] X. Y. Z. 2020.');
  assert.strictEqual(gate.hasCitationSignal(skipped), false);
  const plain = path.join(tmp, 'c.md');
  fs.writeFileSync(plain, 'just a sentence.');
  assert.strictEqual(gate.hasCitationSignal(plain), false);
}

console.log('all hook unit tests passed');
