import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './auth/RequireAuth'
import Home from './pages/Home'
import ContainersPage from './pages/ContainersPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import ImagesPage from './pages/ImagesPage'
import PlaceholderPage from './pages/PlaceholderPage'
import SettingsPage from './pages/SettingsPage'
import TeamsPage from './pages/TeamsPage'

/**
 * Defines the application's client-side routes and layout.
 *
 * Renders public routes for /login and /register, and nested routes within the main Layout: / (Home), and protected routes /dashboard, /containers, /builder, and /settings which are wrapped with RequireAuth.
 *
 * @returns The top-level routing JSX element that configures the application's routes.
 */
export default function App() {
  return (
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
      </Route>
    </Routes>
  )
}
