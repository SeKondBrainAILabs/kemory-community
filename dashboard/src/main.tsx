import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { loadConfig } from '@/lib/runtimeConfig'
import { AdvancedViewProvider } from '@/contexts/AdvancedViewContext'
import { App } from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

async function bootstrap() {
  await loadConfig()
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AdvancedViewProvider>
            <App />
          </AdvancedViewProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}

void bootstrap()
