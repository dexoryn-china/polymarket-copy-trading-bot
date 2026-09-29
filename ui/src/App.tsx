import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { shouldRetry } from './api/queries'
import { Layout } from './components/Layout'
import { EmptyState } from './components/ui/EmptyState'
import { ToastProvider } from './components/ui/Toast'
import { ActivityPage } from './pages/ActivityPage'
import { OverviewPage } from './pages/OverviewPage'
import { PositionsPage } from './pages/PositionsPage'
import { SettingsPage } from './pages/SettingsPage'
import { TargetsPage } from './pages/TargetsPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetry,
      staleTime: 5_000,
      refetchOnWindowFocus: true,
    },
    mutations: { retry: false },
  },
})

function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      description="The page you're looking for doesn't exist."
      action={
        <Link to="/" className="text-sm font-medium text-indigo-300 hover:text-indigo-200">
          Back to overview
        </Link>
      }
    />
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<OverviewPage />} />
              <Route path="targets" element={<TargetsPage />} />
              <Route path="positions" element={<PositionsPage />} />
              <Route path="activity" element={<ActivityPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}
