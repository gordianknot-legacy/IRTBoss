import { useParams, useNavigate } from 'react-router-dom'

export default function Diagnostics() {
  const { projectId } = useParams()
  const navigate = useNavigate()

  // Placeholder data
  const diagnostics = {
    reliability: 0.85,
    peakTheta: 0.2,
    peakInfo: 12.5,
    coverageLow: -2.1,
    coverageHigh: 2.3,
    items: [
      { id: 'item_01', status: 'good', discrimination: 1.2, difficulty: -0.5 },
      { id: 'item_02', status: 'good', discrimination: 0.9, difficulty: 0.3 },
      { id: 'item_03', status: 'flagged', discrimination: 0.3, difficulty: 1.2 },
      { id: 'item_04', status: 'good', discrimination: 1.5, difficulty: -1.0 },
      { id: 'item_05', status: 'good', discrimination: 1.1, difficulty: 0.0 },
    ],
  }

  const getStatusStyle = (status: string) => {
    switch (status) {
      case 'good':
        return 'bg-green-100 text-green-800'
      case 'flagged':
        return 'bg-yellow-100 text-yellow-800'
      case 'problematic':
        return 'bg-red-100 text-red-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Diagnostics</h1>
        <p className="text-gray-600 mt-1">
          Review test and item-level diagnostic information
        </p>
      </div>

      {/* Test-Level Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <div className="card">
          <div className="text-sm text-gray-500">Reliability</div>
          <div className="text-3xl font-bold mt-1">
            {diagnostics.reliability.toFixed(2)}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            {diagnostics.reliability >= 0.8 ? 'Acceptable' : 'Below threshold'}
          </div>
        </div>

        <div className="card">
          <div className="text-sm text-gray-500">Peak Information</div>
          <div className="text-3xl font-bold mt-1">
            {diagnostics.peakInfo.toFixed(1)}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            at θ = {diagnostics.peakTheta.toFixed(1)}
          </div>
        </div>

        <div className="card">
          <div className="text-sm text-gray-500">Adequate Coverage</div>
          <div className="text-3xl font-bold mt-1">
            θ ∈ [{diagnostics.coverageLow.toFixed(1)}, {diagnostics.coverageHigh.toFixed(1)}]
          </div>
          <div className="text-sm text-gray-500 mt-1">
            Range with information ≥ 1.0
          </div>
        </div>
      </div>

      {/* TIF Visualization Placeholder */}
      <div className="card mb-6">
        <h2 className="card-header">Test Information Function</h2>
        <div className="h-64 bg-gray-100 rounded flex items-center justify-center">
          <p className="text-gray-500">
            TIF visualization will be rendered here using D3.js
          </p>
        </div>
      </div>

      {/* Item Table */}
      <div className="card mb-6">
        <h2 className="card-header">Item Parameters</h2>
        <table className="min-w-full">
          <thead>
            <tr className="border-b">
              <th className="text-left py-2 font-medium text-gray-700">Item</th>
              <th className="text-center py-2 font-medium text-gray-700">Status</th>
              <th className="text-right py-2 font-medium text-gray-700">Discrimination (a)</th>
              <th className="text-right py-2 font-medium text-gray-700">Difficulty (b)</th>
            </tr>
          </thead>
          <tbody>
            {diagnostics.items.map((item) => (
              <tr key={item.id} className="border-b border-gray-100">
                <td className="py-3 font-medium">{item.id}</td>
                <td className="py-3 text-center">
                  <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusStyle(item.status)}`}>
                    {item.status}
                  </span>
                </td>
                <td className="py-3 text-right font-mono">{item.discrimination.toFixed(2)}</td>
                <td className="py-3 text-right font-mono">{item.difficulty.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Actions */}
      <div className="flex justify-between">
        <button
          onClick={() => navigate(`/projects/${projectId}/results`)}
          className="btn btn-secondary"
        >
          Back to Results
        </button>
        <button
          onClick={() => navigate(`/projects/${projectId}/export`)}
          className="btn btn-primary"
        >
          Export Report
        </button>
      </div>
    </div>
  )
}
