import { defineConfig } from 'orval';

export default defineConfig({
  energyForecast: {
    input: {
      target: '../docs/api/openapi.json',
    },
    output: {
      mode: 'single',
      target: 'src/generated/api/client.ts',
      schemas: 'src/generated/api/models',
      client: 'fetch',
    },
  },
});
