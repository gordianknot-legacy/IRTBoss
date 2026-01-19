import { Routes, Route, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Upload from './pages/Upload'
import ModelComparison from './pages/ModelComparison'
import Diagnostics from './pages/Diagnostics'
import Export from './pages/Export'
import Layout from './components/Layout'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/projects/:projectId/upload" element={<Upload />} />
        <Route path="/projects/:projectId/results" element={<ModelComparison />} />
        <Route path="/projects/:projectId/diagnostics" element={<Diagnostics />} />
        <Route path="/projects/:projectId/export" element={<Export />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

export default App
