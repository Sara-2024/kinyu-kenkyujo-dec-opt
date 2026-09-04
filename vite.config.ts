import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { handleMarket } from './api/_lib/market'

/** 開発中も /api/market が本番（Vercel の api/market.ts）と同じように応える */
function marketApi(): Plugin {
  return {
    name: 'market-api',
    configureServer(server) {
      server.middlewares.use('/api/market', (req, res) => {
        const url = new URL(req.originalUrl ?? req.url ?? '/', 'http://localhost')
        void handleMarket(url).then(({ status, body }) => {
          res.statusCode = status
          res.setHeader('content-type', 'application/json; charset=utf-8')
          res.setHeader('cache-control', 'no-store')
          res.end(JSON.stringify(body))
        })
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), marketApi()],
  server: { port: Number(process.env.PORT) || 5181 },
})
