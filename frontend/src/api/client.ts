/// <reference types="vite/client" />
/**
 * API client for IRTBoss backend.
 *
 * All API calls are made through these functions to ensure
 * consistent error handling and type safety.
 */

import type {
  ProjectCreate,
  ProjectResponse,
  UploadResponse,
  FittingJobCreate,
  FittingJobResponse,
  FittingProgress,
  ModelResultResponse,
  DiagnosticsResponse,
  ICCResponse,
  RecommendationsResponse,
  ReportRequest,
  ReportResponse,
  HealthCheckResponse,
} from './types'

// API base URL - can be configured via environment variable
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'

/**
 * Custom error class for API errors
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public detail?: string
  ) {
    super(detail || `${status} ${statusText}`)
    this.name = 'ApiError'
  }
}

/**
 * Make a fetch request with error handling
 */
async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`

  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    let detail: string | undefined
    try {
      const errorData = await response.json()
      detail = errorData.detail
    } catch {
      // Ignore JSON parse errors
    }
    throw new ApiError(response.status, response.statusText, detail)
  }

  return response.json()
}

// --- Health Check ---

export async function checkHealth(): Promise<HealthCheckResponse> {
  return fetchApi<HealthCheckResponse>('/health')
}

// --- Projects ---

export async function createProject(
  data: ProjectCreate
): Promise<ProjectResponse> {
  return fetchApi<ProjectResponse>('/projects', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getProject(projectId: string): Promise<ProjectResponse> {
  return fetchApi<ProjectResponse>(`/projects/${projectId}`)
}

export async function listProjects(
  limit = 20,
  offset = 0
): Promise<ProjectResponse[]> {
  return fetchApi<ProjectResponse[]>(
    `/projects?limit=${limit}&offset=${offset}`
  )
}

// --- Data Upload ---

export async function uploadData(
  projectId: string,
  file: File
): Promise<UploadResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const url = `${API_BASE_URL}/projects/${projectId}/upload`
  const response = await fetch(url, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    let detail: string | undefined
    try {
      const errorData = await response.json()
      detail = errorData.detail
    } catch {
      // Ignore JSON parse errors
    }
    throw new ApiError(response.status, response.statusText, detail)
  }

  return response.json()
}

// --- Model Fitting ---

export async function startFitting(
  data: FittingJobCreate
): Promise<FittingJobResponse> {
  return fetchApi<FittingJobResponse>(`/projects/${data.project_id}/fit`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getJobStatus(jobId: string): Promise<FittingJobResponse> {
  return fetchApi<FittingJobResponse>(`/jobs/${jobId}`)
}

export async function getJobProgress(jobId: string): Promise<FittingProgress> {
  return fetchApi<FittingProgress>(`/jobs/${jobId}/progress`)
}

/**
 * Poll job status until completion or failure.
 * Returns the final job status.
 */
export async function pollJobUntilComplete(
  jobId: string,
  onProgress?: (progress: FittingProgress) => void,
  intervalMs = 2000
): Promise<FittingJobResponse> {
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const progress = await getJobProgress(jobId)

        if (onProgress) {
          onProgress(progress)
        }

        if (progress.status === 'completed' || progress.status === 'failed') {
          const job = await getJobStatus(jobId)
          resolve(job)
        } else {
          setTimeout(poll, intervalMs)
        }
      } catch (error) {
        reject(error)
      }
    }

    poll()
  })
}

// --- Results ---

export async function getResults(
  projectId: string
): Promise<ModelResultResponse> {
  return fetchApi<ModelResultResponse>(`/projects/${projectId}/results`)
}

export async function getDiagnostics(
  projectId: string
): Promise<DiagnosticsResponse> {
  return fetchApi<DiagnosticsResponse>(`/projects/${projectId}/diagnostics`)
}

export async function getItemICC(
  projectId: string,
  itemId: string
): Promise<ICCResponse> {
  return fetchApi<ICCResponse>(
    `/projects/${projectId}/diagnostics/icc/${encodeURIComponent(itemId)}`
  )
}

// --- Recommendations ---

export async function getRecommendations(
  projectId: string
): Promise<RecommendationsResponse> {
  return fetchApi<RecommendationsResponse>(
    `/projects/${projectId}/recommendations`
  )
}

// --- Reports ---

export async function generateReport(
  data: ReportRequest
): Promise<ReportResponse> {
  return fetchApi<ReportResponse>(`/projects/${data.project_id}/report`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function getReportDownloadUrl(
  projectId: string,
  format: string
): string {
  return `${API_BASE_URL}/projects/${projectId}/report/${format}`
}
