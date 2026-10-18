const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const cli = fs.readFileSync(path.join(root, 'bin', 'kemory-community.js'), 'utf8');
const files = pkg.files || [];

if (!/^0\.1\.\d+(-[0-9A-Za-z.-]+)?$/.test(pkg.version)) {
  throw new Error(`unexpected package version for v0.1 release: ${pkg.version}`);
}

if (!cli.includes(`const VERSION = '${pkg.version}'`)) {
  throw new Error('CLI VERSION must match package.json version');
}

for (const required of [
  'ghcr.io/sekondbrainailabs/kemory-community-api',
  'ghcr.io/sekondbrainailabs/kemory-community-dashboard',
]) {
  if (!cli.includes(required)) {
    throw new Error(`CLI is missing default image ${required}`);
  }
}

for (const required of [
  'bin/',
  'config/',
  'postinstall.js',
  'scripts/',
  'README.md',
  'LICENSE',
  'NOTICE',
]) {
  if (!files.includes(required)) {
    throw new Error(`package.json files must include ${required}`);
  }
}

const bundle = JSON.parse(fs.readFileSync(path.join(root, 'config', 'community-bundle.json'), 'utf8'));
if (bundle.default_profile !== 'minimal') {
  throw new Error('Community bundle default profile must remain minimal');
}
for (const repository of bundle.repository_integrations) {
  if (repository.default_bundle !== false) {
    throw new Error(`${repository.repository} must not enter the default bundle without admission gates`);
  }
}

for (const forbidden of ['backend/', 'kemory/', 'dashboard/', '.github/', 'docs/']) {
  if (files.includes(forbidden)) {
    throw new Error(`package.json files must not include ${forbidden}; npm ships the CLI shim only`);
  }
}

console.log(`kemory-community package ${pkg.version} verified`);
