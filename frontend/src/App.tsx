import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '@/components/Layout'
import { RequireAuth } from '@/components/RequireAuth'
import { AuthPage } from '@/pages/AuthPage'
import { ProjectsPage } from '@/pages/ProjectsPage'
import { ProjectPage } from '@/pages/ProjectPage'
import { DatasetPage } from '@/pages/DatasetPage'
import { RunPage } from '@/pages/RunPage'

export default function App() {
  return (
    <Routes>
      <Route path="/sign-in" element={<AuthPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:projectId" element={<ProjectPage />} />
        <Route path="/datasets/:datasetId" element={<DatasetPage />} />
        <Route path="/analyses/:runId" element={<RunPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}
