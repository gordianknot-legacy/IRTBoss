import { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ICCChart, TIFChart, generateICCData } from '../components/charts'
import { getDiagnostics, ApiError, type DiagnosticsResponse } from '../api'

export default function Diagnostics() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [selectedItem, setSelectedItem] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadDiagnostics()
  }, [projectId])

  const loadDiagnostics = async () => {
    if (!projectId) return

    try {
      setLoading(true)
      setError(null)
      const data = await getDiagnostics(projectId)
      setDiagnostics(data)
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 404) {
          setError('No diagnostics available. Please fit models first.')
        } else {
          setError(err.detail || err.message)
        }
      } else {
        setError('Failed to load diagnostics')
      }
    } finally {
      setLoading(false)
    }
  }

  // Generate ICC data for selected item
  const selectedItemData = useMemo(() => {
    if (!selectedItem || !diagnostics) return null
    const item = diagnostics.items.find((i) => i.item_id === selectedItem)
    if (!item) return null
    return {
      item,
      data: generateICCData(item.discrimination, item.difficulty, item.guessing),
    }
  }, [selectedItem, diagnostics])

  const getStatusStyle = (status: string) => {
    switch (status) {
      case 'good':
        return 'bg-green-100 text-green-800'
      case 'acceptable':
        return 'bg-blue-100 text-blue-800'
      case 'flagged':
        return 'bg-yellow-100 text-yellow-800'
      case 'problematic':
        return 'bg-red-100 text-red-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      good: 'Good',
      acceptable: 'Acceptable',
      flagged: 'Flagged',
      problematic: 'Problematic',
    }
    return labels[status] || status
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Diagnostics</h1>
        </div>
        <div className="card text-center py-12">
          <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
            {error}
          </div>
          <button
            onClick={() => navigate(`/projects/${projectId}/results`)}
            className="btn btn-primary"
          >
            Back to Results
          </button>
        </div>
      </div>
    )
  }

  if (!diagnostics) {
    return null
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
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="card">
          <div className="text-sm text-gray-500">Reliability</div>
          <div className="text-3xl font-bold mt-1">
            {diagnostics.reliability.toFixed(2)}
          </div>
          <div className={`text-sm mt-1 ${diagnostics.reliability >= 0.8 ? 'text-green-600' : 'text-red-600'}`}>
            {diagnostics.reliability >= 0.8 ? 'Acceptable' : 'Below threshold'}
          </div>
        </div>

        <div className="card">
          <div className="text-sm text-gray-500">Peak Information</div>
          <div className="text-3xl font-bold mt-1">
            {diagnostics.tif.peak_information.toFixed(1)}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            at theta = {diagnostics.tif.peak_theta.toFixed(1)}
          </div>
        </div>

        <div className="card">
          <div className="text-sm text-gray-500">Coverage Range</div>
          <div className="text-2xl font-bold mt-1">
            [{diagnostics.tif.coverage_low.toFixed(1)}, {diagnostics.tif.coverage_high.toFixed(1)}]
          </div>
          <div className="text-sm text-gray-500 mt-1">
            Adequate measurement
          </div>
        </div>

        <div className="card">
          <div className="text-sm text-gray-500">Items Flagged</div>
          <div className="text-3xl font-bold mt-1">
            {diagnostics.n_flagged}
          </div>
          <div className="text-sm text-gray-500 mt-1">
            of {diagnostics.items.length} items
          </div>
        </div>
      </div>

      {/* TIF Visualization */}
      <div className="card mb-6">
        <h2 className="card-header">Test Information Function</h2>
        <div className="flex justify-center">
          <TIFChart
            data={diagnostics.tif.data}
            peakTheta={diagnostics.tif.peak_theta}
            peakInformation={diagnostics.tif.peak_information}
            coverageLow={diagnostics.tif.coverage_low}
            coverageHigh={diagnostics.tif.coverage_high}
            width={700}
            height={350}
            showSE={true}
            reliabilityThreshold={0.8}
          />
        </div>
        <p className="text-sm text-gray-500 mt-4 text-center">
          The Test Information Function shows measurement precision across the ability range.
          Higher values indicate more precise measurement.
        </p>
      </div>

      {/* ICC for Selected Item */}
      {selectedItemData && (
        <div className="card mb-6">
          <div className="flex justify-between items-start mb-4">
            <h2 className="card-header">Item Characteristic Curve: {selectedItem}</h2>
            <button
              onClick={() => setSelectedItem(null)}
              className="text-gray-400 hover:text-gray-600"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="flex justify-center">
            <ICCChart
              data={selectedItemData.data}
              itemId={selectedItemData.item.item_id}
              difficulty={selectedItemData.item.difficulty}
              discrimination={selectedItemData.item.discrimination}
              guessing={selectedItemData.item.guessing}
              width={550}
              height={350}
              showInformation={true}
            />
          </div>
        </div>
      )}

      {/* Item Table */}
      <div className="card mb-6">
        <h2 className="card-header">Item Parameters</h2>
        <p className="text-sm text-gray-500 mb-4">
          Click on an item to view its characteristic curve
        </p>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-3 px-2 font-medium text-gray-700">Item</th>
                <th className="text-center py-3 px-2 font-medium text-gray-700">Status</th>
                <th className="text-right py-3 px-2 font-medium text-gray-700">Discrimination (a)</th>
                <th className="text-right py-3 px-2 font-medium text-gray-700">Difficulty (b)</th>
                <th className="text-right py-3 px-2 font-medium text-gray-700">Max Info</th>
                <th className="text-left py-3 px-2 font-medium text-gray-700">Flags</th>
              </tr>
            </thead>
            <tbody>
              {diagnostics.items.map((item) => (
                <tr
                  key={item.item_id}
                  className={`border-b border-gray-100 cursor-pointer transition-colors ${
                    selectedItem === item.item_id ? 'bg-blue-50' : 'hover:bg-gray-50'
                  }`}
                  onClick={() => setSelectedItem(item.item_id)}
                >
                  <td className="py-3 px-2 font-medium">{item.item_id}</td>
                  <td className="py-3 px-2 text-center">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusStyle(item.status)}`}>
                      {getStatusLabel(item.status)}
                    </span>
                  </td>
                  <td className="py-3 px-2 text-right font-mono">
                    <span className={item.discrimination < 0.5 ? 'text-red-600' : ''}>
                      {item.discrimination.toFixed(2)}
                    </span>
                  </td>
                  <td className="py-3 px-2 text-right font-mono">
                    <span className={Math.abs(item.difficulty) > 3 ? 'text-yellow-600' : ''}>
                      {item.difficulty.toFixed(2)}
                    </span>
                  </td>
                  <td className="py-3 px-2 text-right font-mono">{item.max_information.toFixed(2)}</td>
                  <td className="py-3 px-2">
                    {item.flags.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {item.flags.map((flag, idx) => (
                          <span key={idx} className="px-1.5 py-0.5 bg-yellow-100 text-yellow-800 text-xs rounded">
                            {flag}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Item Status Summary */}
      <div className="card mb-6">
        <h2 className="card-header">Status Summary</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {(['good', 'acceptable', 'flagged', 'problematic'] as const).map((status) => {
            const count = diagnostics.items.filter((i) => i.status === status).length
            return (
              <div key={status} className="flex items-center gap-3">
                <div className={`w-4 h-4 rounded ${getStatusStyle(status)}`}></div>
                <div>
                  <div className="font-medium capitalize">{status}</div>
                  <div className="text-sm text-gray-500">{count} items</div>
                </div>
              </div>
            )
          })}
        </div>
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
