import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Navbar from './components/Navbar'
import RequireAuth from './auth/RequireAuth'
import Home from './pages/Home'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ContainersPage = lazy(() => import('./pages/ContainersPage'))
const BuilderPage = lazy(() => import('./pages/BuilderPage'))
const ImagesPage = lazy(() => import('./pages/ImagesPage'))
const TeamsPage = lazy(() => import('./pages/TeamsPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const LogsPage = lazy(() => import('./pages/LogsPage'))
const AuditLogPage = lazy(() => import('./pages/AuditLogPage'))
const StacksPage = lazy(() => import('./pages/StacksPage'))
const StackBuilderPage = lazy(() => import('./pages/stacks/StackBuilderPage'))
/**
 * Defines the application's client-side routes and layout.
 *
 * Renders public routes for /login and /register, and nested routes within the main Layout: / (Home), and protected routes /dashboard, /containers, /builder, and /settings which are wrapped with RequireAuth.
 *
 * @returns The top-level routing JSX element that configures the application's routes.
 */
export default function App() {
  return (
    <Suspense
      fallback={
        <div className="app-shell">
          <Navbar />
          <main className="main-content" role="status" aria-live="polite">
            <span className="skeleton skeleton--detail-title" />
            <span className="skeleton skeleton--team-row" />
            <span className="skeleton skeleton--team-row" />
          </main>
        </div>
      }
    >
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <DashboardPage />
              </RequireAuth>
            }
          />
          <Route
            path="/containers"
            element={
              <RequireAuth>
                <ContainersPage />
              </RequireAuth>
            }
          />
          <Route
            path="/builder"
            element={
              <RequireAuth>
                <BuilderPage />
              </RequireAuth>
            }
          />
          <Route
            path="/images"
            element={
              <RequireAuth>
                <ImagesPage />
              </RequireAuth>
            }
          />
          <Route
            path="/teams/:projectId?"
            element={
              <RequireAuth>
                <TeamsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/settings"
            element={
              <RequireAuth>
                <SettingsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/logs"
            element={
              <RequireAuth>
                <LogsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/audit"
            element={
              <RequireAuth>
                <AuditLogPage />
              </RequireAuth>
            }
          />
          <Route
            path="/stacks"
            element={
              <RequireAuth>
                <StacksPage />
              </RequireAuth>
            }
          />
          <Route
            path="/stacks/new"
            element={
              <RequireAuth>
                <StackBuilderPage />
              </RequireAuth>
            }
          />
          <Route
            path="/stacks/:id"
            element={
              <RequireAuth>
                <StackBuilderPage />
              </RequireAuth>
            }
          />
        </Route>
      </Routes>
    </Suspense>
  )
}
