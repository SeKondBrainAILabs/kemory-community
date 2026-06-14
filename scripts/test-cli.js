const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const cli = path.join(root, 'bin', 'kemory-community.js');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'kemory-community-cli-'));

function run(args, options = {}) {
  const result = spawnSync(process.execPath, [cli, ...args], {
    encoding: 'utf8',
    ...options,
  });
  if (result.status !== 0) {
    process.stderr.write(result.stdout);
    process.stderr.write(result.stderr);
    throw new Error(`command failed: ${args.join(' ')}`);
  }
  return result;
}

run(['ports']);
run(['init', '--runtime', 'docker', '--dir', tmp]);

const config = JSON.parse(fs.readFileSync(path.join(tmp, 'config.json'), 'utf8'));
if (config.runtime !== 'docker') throw new Error('runtime should be docker');
if (config.ports.api !== 8111) throw new Error('api port should be 8111');
if (!fs.existsSync(path.join(tmp, 'docker-compose.yml'))) {
  throw new Error('docker-compose.yml was not generated');
}

run(['doctor', '--dir', tmp]);
console.log('CLI scaffold tests passed');
