import tailwindcss from '@tailwindcss/vite'
import { TanStackRouterVite } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig, UserConfig } from 'vite'

const PORT = 57988

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const isLibMode = mode === 'lib'

  // Base configuration that applies to all environments
  const config: UserConfig = {
    plugins: [
      !isLibMode &&
        TanStackRouterVite({
          target: 'react',
          autoCodeSplitting: true,
          generatedRouteTree: 'src/route-tree.gen.ts',
        }),
      react(),
      tailwindcss(),
    ].filter(Boolean),
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5174,
      proxy: {},
    },
  }

  // Library build configuration
  if (isLibMode) {
    config.build = {
      lib: {
        entry: path.resolve(__dirname, 'src/index.ts'),
        name: '@jaaz/agent-ui',
        fileName: (format: string) => `index.${format}.js`,
        formats: ['es'],
      },
      rollupOptions: {
        external: [
          'react',
          'react-dom',
          'react/jsx-runtime',
          '@tanstack/react-router',
          '@tanstack/react-query',
          'i18next',
          'react-i18next',
          'framer-motion',
          'motion',
          'lucide-react',
          'sonner',
          'zustand',
          'immer',
          'nanoid',
          'ahooks',
          'socket.io-client',
          'openai',
          'clsx',
          'tailwind-merge',
          'class-variance-authority',
          /@radix-ui\/.*/,
          /@tanstack\/.*/,
          /@excalidraw\/.*/,
          /@mdxeditor\/.*/,
        ],
        output: {
          globals: {
            react: 'React',
            'react-dom': 'ReactDOM',
            'react/jsx-runtime': 'react/jsx-runtime',
          },
        },
      },
    }
  } else {
    // 应用模式按重型依赖做代码分包，降低首屏核心 chunk 体积
    config.build = {
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return undefined
            if (id.includes('mermaid') || id.includes('cytoscape') || id.includes('dagre') || id.includes('d3-') || id.includes('elkjs') || id.includes('khroma')) {
              return 'diagram-vendor'
            }
            if (id.includes('katex')) {
              return 'math-vendor'
            }
            if (id.includes('react-markdown') || id.includes('remark-') || id.includes('rehype-') || id.includes('micromark') || id.includes('mdast-')) {
              return 'markdown-vendor'
            }
            if (id.includes('@excalidraw')) {
              return 'excalidraw-vendor'
            }
            if (id.includes('@mdxeditor') || id.includes('lexical') || id.includes('prismjs') || id.includes('codemirror')) {
              return 'editor-vendor'
            }
            if (id.includes('@radix-ui') || id.includes('lucide-react') || id.includes('sonner')) {
              return 'ui-vendor'
            }
            if (id.includes('@tanstack') || id.includes('motion') || id.includes('framer-motion') || id.includes('i18next')) {
              return 'app-framework-vendor'
            }
            return undefined
          },
        },
      },
    }
  }

  // Configure server based on environment
  if (mode === 'development') {
    config.server = config.server || {}
    config.server.proxy = {
      '/api': {
        target: `http://127.0.0.1:${PORT}`,
        changeOrigin: true,
        // Uncomment the following if you want to remove the /api prefix when forwarding to Flask
        // rewrite: (path) => path.replace(/^\/api/, '')
      },
      // 代理 Socket.IO WebSocket 与长轮询连接，开发模式走同源代理避免跨域 Cookie 失效
      '/socket.io': {
        target: `http://127.0.0.1:${PORT}`,
        ws: true,
        changeOrigin: true,
      },
      // Also proxy WebSocket connections
      '/ws': {
        target: `ws://127.0.0.1:${PORT}`,
        ws: true,
      },
    }
  }

  return config
})
