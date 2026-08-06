import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import './index.css'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // A 401 is an answer, not a transient failure; retrying it just delays
      // the redirect to the login screen.
      retry: 1,
      staleTime: 15_000,
    },
  },
})

const container = document.getElementById('root')
if (container == null) throw new Error('#root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
