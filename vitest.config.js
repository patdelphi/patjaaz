import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    globals: true,
    testTimeout: 15000,
    // 仅收集 React 单元测试；Electron 安装器测试脚本会访问外网或真实用户目录。
    include: [
      'react/test/**/*.test.js',
      'react/test/**/*.test.jsx',
      'react/test/**/*.test.ts',
    ],
    exclude: ['node_modules/**', 'dist/**'],
    threads: false,
    isolate: false,
    pool: 'forks',
    poolOptions: {
      forks: {
        singleFork: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': new URL('./react/src', import.meta.url).pathname,
    },
  },
})
