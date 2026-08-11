import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config'

// Kept out of `vite.config.ts` so the build config typechecks against Vite's own
// `UserConfig`, which has no `test` key.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }),
)
