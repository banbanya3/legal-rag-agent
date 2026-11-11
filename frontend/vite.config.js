import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端统一请求 /api/xxx，由 Vite 转发到 Flask。
// 好处：浏览器同源、没有 CORS 预检，SSE 也能正常流过代理。
// preview（生产预览）也复用同一份配置，避免 build 之后接口全 404。
const proxy = {
  '/api': {
    target: 'http://127.0.0.1:5000',
    changeOrigin: true,
    // SSE（text/event-stream）不能被缓冲，否则前端要等全部生成完才收到
    configure: (server) => {
      server.on('proxyReq', (proxyReq) => {
        proxyReq.setHeader('Accept-Encoding', 'identity')
      })
    },
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 显式绑 IPv4：Windows 下默认可能只监听 [::1]，导致 127.0.0.1 连不上
    host: '127.0.0.1',
    port: 5173,
    proxy,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy,
  },
})
