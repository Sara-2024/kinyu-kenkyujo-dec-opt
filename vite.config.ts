import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { handleMarket } from './api/_lib/market'
import { handleCalendar } from './api/_lib/calendar'
import { bearerOf, envFrom, handleChat, readJson } from './api/_lib/chat'
import { handleRisk, riskEnvFrom, type RiskRequest } from './api/_lib/risk'

/** 開発中も /api/* が本番（Vercel の api/*.ts）と同じように応える */
function localApi(env: Record<string, string>): Plugin {
  return {
    name: 'local-api',
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
      server.middlewares.use('/api/calendar', (_req, res) => {
        void handleCalendar().then(({ status, body }) => {
          res.statusCode = status
          res.setHeader('content-type', 'application/json; charset=utf-8')
          res.setHeader('cache-control', 'no-store')
          res.end(JSON.stringify(body))
        })
      })
      server.middlewares.use('/api/chat', (req, res) => {
        void (async () => {
          const body = req.method === 'POST' ? await readJson(req) : {}
          const { status, body: out } = await handleChat(body, bearerOf(req.headers.authorization), envFrom({ ...env, ...process.env }))
          res.statusCode = status
          res.setHeader('content-type', 'application/json; charset=utf-8')
          res.setHeader('cache-control', 'no-store')
          res.end(JSON.stringify(out))
        })()
      })
      // AIリスク監督。ブリッジ（お客様のPC）だけが呼ぶ
      server.middlewares.use('/api/risk', (req, res) => {
        void (async () => {
          const body = req.method === 'POST' ? ((await readJson(req)) as unknown as RiskRequest) : null
          const token = String(req.headers['x-trelab-bridge'] ?? '')
          const { status, body: out } = await handleRisk(body, riskEnvFrom({ ...env, ...process.env }), token)
          res.statusCode = status
          res.setHeader('content-type', 'application/json; charset=utf-8')
          res.setHeader('cache-control', 'no-store')
          res.end(JSON.stringify(out))
        })()
      })
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), localApi(loadEnv(mode, process.cwd(), ''))],
  server: { port: Number(process.env.PORT) || 5181 },
}))
