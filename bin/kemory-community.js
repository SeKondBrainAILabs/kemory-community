#!/usr/bin/env node
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const VERSION = '0.1.0';
const DEFAULTS = {
  runtime: 'docker',
  apiPort: 8111,
  dashboardPort: 5175,
  postgresPort: 5434,
  apiContainerPort: 8000,
  dashboardContainerPort: 5173,
  postgresContainerPort: 5432,
  apiImage: 'ghcr.io/sekondbrainailabs/kemory-community-api:0.1.0',
  dashboardImage: 'ghcr.io/sekondbrainailabs/kemory-community-dashboard:0.1.0',
};

function usage(exitCode = 0) {
  const text = `
kemory-community ${VERSION}

Usage:
  kemory-community init [--runtime docker|local] [--dir <path>] [--force]
  kemory-community up [--dir <path>]
  kemory-community down [--dir <path>]
  kemory-community doctor [--dir <path>]
  kemory-community mcp-config [--dir <path>]
  kemory-community ports

Docker is the default runtime. The local runtime only writes config; v0.1
will wire the downloaded platform binary.

Default local Docker ports:
  API        http://127.0.0.1:${DEFAULTS.apiPort}
  Dashboard  http://127.0.0.1:${DEFAULTS.dashboardPort}
  Postgres   127.0.0.1:${DEFAULTS.postgresPort}

Image overrides:
  --image <api-image>              API image; dashboard defaults to <api-image>-dashboard
  --dashboard-image <image>        Dashboard image
`;
  (exitCode === 0 ? console.log : console.error)(text.trimStart());
  process.exit(exitCode);
}

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) {
      args._.push(arg);
      continue;
    }
    const key = arg.slice(2);
    if (key === 'help') {
      args._.push('help');
      continue;
    }
    if (key === 'force') {
      args.force = true;
      continue;
    }
    const value = argv[i + 1];
    if (!value || value.startsWith('--')) {
      fail(`missing value for --${key}`);
    }
    args[key] = value;
    i += 1;
  }
  if (argv.includes('-h')) {
    args._.push('help');
  }
  return args;
}

function fail(message, exitCode = 1) {
  console.error(`kemory-community: ${message}`);
  process.exit(exitCode);
}

function setupDir(args) {
  return path.resolve(args.dir || path.join(process.cwd(), '.kemory-community'));
}

function intArg(args, name, fallback) {
  const raw = args[name];
  if (raw === undefined) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    fail(`--${name} must be a TCP port number`);
  }
  return parsed;
}

function configFromArgs(args) {
  const runtime = args.runtime || DEFAULTS.runtime;
  if (!['docker', 'local'].includes(runtime)) {
    fail('--runtime must be docker or local');
  }
  return {
    runtime,
    apiPort: intArg(args, 'api-port', DEFAULTS.apiPort),
    dashboardPort: intArg(args, 'dashboard-port', DEFAULTS.dashboardPort),
    postgresPort: intArg(args, 'postgres-port', DEFAULTS.postgresPort),
    apiContainerPort: DEFAULTS.apiContainerPort,
    dashboardContainerPort: DEFAULTS.dashboardContainerPort,
    postgresContainerPort: DEFAULTS.postgresContainerPort,
    apiImage: args['api-image'] || args.image || DEFAULTS.apiImage,
    dashboardImage: args['dashboard-image'] || (args.image ? `${args.image}-dashboard` : DEFAULTS.dashboardImage),
    apiKey: args['api-key'] || `kc_${crypto.randomBytes(24).toString('base64url')}`,
  };
}

function dockerCompose(config) {
  return `services:
  kemory-api:
    image: \${KEMORY_COMMUNITY_IMAGE:-${config.apiImage}}
    environment:
      API_PUBLIC_URL: http://127.0.0.1:${config.apiPort}
      CORS_ORIGINS: http://localhost:${config.dashboardPort}
      DATABASE_URL: postgresql+asyncpg://kemory:kemory_local@postgres:${config.postgresContainerPort}/kemory_community
      DATABASE_URL_SYNC: postgresql://kemory:kemory_local@postgres:${config.postgresContainerPort}/kemory_community
      KEMORY_COMMUNITY_CONFIG: /app/.community/config.json
      KMV_VECTOR_BACKEND: pgvector
      KMV_BLOB_BACKEND: local_fs
      KMV_BLOB_LOCAL_ROOT: /app/.community/artifacts
      KMV_IDENTITY: local_single_user
      KMV_TELEMETRY: noop
      KMV_COGNITION_ENTERPRISE: "false"
      KEMORY_LOCAL_API_KEY: \${KEMORY_LOCAL_API_KEY}
      KEMORY_LOCAL_BLOB_SIGNING_KEY: community-local-blob-signing-key-32-bytes
      OPENAI_API_KEY: \${OPENAI_API_KEY:-}
      VOYAGE_API_KEY: \${VOYAGE_API_KEY:-}
      COHERE_API_KEY: \${COHERE_API_KEY:-}
      KEMORY_RUN_MIGRATIONS: "true"
      MEMORY_VAULT_MODE: platform
      REDIS_URL: redis://redis:6379/0
      TENANT_ENFORCEMENT: "off"
      WORKERS: "1"
    ports:
      - "127.0.0.1:${config.apiPort}:${config.apiContainerPort}"
    volumes:
      - kemory_data:/app/.community
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:${config.apiContainerPort}/health/ready"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 30s
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  dashboard:
    image: \${KEMORY_COMMUNITY_DASHBOARD_IMAGE:-${config.dashboardImage}}
    environment:
      API_PUBLIC_URL: http://127.0.0.1:${config.apiPort}
      API_KEY: \${KEMORY_LOCAL_API_KEY}
      SKIP_AUTH: "true"
    ports:
      - "127.0.0.1:${config.dashboardPort}:${config.dashboardContainerPort}"
    depends_on:
      kemory-api:
        condition: service_healthy

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: kemory
      POSTGRES_PASSWORD: kemory_local
      POSTGRES_DB: kemory_community
    ports:
      - "127.0.0.1:${config.postgresPort}:${config.postgresContainerPort}"
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U kemory -d kemory_community"]
      interval: 5s
      timeout: 5s
      retries: 20

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 20

volumes:
  kemory_data:
  pg_data:
`;
}

