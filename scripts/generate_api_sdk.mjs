import { readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, '..');
const outputDirectory = resolve(repositoryRoot, 'frontend/src/generated/api');

rmSync(outputDirectory, { recursive: true, force: true });

const dockerArgs = ['run', '--rm'];
if (process.platform !== 'win32' && process.getuid && process.getgid) {
  dockerArgs.push('--user', `${process.getuid()}:${process.getgid()}`);
}

dockerArgs.push(
  '--volume',
  `${repositoryRoot}:/work`,
  '--workdir',
  '/work',
  'openapitools/openapi-generator-cli:v7.24.0',
  'generate',
  '--input-spec',
  '/work/docs/api/openapi.json',
  '--generator-name',
  'typescript-fetch',
  '--output',
  '/work/frontend/src/generated/api',
  '--global-property',
  'apiDocs=false,modelDocs=false,apiTests=false,modelTests=false',
  '--additional-properties',
  'hideGenerationTimestamp=true,supportsES6=true,useSingleRequestParameter=true',
);

const result = spawnSync('docker', dockerArgs, {
  cwd: repositoryRoot,
  stdio: 'inherit',
});

if (result.error) {
  console.error(`Failed to start Docker: ${result.error.message}`);
  process.exit(1);
}

if (result.status === 0) {
  for (const relativePath of ['index.ts', 'apis/index.ts', 'models/index.ts']) {
    const path = resolve(outputDirectory, relativePath);
    const source = readFileSync(path, 'utf8');
    writeFileSync(path, source.replace('/* eslint-disable */\n', ''), 'utf8');
  }
}

process.exit(result.status ?? 1);
