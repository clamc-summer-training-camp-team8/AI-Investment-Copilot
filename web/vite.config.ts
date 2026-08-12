import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        // 可覆盖目标便于在隔离端口做端到端验证；常规本地
        // 开发仍固定走 8000，浏览器代码不直接持有后端地址。
        target: process.env.COPILOT_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        // 开发身份只由代理注入，避免浏览器代码伪造或切换研究员身份。
        // HTTP 头只能传 ASCII 账号和团队 ID，中文名称由展示层负责映射。
        headers: {
          'X-User-Id': 'analyst-mvp',
          'X-User-Teams': 'equity-research',
        },
      },
    },
  },
})
