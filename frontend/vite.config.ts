import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],

  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },

  server: {
    port: 5173,

    // 关键修复：允许 ai.roguelife.de 访问开发服务器
    allowedHosts: [
      'ai.roguelife.de',
      // 如果你有其他子域名或需要支持所有 roguelife.de 子域名，可以这样写（推荐）：
      // '.roguelife.de'
    ],

    // 建议同时开启，让开发服务器监听所有网络接口（局域网、服务器、域名解析等都能访问）
    host: true,        // 等同于 '0.0.0.0'

    proxy: {
      '/api': {
        target: 'http://localhost:8881',
        changeOrigin: true
      }
    }
  },

  // 如果你以后会使用 vite preview 命令，也建议加上 preview 配置
  preview: {
    allowedHosts: [
      'ai.roguelife.de',
      // '.roguelife.de'
    ]
  }
})