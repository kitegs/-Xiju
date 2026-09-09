import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return ({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('vue-echarts')) return 'echarts-vue'
          if (id.includes('echarts/charts')) return 'echarts-charts'
          if (id.includes('echarts/components')) return 'echarts-components'
          if (id.includes('echarts/core') || id.includes('echarts/renderers') || id.includes('zrender')) return 'echarts-core'
          return undefined
        },
      },
    },
  },
  server: {
    port: 5174,
    proxy: { '/api': env.VITE_API_TARGET || 'http://127.0.0.1:8010' }
  }
  })
})
