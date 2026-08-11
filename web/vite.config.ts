import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
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
