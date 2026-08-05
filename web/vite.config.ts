import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // shadcn/ui 관례(@/...) — 기존 상대 경로 import와 공존한다
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
})
