import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import PlaceholderPage from './pages/PlaceholderPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route
          path="/dashboard"
          element={<PlaceholderPage title="Dashboard" />}
        />
        <Route
          path="/containers"
          element={<PlaceholderPage title="Containers" />}
        />
        <Route
          path="/builder"
          element={<PlaceholderPage title="Builder" />}
        />
        <Route path="/images" element={<PlaceholderPage title="Images" />} />
        <Route
          path="/settings"
          element={<PlaceholderPage title="Settings" />}
        />
      </Route>
    </Routes>
  )
}
