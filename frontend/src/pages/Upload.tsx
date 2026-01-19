import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'

interface ValidationMessage {
  severity: 'info' | 'warning' | 'error'
  code: string
  message: string
  details?: string
}

interface DataSummary {
  n_respondents: number
  n_items: number
  response_type: string
  missing_percentage: number
}

export default function Upload() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [summary, setSummary] = useState<DataSummary | null>(null)
  const [messages, setMessages] = useState<ValidationMessage[]>([])
  const [dragActive, setDragActive] = useState(false)

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0])
    }
  }, [])

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0])
    }
  }

  const handleUpload = async () => {
    if (!file) return

    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`/api/v1/projects/${projectId}/upload`, {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()
      setSummary(data.summary)
      setMessages(data.messages)
    } catch (error) {
      setMessages([{
        severity: 'error',
        code: 'UPLOAD_FAILED',
        message: 'Failed to upload file',
        details: error instanceof Error ? error.message : 'Unknown error',
      }])
    } finally {
      setUploading(false)
    }
  }

  const getMessageStyle = (severity: string) => {
    switch (severity) {
      case 'error':
        return 'bg-red-50 border-red-200 text-red-800'
      case 'warning':
        return 'bg-yellow-50 border-yellow-200 text-yellow-800'
      default:
        return 'bg-blue-50 border-blue-200 text-blue-800'
    }
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Upload Response Data</h1>
        <p className="text-gray-600 mt-1">
          Upload a CSV file containing your response data
        </p>
      </div>

      {/* Upload area */}
      <div className="card mb-6">
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            dragActive
              ? 'border-blue-500 bg-blue-50'
              : 'border-gray-300 hover:border-gray-400'
          }`}
        >
          <svg
            className="mx-auto h-12 w-12 text-gray-400"
            stroke="currentColor"
            fill="none"
            viewBox="0 0 48 48"
          >
            <path
              d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8m-12 4h.02"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="mt-4">
            <label className="cursor-pointer">
              <span className="text-blue-600 hover:text-blue-700 font-medium">
                Upload a file
              </span>
              <input
                type="file"
                accept=".csv"
                onChange={handleFileSelect}
                className="hidden"
              />
            </label>
            <span className="text-gray-600"> or drag and drop</span>
          </div>
          <p className="text-sm text-gray-500 mt-2">CSV files only</p>
          {file && (
            <p className="text-sm text-gray-700 mt-4">
              Selected: <span className="font-medium">{file.name}</span>
            </p>
          )}
        </div>

        {file && (
          <div className="mt-4 flex justify-end">
            <button
              onClick={handleUpload}
              disabled={uploading}
              className="btn btn-primary"
            >
              {uploading ? 'Uploading...' : 'Upload & Validate'}
            </button>
          </div>
        )}
      </div>

      {/* Validation messages */}
      {messages.length > 0 && (
        <div className="space-y-3 mb-6">
          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`p-4 rounded-lg border ${getMessageStyle(msg.severity)}`}
            >
              <div className="font-medium">{msg.message}</div>
              {msg.details && (
                <div className="text-sm mt-1 opacity-80">{msg.details}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Data summary */}
      {summary && (
        <div className="card">
          <h2 className="card-header">Data Summary</h2>
          <dl className="grid grid-cols-2 gap-4">
            <div>
              <dt className="text-sm text-gray-500">Respondents</dt>
              <dd className="text-2xl font-semibold">{summary.n_respondents}</dd>
            </div>
            <div>
              <dt className="text-sm text-gray-500">Items</dt>
              <dd className="text-2xl font-semibold">{summary.n_items}</dd>
            </div>
            <div>
              <dt className="text-sm text-gray-500">Response Type</dt>
              <dd className="text-lg font-medium capitalize">{summary.response_type}</dd>
            </div>
            <div>
              <dt className="text-sm text-gray-500">Missing Data</dt>
              <dd className="text-lg font-medium">
                {(summary.missing_percentage * 100).toFixed(1)}%
              </dd>
            </div>
          </dl>

          <div className="mt-6 flex justify-end">
            <button
              onClick={() => navigate(`/projects/${projectId}/results`)}
              className="btn btn-primary"
            >
              Continue to Model Fitting
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
