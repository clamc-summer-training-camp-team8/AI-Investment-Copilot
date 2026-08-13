import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  if (command === 'build' && env.VITE_DEMO_SCENARIO_MODE === 'controlled-mock') {
    throw new Error('正式构建禁止使用 controlled-mock，请设置 VITE_DEMO_SCENARIO_MODE=real。')
  }

  return {
    plugins: [react()],
    server: {
      port: 5174,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          headers: {
            'X-User-Id': 'demo_owner',
            'X-User-Teams': 'research-demo',
          },
        },
      },
    },
  }
})
