import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  listProjects,
  createProject,
  ApiError,
  type ProjectResponse,
  type StakesLevel,
  type IntendedUse,
} from '../api'



export default function Dashboard() {
  const navigate = useNavigate()
  const [showNewProject, setShowNewProject] = useState(false)
  const [projects, setProjects] = useState<ProjectResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // New project form state
  const [newProjectName, setNewProjectName] = useState('')
  const [newProjectDescription, setNewProjectDescription] = useState('')
  const [newProjectStakes, setNewProjectStakes] = useState<StakesLevel>('medium')
  const [newProjectUse, setNewProjectUse] = useState<IntendedUse>('operational')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    loadProjects()
  }, [])

  const loadProjects = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await listProjects()
      setProjects(data)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Failed to load projects: ${err.detail || err.message}`)
      } else {
        setError('Failed to load projects')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleCreateProject = async () => {
    if (!newProjectName.trim()) return

    try {
      setCreating(true)
      const project = await createProject({
        name: newProjectName.trim(),
        description: newProjectDescription.trim() || undefined,
        stakes_level: newProjectStakes,
        intended_use: newProjectUse,
      })
      setProjects([project, ...projects])
      setShowNewProject(false)
      resetForm()
      // Navigate to upload page
      navigate(`/projects/${project.id}/upload`)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Failed to create project: ${err.detail || err.message}`)
      } else {
        setError('Failed to create project')
      }
    } finally {
      setCreating(false)
    }
  }

  const resetForm = () => {
    setNewProjectName('')
    setNewProjectDescription('')
    setNewProjectStakes('medium')
    setNewProjectUse('operational')
  }

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      created: 'bg-gray-100 text-gray-800',
      data_uploaded: 'bg-blue-100 text-blue-800',
      fitting: 'bg-yellow-100 text-yellow-800',
      completed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
    }
    const labels: Record<string, string> = {
      created: 'Created',
      data_uploaded: 'Data Uploaded',
      fitting: 'Fitting Models...',
      completed: 'Completed',
      failed: 'Failed',
    }
    return (
      <span className={`px-2 py-1 rounded-full text-xs font-medium ${styles[status] || styles.created}`}>
        {labels[status] || status}
      </span>
    )
  }

  const getNextAction = (project: ProjectResponse) => {
    switch (project.status) {
      case 'created':
        return { label: 'Upload Data', path: `/projects/${project.id}/upload` }
      case 'data_uploaded':
        return { label: 'Fit Models', path: `/projects/${project.id}/results` }
      case 'fitting':
        return { label: 'View Progress', path: `/projects/${project.id}/results` }
      case 'completed':
        return { label: 'View Results', path: `/projects/${project.id}/results` }
      default:
        return { label: 'View', path: `/projects/${project.id}/results` }
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Projects</h1>
          <p className="text-gray-600 mt-1">
            Manage your IRT assessment projects
          </p>
        </div>
        <button
          onClick={() => setShowNewProject(true)}
          className="btn btn-primary"
        >
          New Project
        </button>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-4 text-red-600 hover:text-red-800"
          >
            Dismiss
          </button>
        </div>
      )}

      {projects.length === 0 ? (
        <div className="card text-center py-12">
          <svg
            className="mx-auto h-12 w-12 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">No projects yet</h3>
          <p className="mt-2 text-gray-600">
            Create your first project to get started with IRT analysis.
          </p>
          <button
            onClick={() => setShowNewProject(true)}
            className="btn btn-primary mt-4"
          >
            Create Project
          </button>
        </div>
      ) : (
        <div className="bg-white shadow-sm rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Project
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Stakes Level
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Created
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {projects.map((project) => {
                const action = getNextAction(project)
                return (
                  <tr key={project.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="font-medium text-gray-900">{project.name}</div>
                      {project.description && (
                        <div className="text-sm text-gray-500">{project.description}</div>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {getStatusBadge(project.status)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-600 capitalize">
                      {project.stakes_level}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-600">
                      {new Date(project.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <button
                        onClick={() => navigate(action.path)}
                        className="text-blue-600 hover:text-blue-800 font-medium"
                      >
                        {action.label}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* New Project Modal */}
      {showNewProject && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg max-w-lg w-full p-6">
            <h2 className="text-lg font-semibold mb-4">Create New Project</h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Project Name *
                </label>
                <input
                  type="text"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  placeholder="e.g., Math Assessment 2024"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description
                </label>
                <textarea
                  value={newProjectDescription}
                  onChange={(e) => setNewProjectDescription(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  rows={2}
                  placeholder="Optional description of the assessment"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Stakes Level
                </label>
                <select
                  value={newProjectStakes}
                  onChange={(e) => setNewProjectStakes(e.target.value as StakesLevel)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="low">Low - Classroom quizzes, practice tests</option>
                  <option value="medium">Medium - Course grades, placement tests</option>
                  <option value="high">High - Certification, licensure</option>
                </select>
                <p className="text-sm text-gray-500 mt-1">
                  Higher stakes require more stringent validation thresholds.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Intended Use
                </label>
                <select
                  value={newProjectUse}
                  onChange={(e) => setNewProjectUse(e.target.value as IntendedUse)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="research">Research - Exploratory analysis</option>
                  <option value="operational">Operational - Regular production use</option>
                  <option value="certification">Certification - High-stakes decisions</option>
                </select>
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setShowNewProject(false)
                  resetForm()
                }}
                className="btn btn-secondary"
                disabled={creating}
              >
                Cancel
              </button>
              <button
                onClick={handleCreateProject}
                className="btn btn-primary"
                disabled={!newProjectName.trim() || creating}
              >
                {creating ? 'Creating...' : 'Create Project'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
