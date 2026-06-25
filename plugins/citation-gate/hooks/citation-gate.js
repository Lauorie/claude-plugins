#!/usr/bin/env node
/**
 * Stop Hook: Citation verification gate (non-skill writing path)
 * Event: Stop
 * 解析 transcript 找本会话改过的 .tex/.bib/.md，有引用就跑 citation_gate 校验器；
 * HARD_FAIL → block 返工（最多 MAX_ROUNDS 轮防死锁），否则放行。
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const HOME = os.homedir();
// Plugin root = the directory that contains this hook's `hooks/` folder.
// The bundled `citation_gate` Python package lives at <PLUGIN_ROOT>/citation_gate,
// so PYTHONPATH must be PLUGIN_ROOT for `python3 -m citation_gate` to resolve it.
const PLUGIN_ROOT = process.env.CLAUDE_PLUGIN_ROOT || path.resolve(__dirname, '..');
const LIB_DIR = PLUGIN_ROOT;
// Per-user state (block-round counters) stays under the user's home, not the plugin.
const ROUNDS_DIR = path.join(HOME, '.claude', '.cache', 'citation_gate', 'rounds');
const MAX_ROUNDS = 3;
const EXTS = new Set(['.tex', '.bib', '.md']);

function collectCandidateFiles(transcriptPath) {
  const seen = [];
  const add = (fp) => {
    if (fp && EXTS.has(path.extname(fp).toLowerCase())
        && fs.existsSync(fp) && !seen.includes(fp)) seen.push(fp);
  };
  let lines = [];
  try {
    lines = fs.readFileSync(transcriptPath, 'utf8').split('\n').filter(Boolean);
  } catch { return []; }
  for (const line of lines) {
    let ev;
    try { ev = JSON.parse(line); } catch { continue; }
    const content = ev && ev.message && ev.message.content;
    if (!Array.isArray(content)) continue;
    for (const block of content) {
      if (block && block.type === 'tool_use'
          && ['Write', 'Edit', 'MultiEdit'].includes(block.name)) {
        add(block.input && block.input.file_path);
      }
    }
  }
  return seen;
}

function hasCitationSignal(filePath) {
  let text = '';
  try { text = fs.readFileSync(filePath, 'utf8'); } catch { return false; }
  if (text.includes('<!-- citation-gate: skip -->')) return false;
  return /\\bibitem|\\cite|\[\d+\]|@(inproceedings|article|misc|book)\b/m.test(text);
}

function readRounds(sessionId) {
  try {
    return JSON.parse(fs.readFileSync(path.join(ROUNDS_DIR, `${sessionId}.json`), 'utf8')).n || 0;
  } catch { return 0; }
}
function bumpRounds(sessionId) {
  fs.mkdirSync(ROUNDS_DIR, { recursive: true });
  const n = readRounds(sessionId) + 1;
  fs.writeFileSync(path.join(ROUNDS_DIR, `${sessionId}.json`), JSON.stringify({ n }));
  return n;
}
function resetRounds(sessionId) {
  try { fs.unlinkSync(path.join(ROUNDS_DIR, `${sessionId}.json`)); } catch { /* noop */ }
}

function runVerifier(files) {
  const result = spawnSync('python3', ['-m', 'citation_gate', '--json', ...files], {
    env: { ...process.env, PYTHONPATH: LIB_DIR },
    encoding: 'utf8', timeout: 120000,
  });
  if (result.error) throw result.error;
  const out = result.stdout || '';
  if (!out.trim()) {
    throw new Error(`verifier produced no output (exit=${result.status}): ${(result.stderr || '').slice(0, 200)}`);
  }
  return JSON.parse(out);
}

function decide(report, roundCount, maxRounds) {
  const hard = report.hardFail || report.hard_fail || [];
  const soft = report.softWarn || report.soft_warn || [];
  if (hard.length === 0) {
    let msg = '引用校验通过。';
    if (soft.length) msg += ` ${soft.length} 条未能核实，已标 [unverified]，请人工确认。`;
    return { block: false, message: msg };
  }
  if (roundCount >= maxRounds) {
    return { block: false, message:
      `引用校验仍有 ${hard.length} 条疑似编造，但已达返工上限（${maxRounds} 轮），放行。请人工(manual)复核：\n`
      + hard.map((h) => `  [${h.index}] ${h.message}`).join('\n') };
  }
  const detail = hard.map((h) => `  [${h.index}] ${h.message}`).join('\n');
  return { block: true, message:
    `检测到 ${hard.length} 条疑似编造的引用，请逐条按权威记录修正后再交付：\n${detail}` };
}

function main() {
  let input = {};
  try {
    const raw = fs.readFileSync(0, 'utf8');
    if (raw.trim()) input = JSON.parse(raw);
  } catch { /* empty */ }

  const pass = (sysMsg) => {
    console.log(JSON.stringify(sysMsg ? { continue: true, systemMessage: sysMsg }
                                       : { continue: true }));
    process.exit(0);
  };

  if (process.env.CITATION_GATE === 'off') return pass();
  const sessionId = input.session_id || 'unknown';

  const files = collectCandidateFiles(input.transcript_path || '')
    .filter(hasCitationSignal);
  if (files.length === 0) { resetRounds(sessionId); return pass(); }

  let report;
  try {
    report = runVerifier(files);
  } catch (e) {
    return pass(`引用校验器未能运行（${(e && e.message || '').slice(0, 120)}），本次跳过。`);
  }

  const round = readRounds(sessionId);
  const d = decide(report, round, MAX_ROUNDS);
  if (d.block) {
    bumpRounds(sessionId);
    console.log(JSON.stringify({ decision: 'block', reason: d.message }));
    process.exit(0);
  }
  resetRounds(sessionId);
  return pass(d.message);
}

if (require.main === module) main();

module.exports = { collectCandidateFiles, hasCitationSignal, decide,
                   readRounds, bumpRounds, resetRounds };