function envFile(config) {
  return `KEMORY_LOCAL_API_KEY=${config.apiKey}
KEMORY_COMMUNITY_IMAGE=${config.apiImage}
KEMORY_COMMUNITY_DASHBOARD_IMAGE=${config.dashboardImage}
OPENAI_API_KEY=
VOYAGE_API_KEY=
COHERE_API_KEY=
`;
}

function jsonConfig(config) {
  return JSON.stringify(
    {
      version: 1,
      runtime: config.runtime,
      urls: {
        api: `http://127.0.0.1:${config.apiPort}`,
        dashboard: `http://127.0.0.1:${config.dashboardPort}`,
      },
      ports: {
        api: config.apiPort,
        dashboard: config.dashboardPort,
        postgres: config.postgresPort,
      },
      images: {
        api: config.apiImage,
        dashboard: config.dashboardImage,
      },
      storage: 'docker_named_volumes',
    },
    null,
    2,
  ) + '\n';
}

function mcpBridge() {
  return `#!/usr/bin/env node
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const dir = __dirname;
const result = spawnSync('docker', [
  'compose', '--env-file', path.join(dir, 'kemory.env'),
  '-f', path.join(dir, 'docker-compose.yml'),
  'exec', '-T', '-e', 'KEMORY_URL=http://127.0.0.1:8000',
  'kemory-api', 'kemory', 'mcp', 'serve',
], { stdio: 'inherit' });

process.exit(result.status ?? 1);
`;
}

function mcpClientConfig(dir) {
  return JSON.stringify({
    mcpServers: {
      kemory: {
        command: 'node',
        args: [path.join(dir, 'kemory-mcp.js')],
        env: {},
      },
    },
  }, null, 2) + '\n';
}

function writeFileOnce(filePath, content, force) {
  if (fs.existsSync(filePath) && !force) {
    fail(`${filePath} already exists; pass --force to overwrite`);
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, { mode: 0o600 });
}

function init(args) {
  const dir = setupDir(args);
  const config = configFromArgs(args);
  fs.mkdirSync(dir, { recursive: true });

  writeFileOnce(path.join(dir, 'config.json'), jsonConfig(config), args.force);
  writeFileOnce(path.join(dir, 'kemory.env'), envFile(config), args.force);

  if (config.runtime === 'docker') {
    writeFileOnce(path.join(dir, 'docker-compose.yml'), dockerCompose(config), args.force);
    writeFileOnce(path.join(dir, 'kemory-mcp.js'), mcpBridge(), args.force);
    writeFileOnce(path.join(dir, 'mcp.json'), mcpClientConfig(dir), args.force);
  } else {
    writeFileOnce(
      path.join(dir, 'local.env'),
      `KEMORY_LOCAL_API_KEY=${config.apiKey}
KEMORY_API_PORT=${config.apiPort}
KEMORY_DASHBOARD_PORT=${config.dashboardPort}
`,
      args.force,
    );
  }

  console.log(`Initialized ${config.runtime} setup in ${dir}`);
  console.log(`API: http://127.0.0.1:${config.apiPort}`);
  console.log(`Dashboard: http://127.0.0.1:${config.dashboardPort}`);
  if (config.runtime === 'docker') {
    console.log(`Run: kemory-community up --dir ${dir}`);
    console.log(`MCP config: ${path.join(dir, 'mcp.json')}`);
  }
}

function composeCommand() {
  const dockerCompose = spawnSync('docker', ['compose', 'version'], { stdio: 'ignore' });
  if (dockerCompose.status === 0) return ['docker', ['compose']];
  const legacyCompose = spawnSync('docker-compose', ['version'], { stdio: 'ignore' });
  if (legacyCompose.status === 0) return ['docker-compose', []];
  fail('Docker Compose is required for --runtime docker');
}

