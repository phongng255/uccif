#!/usr/bin/env node

/**
 * Node.js entry point for UCCIF CLI (supports `npx @phongng255/uccif <command>`).
 * Automatically locates a Python 3.8+ interpreter and delegates to scripts/uccif_main.py.
 */

const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const mainScript = path.join(__dirname, '..', 'plugins', 'uccif', 'scripts', 'uccif_main.py');

function findPython() {
  const candidates = process.platform === 'win32'
    ? ['python', 'py', 'python3']
    : ['python3', 'python'];

  for (const cmd of candidates) {
    try {
      const args = cmd === 'py' ? ['-3', '-c'] : ['-c'];
      args.push('import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)');
      const res = spawnSync(cmd, args, { stdio: 'ignore' });
      if (res.status === 0) {
        return cmd === 'py' ? { bin: 'py', prefixArgs: ['-3'] } : { bin: cmd, prefixArgs: [] };
      }
    } catch (_) {}
  }
  return null;
}

const py = findPython();
if (!py) {
  console.error('uccif: Error - Python 3.8+ was not found on PATH (tried python3, python, py -3).');
  process.exit(127);
}

const child = spawn(py.bin, [...py.prefixArgs, mainScript, ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: {
    ...process.env,
    PYTHONDONTWRITEBYTECODE: '1'
  }
});

child.on('exit', (code) => {
  process.exit(code ?? 0);
});
