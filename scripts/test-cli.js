const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const cli = path.join(root, 'bin', 'kemory-community.js');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'kemory-community-cli-'));
const sharedTmp = fs.mkdtempSync(path.join(os.tmpdir(), 'kemory-community-shared-cli-'));

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

const bridge = fs.readFileSync(path.join(tmp, 'kemory-mcp.js'), 'utf8');
if (!bridge.includes("'kemory', 'mcp', 'serve'")) throw new Error('Docker MCP bridge was not generated');
const mcpConfig = JSON.parse(fs.readFileSync(path.join(tmp, 'mcp.json'), 'utf8'));
if (mcpConfig.mcpServers.kemory.command !== 'node') throw new Error('MCP config should use Node bridge');
run(['mcp-config', '--dir', tmp]);

run(['init', '--runtime', 'docker', '--infra', 'shared', '--dir', sharedTmp]);
const sharedConfig = JSON.parse(fs.readFileSync(path.join(sharedTmp, 'config.json'), 'utf8'));
if (sharedConfig.infrastructure !== 'shared') throw new Error('shared infrastructure mode was not persisted');
if (sharedConfig.ports.postgres !== 5432) throw new Error('shared Postgres must use infra port 5432');
if (sharedConfig.ports.redis_database !== 14) throw new Error('shared Redis database must be 14');

const sharedCompose = fs.readFileSync(path.join(sharedTmp, 'docker-compose.yml'), 'utf8');
if (!sharedCompose.includes('external: true')) throw new Error('shared-infra must be external');
if (!sharedCompose.includes('redis://redis:6379/')) throw new Error('shared Redis was not configured');
if (/^  (postgres|redis):$/m.test(sharedCompose)) {
  throw new Error('shared mode must not create Postgres or Redis services');
}
const sharedPublished = sharedCompose.match(/^\s+- "(.*:\d+)"$/gm) || [];
if (sharedPublished.length !== 2) throw new Error('shared mode should publish only API and dashboard');
for (const mapping of sharedPublished) {
  if (!mapping.includes('"127.0.0.1:')) {
    throw new Error(`shared published port must bind 127.0.0.1, got:${mapping}`);
  }
}

const fakeInfra = fs.mkdtempSync(path.join(os.tmpdir(), 'kemory-community-fake-infra-'));
const fakeBin = path.join(fakeInfra, 'bin');
fs.mkdirSync(path.join(fakeInfra, 'scripts'), { recursive: true });
fs.mkdirSync(fakeBin);
fs.writeFileSync(path.join(fakeInfra, '.env'), 'POSTGRES_USER=admin\nPOSTGRES_PASSWORD=test-admin-password\n');
for (const script of ['start.sh', 'create-app-db.sh']) {
  fs.writeFileSync(path.join(fakeInfra, 'scripts', script), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
}
fs.writeFileSync(path.join(fakeBin, 'docker'), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
run(['provision-shared', '--dir', sharedTmp, '--infra-dir', fakeInfra], {
  env: { ...process.env, PATH: `${fakeBin}:${process.env.PATH}` },
});
const expectedDbPassword = crypto
  .createHash('sha256')
  .update('kemory_community:test-admin-password')
  .digest('hex')
  .slice(0, 32);
const sharedEnv = fs.readFileSync(path.join(sharedTmp, 'kemory.env'), 'utf8');
if (!sharedEnv.includes(`KEMORY_COMMUNITY_DB_PASSWORD=${expectedDbPassword}`)) {
  throw new Error('provision-shared did not persist the deterministic database password');
}
console.log('CLI scaffold tests passed');
