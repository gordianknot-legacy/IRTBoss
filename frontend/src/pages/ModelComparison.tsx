import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getResults,
  startFitting,
  getJobProgress,
  ApiError,
  type ModelResultResponse,
  type FittingProgress,
} from '../api'

export default function ModelComparison() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const [results, setResults] = useState<ModelResultResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fitting, setFitting] = useState(false)
  const [fittingProgress, setFittingProgress] = useState<FittingProgress | null>(null)

  useEffect(() => {
    loadResults()
  }, [projectId])

  const loadResults = async () => {
    if (!projectId) return

    try {
      setLoading(true)
      setError(null)
      const data = await getResults(projectId)
      setResults(data)
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 404) {
          // No results yet - show fitting UI
          setResults(null)
        } else {
          setError(err.detail || err.message)
        }
      } else {
        setError('Failed to load results')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleStartFitting = async () => {
    if (!projectId) return

    try {
      setFitting(true)
      setError(null)

      const job = await startFitting({
        project_id: projectId,
        fit_1pl: true,
        fit_2pl: true,
        fit_3pl: false,
      })

      // Poll for progress
      const pollInterval = setInterval(async () => {
        try {
          const progress = await getJobProgress(job.job_id)
          setFittingProgress(progress)

          if (progress.status === 'completed') {
            clearInterval(pollInterval)
            setFitting(false)
            loadResults()
          } else if (progress.status === 'failed') {
            clearInterval(pollInterval)
            setFitting(false)
            setError('Model fitting failed. Please try again.')
          }
        } catch (err) {
          clearInterval(pollInterval)
          setFitting(false)
          setError('Error checking fitting progress')
        }
      }, 2000)
    } catch (err) {
      setFitting(false)
      if (err instanceof ApiError) {
        setError(err.detail || err.message)
      } else {
        setError('Failed to start model fitting')
      }
    }
  }

  const getModelDescription = (modelType: string) => {
    switch (modelType) {
      case '1PL':
        return {
          title: 'Rasch (1PL) Model',
          description:
            'The 1PL model assumes all items have equal discrimination. This simpler model is easier to interpret and requires less data, but may not fit well if items truly differ in quality.',
        }
      case '2PL':
        return {
          title: '2-Parameter Logistic (2PL) Model',
          description:
            'The 2PL model allows items to differ in both difficulty AND discrimination (how well they distinguish between ability levels). This is more realistic for most assessments.',
        }
      case '3PL':
        return {
          title: '3-Parameter Logistic (3PL) Model',
          description:
            'The 3PL model adds a guessing parameter, useful for multiple-choice tests where examinees can guess correctly even when they do not know the answer.',
        }
      default:
        return { title: modelType, description: '' }
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  // Show fitting UI if no results yet
  if (!results) {
    return (
      <div>
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Model Fitting</h1>
          <p className="text-gray-600 mt-1">
            Fit IRT models to your response data
          </p>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
            {error}
          </div>
        )}

        {fitting ? (
          <div className="card text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
            <h3 className="mt-4 text-lg font-medium text-gray-900">
              Fitting Models...
            </h3>
            {fittingProgress && (
              <>
                <p className="mt-2 text-gray-600">
                  {fittingProgress.current_model
                    ? `Currently fitting: ${fittingProgress.current_model}`
                    : 'Initializing...'}
                </p>
                <div className="mt-4 w-64 mx-auto bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${fittingProgress.progress * 100}%` }}
                  ></div>
                </div>
                <p className="mt-2 text-sm text-gray-500">
                  {Math.round(fittingProgress.progress * 100)}% complete
                </p>
              </>
            )}
          </div>
        ) : (
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
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
              />
            </svg>
            <h3 className="mt-4 text-lg font-medium text-gray-900">
              Ready to Fit Models
            </h3>
            <p className="mt-2 text-gray-600 max-w-md mx-auto">
              Your data has been validated. Click below to fit 1PL and 2PL IRT
              models and get a recommendation.
            </p>
            <button
              onClick={handleStartFitting}
              className="btn btn-primary mt-6"
            >
              Start Model Fitting
            </button>
          </div>
        )}

        <div className="flex justify-between mt-6">
          <button
            onClick={() => navigate(`/projects/${projectId}/upload`)}
            className="btn btn-secondary"
          >
            Back to Upload
          </button>
        </div>
      </div>
    )
  }

  // Show results
  const modelInfo = getModelDescription(results.comparison.recommended_model)

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Model Comparison</h1>
        <p className="text-gray-600 mt-1">
          Review fitted models and our recommendation
        </p>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
          {error}
        </div>
      )}

      {/* Recommendation Card */}
      <div className="card mb-6 border-l-4 border-l-blue-500">
        <div className="flex items-start">
          <div className="flex-shrink-0">
            <svg
              className="h-6 w-6 text-blue-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <div className="ml-4">
            <h2 className="text-lg font-semibold text-gray-900">
              Recommended Model: {results.comparison.recommended_model}
            </h2>
            <div className="mt-2 space-y-1">
              {results.comparison.selection_reasons.map((reason, idx) => (
                <p key={idx} className="text-gray-600">
                  {reason}
                </p>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="card">
          <div className="text-sm text-gray-500">Reliability</div>
          <div className="text-3xl font-bold mt-1">
            {results.reliability_estimate.toFixed(2)}
          </div>
          <div
            className={`text-sm mt-1 ${
              results.reliability_estimate >= 0.8
                ? 'text-green-600'
                : 'text-yellow-600'
            }`}
          >
            {results.reliability_estimate >= 0.8 ? 'Acceptable' : 'Review recommended'}
          </div>
        </div>

        <div className="card">
          <div className="text-sm text-gray-500">Items</div>
          <div className="text-3xl font-bold mt-1">
            {results.item_parameters.length}
          </div>
          <div className="text-sm text-gray-500 mt-1">in analysis</div>
        </div>

        <div className="card">
          <div className="text-sm text-gray-500">Model Type</div>
          <div className="text-3xl font-bold mt-1">
            {results.selected_model.model_type}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            {results.selected_model.fit_stats.converged
              ? 'Converged'
              : 'Did not converge'}
          </div>
        </div>
      </div>

      {/* Comparison Table */}
      <div className="card mb-6">
        <h2 className="card-header">Model Comparison</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr className="border-b">
                <th className="text-left py-2 font-medium text-gray-700">Model</th>
                <th className="text-right py-2 font-medium text-gray-700">
                  Log-Likelihood
                </th>
                <th className="text-right py-2 font-medium text-gray-700">AIC</th>
                <th className="text-right py-2 font-medium text-gray-700">BIC</th>
                <th className="text-right py-2 font-medium text-gray-700">
                  Parameters
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(results.comparison.comparison_table).map(
                ([modelType, stats]) => (
                  <tr
                    key={modelType}
                    className={
                      modelType === results.comparison.recommended_model
                        ? 'bg-blue-50'
                        : ''
                    }
                  >
                    <td className="py-3">
                      <span className="font-medium">{modelType}</span>
                      {modelType === results.comparison.recommended_model && (
                        <span className="ml-2 text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded-full">
                          Recommended
                        </span>
                      )}
                    </td>
                    <td className="text-right py-3 font-mono">
                      {stats.log_likelihood.toFixed(1)}
                    </td>
                    <td className="text-right py-3 font-mono">
                      {stats.aic.toFixed(1)}
                    </td>
                    <td className="text-right py-3 font-mono">
                      {stats.bic.toFixed(1)}
                    </td>
                    <td className="text-right py-3">{stats.n_parameters}</td>
                  </tr>
                )
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* What This Means */}
      <div className="card mb-6">
        <h2 className="card-header">Understanding the {modelInfo.title}</h2>
        <p className="text-gray-600">{modelInfo.description}</p>
      </div>

      {/* Item Parameters Preview */}
      <div className="card mb-6">
        <h2 className="card-header">Item Parameters Preview</h2>
        <p className="text-sm text-gray-500 mb-4">
          Showing first 10 items. View full details in Diagnostics.
        </p>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr className="border-b">
                <th className="text-left py-2 font-medium text-gray-700">Item</th>
                <th className="text-right py-2 font-medium text-gray-700">
                  Discrimination (a)
                </th>
                <th className="text-right py-2 font-medium text-gray-700">
                  Difficulty (b)
                </th>
              </tr>
            </thead>
            <tbody>
              {results.item_parameters.slice(0, 10).map((item) => (
                <tr key={item.item_id} className="border-b border-gray-100">
                  <td className="py-3 font-medium">{item.item_id}</td>
                  <td className="text-right py-3 font-mono">
                    {item.discrimination.toFixed(2)}
                  </td>
                  <td className="text-right py-3 font-mono">
                    {item.difficulty.toFixed(2)}
                  </td>
                </tr>
              ))}
              {results.item_parameters.length > 10 && (
                <tr>
                  <td
                    colSpan={3}
                    className="py-3 text-center text-sm text-gray-500"
                  >
                    ... and {results.item_parameters.length - 10} more items
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Actions */}
      <div className="flex justify-between">
        <button
          onClick={() => navigate(`/projects/${projectId}/upload`)}
          className="btn btn-secondary"
        >
          Back to Upload
        </button>
        <button
          onClick={() => navigate(`/projects/${projectId}/diagnostics`)}
          className="btn btn-primary"
        >
          View Diagnostics
        </button>
      </div>
    </div>
  )
}
