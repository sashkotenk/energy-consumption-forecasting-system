import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../docs/api/openapi.json',
  output: 'src/generated/api',
});
