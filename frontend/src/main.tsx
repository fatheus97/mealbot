import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { syncDocumentLang } from './i18n/documentLang'

// app.html ships `<html lang="en">`; keep the attribute honest once a locale is
// chosen. Not cosmetic — a screen reader picks its pronunciation rules from it,
// so Czech text under lang="en" is read out with English phonetics. Wired here
// rather than in a component because it is app bootstrap, not rendering.
syncDocumentLang()

// Define a stable client with pragmatic cache boundaries
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1, // Only retry once to avoid hiding systemic backend failures
      refetchOnWindowFocus: false, // Prevents aggressive polling
      staleTime: 1000 * 60 * 5, // Data remains fresh for 5 minutes
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)