function composeArgs(dir, action) {
  return ['--env-file', path.join(dir, 'kemory.env'), '-f', path.join(dir, 'docker-compose.yml'), action];
}

function readConfig(dir) {
  const target = path.join(dir, 'config.json');
  if (!fs.existsSync(target)) fail(`missing ${target}; run kemory-community init first`);
  try {
    return JSON.parse(fs.readFileSync(target, 'utf8'));
  } catch {
    fail(`${target} is not valid JSON`);
  }
}

function readEnvValue(dir, key) {
  const target = path.join(dir, 'kemory.env');
  if (!fs.existsSync(target)) return '';
  const line = fs.readFileSync(target, 'utf8').split(/\r?\n/).find((item) => item.startsWith(`${key}=`));
  return line ? line.slice(key.length + 1) : '';
}

async function probe(url, options = {}) {
  try {
    const response = await fetch(url, { ...options, signal: AbortSignal.timeout(5_000) });
    return { ok: response.ok, status: response.status };
  } catch (error) {
    return { ok: false, status: error.cause?.code || error.name || 'unreachable' };
  }
}

async function waitForReady(url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await probe(url);
    if (result.ok) return;
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  fail(`timed out waiting for ${url}`);
}

async function up(args) {
  const dir = setupDir(args);
  const composeFile = path.join(dir, 'docker-compose.yml');
  const envFilePath = path.join(dir, 'kemory.env');
  if (!fs.existsSync(composeFile)) {
    fail(`missing ${composeFile}; run kemory-community init --runtime docker first`);
  }
  const [command, baseArgs] = composeCommand();
  const result = spawnSync(command, [...baseArgs, ...composeArgs(dir, 'up'), '-d'], {
    stdio: 'inherit',
  });
  if (result.status !== 0) fail('Docker Compose failed to start');

  const config = readConfig(dir);
  process.stdout.write('Waiting for Kemory API');
  await waitForReady(`${config.urls.api}/health/ready`);
  process.stdout.write(' ready\nWaiting for dashboard');
  await waitForReady(config.urls.dashboard);
  console.log(' ready');
  console.log(`Kemory Community is ready: ${config.urls.dashboard}`);
  console.log(`MCP config: ${path.join(dir, 'mcp.json')}`);
}

function down(args) {
  const dir = setupDir(args);
  const [command, baseArgs] = composeCommand();
  const result = spawnSync(command, [...baseArgs, ...composeArgs(dir, 'down')], { stdio: 'inherit' });
  if (result.status !== 0) fail('Docker Compose failed to stop');
}

async function doctor(args) {
  const dir = setupDir(args);
  const configPath = path.join(dir, 'config.json');
  const composePath = path.join(dir, 'docker-compose.yml');
  const checks = [];
  function report(label, ok, detail) {
    checks.push(ok);
    console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}  ${detail}`);
  }
  console.log('kemory community doctor');
  report('setup', fs.existsSync(configPath), dir);
  report('compose file', fs.existsSync(composePath), composePath);
  const docker = spawnSync('docker', ['--version'], { encoding: 'utf8' });
  report('docker', docker.status === 0, docker.status === 0 ? docker.stdout.trim() : 'missing');
  const compose = spawnSync('docker', ['compose', 'version'], { encoding: 'utf8' });
  report('docker compose', compose.status === 0, compose.status === 0 ? compose.stdout.trim() : 'missing');

  if (fs.existsSync(configPath)) {
    const config = readConfig(dir);
    const readiness = await probe(`${config.urls.api}/health/ready`);
    report('API readiness', readiness.ok, `HTTP ${readiness.status}`);
    const apiKey = readEnvValue(dir, 'KEMORY_LOCAL_API_KEY');
    const auth = await probe(`${config.urls.api}/api/v1/community/settings`, {
      headers: { 'X-API-Key': apiKey },
    });
    report('API key', auth.ok, `HTTP ${auth.status}`);
    const dashboard = await probe(config.urls.dashboard);
    report('dashboard', dashboard.ok, `HTTP ${dashboard.status}`);
  }
  if (checks.includes(false)) process.exitCode = 1;
}

function printMcpConfig(args) {
  const target = path.join(setupDir(args), 'mcp.json');
  if (!fs.existsSync(target)) fail(`missing ${target}; run kemory-community init --runtime docker first`);
  process.stdout.write(fs.readFileSync(target, 'utf8'));
}

function ports() {
  console.log(JSON.stringify({
    api: DEFAULTS.apiPort,
    dashboard: DEFAULTS.dashboardPort,
    postgres: DEFAULTS.postgresPort,
  }, null, 2));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const command = args._[0] || 'help';

  switch (command) {
    case 'init': init(args); break;
    case 'up': await up(args); break;
    case 'down': down(args); break;
    case 'doctor': await doctor(args); break;
    case 'mcp-config': printMcpConfig(args); break;
    case 'ports': ports(); break;
    case 'help':
    case '--help':
    case '-h': usage(0); break;
    default: usage(2);
  }
}

main().catch((error) => fail(error.message || String(error)));
