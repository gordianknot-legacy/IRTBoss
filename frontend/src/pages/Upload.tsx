import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  uploadData,
  ApiError,
  type DataSummary,
  type ValidationMessage,
} from '../api'

export default function Upload() {
  const { projectId } = useParams<{ projectId: string }>()
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
      // Clear previous results
      setSummary(null)
      setMessages([])
    }
  }, [])

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0])
      // Clear previous results
      setSummary(null)
      setMessages([])
    }
  }

  const handleUpload = async () => {
    if (!file || !projectId) return

    setUploading(true)
    setMessages([])
    setSummary(null)

    try {
      const response = await uploadData(projectId, file)
      setSummary(response.summary || null)
      setMessages(response.messages)
    } catch (error) {
      if (error instanceof ApiError) {
        setMessages([{
          severity: 'error',
          code: 'API_ERROR',
          message: error.detail || error.message,
        }])
      } else {
        setMessages([{
          severity: 'error',
          code: 'UPLOAD_FAILED',
          message: 'Failed to upload file',
          details: error instanceof Error ? error.message : 'Unknown error',
        }])
      }
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

  const getMessageIcon = (severity: string) => {
    switch (severity) {
      case 'error':
        return (
          <svg className="w-5 h-5 text-red-400" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
        )
      case 'warning':
        return (
          <svg className="w-5 h-5 text-yellow-400" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
        )
      default:
        return (
          <svg className="w-5 h-5 text-blue-400" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
          </svg>
        )
    }
  }

  const hasErrors = messages.some(m => m.severity === 'error')
  const isValid = summary && !hasErrors

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
              <span className="text-gray-500 ml-2">
                ({(file.size / 1024).toFixed(1)} KB)
              </span>
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
              {uploading ? (
                <>
                  <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Validating...
                </>
              ) : (
                'Upload & Validate'
              )}
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
              className={`p-4 rounded-lg border flex items-start gap-3 ${getMessageStyle(msg.severity)}`}
            >
              {getMessageIcon(msg.severity)}
              <div className="flex-1">
                <div className="font-medium">{msg.message}</div>
                {msg.details && (
                  <div className="text-sm mt-1 opacity-80">{msg.details}</div>
                )}
                {msg.affected_items && msg.affected_items.length > 0 && (
                  <div className="text-sm mt-2">
                    <span className="font-medium">Affected items:</span>{' '}
                    {msg.affected_items.join(', ')}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Data summary */}
      {summary && (
        <div className="card">
          <h2 className="card-header">Data Summary</h2>
          <dl className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <dt className="text-sm text-gray-500">Respondents</dt>
              <dd className="text-2xl font-semibold">{summary.n_respondents.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-sm text-gray-500">Items</dt>
              <dd className="text-2xl font-semibold">{summary.n_items}</dd>
            </div>
            <div>
              <dt className="text-sm text-gray-500">Response Type</dt>
              <dd className="text-lg font-medium capitalize">{summary.response_type}</dd>
              {summary.n_categories > 2 && (
                <dd className="text-sm text-gray-500">{summary.n_categories} categories</dd>
              )}
            </div>
            <div>
              <dt className="text-sm text-gray-500">Missing Data</dt>
              <dd className="text-lg font-medium">
                {(summary.missing_percentage * 100).toFixed(1)}%
              </dd>
            </div>
          </dl>

          {summary.item_names && summary.item_names.length > 0 && (
            <div className="mt-6 pt-6 border-t border-gray-200">
              <h3 className="text-sm font-medium text-gray-700 mb-2">Item Names</h3>
              <div className="flex flex-wrap gap-2">
                {summary.item_names.slice(0, 20).map((name, idx) => (
                  <span
                    key={idx}
                    className="px-2 py-1 bg-gray-100 rounded text-sm text-gray-700"
                  >
                    {name}
                  </span>
                ))}
                {summary.item_names.length > 20 && (
                  <span className="px-2 py-1 text-sm text-gray-500">
                    +{summary.item_names.length - 20} more
                  </span>
                )}
              </div>
            </div>
          )}

          {isValid && (
            <div className="mt-6 flex justify-end">
              <button
                onClick={() => navigate(`/projects/${projectId}/results`)}
                className="btn btn-primary"
              >
                Continue to Model Fitting
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
