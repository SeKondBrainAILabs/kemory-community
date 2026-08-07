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
const composePath = path.join(tmp, 'docker-compose.yml');
if (!fs.existsSync(composePath)) {
  throw new Error('docker-compose.yml was not generated');
}

// Community is local-first: every published port must bind loopback only.
// A bare "HOST:CONTAINER" mapping binds 0.0.0.0, which would expose the API,
// the dashboard (it serves the API key at /config.json) and Postgres to the
// whole network.
const compose = fs.readFileSync(composePath, 'utf8');
const published = compose.match(/^\s+- "(.*:\d+)"$/gm) || [];
if (published.length === 0) throw new Error('no published ports found in generated compose');
for (const mapping of published) {
  if (!mapping.includes('"127.0.0.1:')) {
    throw new Error(`published port must bind 127.0.0.1, got:${mapping}`);
  }
}

run(['doctor', '--dir', tmp]);
console.log('CLI scaffold tests passed');
