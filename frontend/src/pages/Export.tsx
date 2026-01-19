import { useState } from 'react'
import { useParams } from 'react-router-dom'

type ReportFormat = 'pdf' | 'html' | 'json'

export default function Export() {
  const { projectId } = useParams()
  const [selectedFormat, setSelectedFormat] = useState<ReportFormat>('pdf')
  const [includeAppendix, setIncludeAppendix] = useState(true)
  const [includeItemDetails, setIncludeItemDetails] = useState(true)
  const [generating, setGenerating] = useState(false)

  const formats = [
    {
      id: 'pdf' as ReportFormat,
      name: 'PDF',
      description: 'Best for sharing with stakeholders',
    },
    {
      id: 'html' as ReportFormat,
      name: 'HTML',
      description: 'Interactive report for web viewing',
    },
    {
      id: 'json' as ReportFormat,
      name: 'JSON',
      description: 'Machine-readable for integration',
    },
  ]

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      // Would call API here
      await new Promise(resolve => setTimeout(resolve, 2000))
      alert('Report generation is not yet implemented')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Export Report</h1>
        <p className="text-gray-600 mt-1">
          Generate an exportable report of your analysis
        </p>
      </div>

      {/* Format Selection */}
      <div className="card mb-6">
        <h2 className="card-header">Select Format</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {formats.map((format) => (
            <button
              key={format.id}
              onClick={() => setSelectedFormat(format.id)}
              className={`p-4 rounded-lg border-2 text-left transition-colors ${
                selectedFormat === format.id
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium">{format.name}</div>
              <div className="text-sm text-gray-500 mt-1">{format.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Options */}
      <div className="card mb-6">
        <h2 className="card-header">Report Options</h2>
        <div className="space-y-4">
          <label className="flex items-center">
            <input
              type="checkbox"
              checked={includeAppendix}
              onChange={(e) => setIncludeAppendix(e.target.checked)}
              className="h-4 w-4 text-blue-600 rounded border-gray-300"
            />
            <span className="ml-3">
              <span className="font-medium">Include Technical Appendix</span>
              <span className="block text-sm text-gray-500">
                Detailed statistical methods and model specifications
              </span>
            </span>
          </label>

          <label className="flex items-center">
            <input
              type="checkbox"
              checked={includeItemDetails}
              onChange={(e) => setIncludeItemDetails(e.target.checked)}
              className="h-4 w-4 text-blue-600 rounded border-gray-300"
            />
            <span className="ml-3">
              <span className="font-medium">Include Item Details</span>
              <span className="block text-sm text-gray-500">
                Full parameter tables and ICCs for each item
              </span>
            </span>
          </label>
        </div>
      </div>

      {/* Report Contents Preview */}
      <div className="card mb-6">
        <h2 className="card-header">Report Will Include</h2>
        <ul className="space-y-2 text-gray-600">
          <li className="flex items-center">
            <svg className="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Executive Summary
          </li>
          <li className="flex items-center">
            <svg className="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Model Selection Justification
          </li>
          <li className="flex items-center">
            <svg className="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Test Information Function
          </li>
          <li className="flex items-center">
            <svg className="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Reliability Estimate
          </li>
          <li className="flex items-center">
            <svg className="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Actionable Recommendations
          </li>
          <li className="flex items-center">
            <svg className="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Reproducibility Metadata
          </li>
          {includeAppendix && (
            <li className="flex items-center">
              <svg className="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              Technical Appendix
            </li>
          )}
          {includeItemDetails && (
            <li className="flex items-center">
              <svg className="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              Item-Level Details
            </li>
          )}
        </ul>
      </div>

      {/* Generate Button */}
      <div className="flex justify-end">
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="btn btn-primary"
        >
          {generating ? 'Generating...' : `Generate ${selectedFormat.toUpperCase()} Report`}
        </button>
      </div>
    </div>
  )
}
