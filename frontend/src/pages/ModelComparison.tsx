import { useParams, useNavigate } from 'react-router-dom'

export default function ModelComparison() {
  const { projectId } = useParams()
  const navigate = useNavigate()

  // Placeholder data - would come from API
  const comparison = {
    recommendedModel: '2PL',
    reasons: [
      '2PL model selected: has lowest AIC and BIC, indicating best balance of fit and complexity.',
      'Sample size (500) is adequate for stable 2PL estimation.',
    ],
    models: [
      { type: '1PL', aic: 12500, bic: 12600, converged: true },
      { type: '2PL', aic: 12200, bic: 12400, converged: true },
    ],
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Model Comparison</h1>
        <p className="text-gray-600 mt-1">
          Review fitted models and our recommendation
        </p>
      </div>

      {/* Recommendation Card */}
      <div className="card mb-6 border-l-4 border-l-blue-500">
        <div className="flex items-start">
          <div className="flex-shrink-0">
            <svg className="h-6 w-6 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="ml-4">
            <h2 className="text-lg font-semibold text-gray-900">
              Recommended Model: {comparison.recommendedModel}
            </h2>
            <div className="mt-2 space-y-1">
              {comparison.reasons.map((reason, idx) => (
                <p key={idx} className="text-gray-600">{reason}</p>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Comparison Table */}
      <div className="card mb-6">
        <h2 className="card-header">Model Comparison</h2>
        <table className="min-w-full">
          <thead>
            <tr className="border-b">
              <th className="text-left py-2 font-medium text-gray-700">Model</th>
              <th className="text-right py-2 font-medium text-gray-700">AIC</th>
              <th className="text-right py-2 font-medium text-gray-700">BIC</th>
              <th className="text-center py-2 font-medium text-gray-700">Converged</th>
            </tr>
          </thead>
          <tbody>
            {comparison.models.map((model) => (
              <tr
                key={model.type}
                className={model.type === comparison.recommendedModel ? 'bg-blue-50' : ''}
              >
                <td className="py-3">
                  <span className="font-medium">{model.type}</span>
                  {model.type === comparison.recommendedModel && (
                    <span className="ml-2 text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded-full">
                      Recommended
                    </span>
                  )}
                </td>
                <td className="text-right py-3 font-mono">{model.aic.toFixed(0)}</td>
                <td className="text-right py-3 font-mono">{model.bic.toFixed(0)}</td>
                <td className="text-center py-3">
                  {model.converged ? (
                    <span className="text-green-600">Yes</span>
                  ) : (
                    <span className="text-red-600">No</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* What This Means */}
      <div className="card mb-6">
        <h2 className="card-header">Understanding the 2PL Model</h2>
        <p className="text-gray-600">
          The 2PL model allows items to differ in both difficulty AND discrimination
          (how well they distinguish between ability levels). This is more realistic
          for most assessments, as some items are simply better at measuring the trait
          than others. However, it requires more data to estimate reliably and produces
          somewhat less interpretable results.
        </p>
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
