/**
 * TypeScript types matching backend API schemas.
 * Keep these in sync with backend/app/api/schemas.py
 */

// Enums
export type StakesLevel = 'low' | 'medium' | 'high'
export type IntendedUse = 'research' | 'operational' | 'certification'
export type ResponseType = 'dichotomous' | 'polytomous'
export type JobStatus = 'pending' | 'running' | 'completed' | 'failed'
export type ModelType = '1PL' | '2PL' | '3PL'
export type ReportFormat = 'pdf' | 'html' | 'json'

// Project schemas
export interface ProjectCreate {
  name: string
  description?: string
  stakes_level?: StakesLevel
  intended_use?: IntendedUse
}

export interface ProjectResponse {
  id: string
  name: string
  description?: string
  stakes_level: StakesLevel
  intended_use: IntendedUse
  status: string
  created_at: string
  updated_at: string
}

// Upload schemas
export interface ValidationMessage {
  severity: 'info' | 'warning' | 'error'
  code: string
  message: string
  details?: string
  affected_items?: string[]
}

export interface DataSummary {
  n_respondents: number
  n_items: number
  response_type: ResponseType
  n_categories: number
  missing_percentage: number
  item_names: string[]
}

export interface UploadResponse {
  is_valid: boolean
  summary?: DataSummary
  messages: ValidationMessage[]
}

// Model fitting schemas
export interface FittingJobCreate {
  project_id: string
  fit_1pl?: boolean
  fit_2pl?: boolean
  fit_3pl?: boolean
}

export interface FittingJobResponse {
  job_id: string
  project_id: string
  status: JobStatus
  progress: number
  created_at: string
  started_at?: string
  completed_at?: string
  error_message?: string
}

export interface FittingProgress {
  job_id: string
  status: JobStatus
  progress: number
  current_model?: string
  message?: string
}

// Model results schemas
export interface ItemParameter {
  item_id: string
  discrimination: number
  difficulty: number
  guessing: number
  se_discrimination?: number
  se_difficulty?: number
  se_guessing?: number
}

export interface FitStatistics {
  log_likelihood: number
  aic: number
  bic: number
  n_parameters: number
  converged: boolean
}

export interface FittedModelSummary {
  model_type: ModelType
  fit_stats: FitStatistics
  n_items: number
  warnings: string[]
}

export interface ModelComparisonSummary {
  models_fitted: ModelType[]
  recommended_model: ModelType
  selection_reasons: string[]
  comparison_table: Record<string, Record<string, number>>
}

export interface ModelResultResponse {
  project_id: string
  comparison: ModelComparisonSummary
  selected_model: FittedModelSummary
  item_parameters: ItemParameter[]
  reliability_estimate: number
}

// Diagnostics schemas
export interface ICCDataPoint {
  theta: number
  probability: number
  information: number
}

export interface ICCResponse {
  item_id: string
  data: ICCDataPoint[]
  difficulty: number
  discrimination: number
}

export interface TIFDataPoint {
  theta: number
  information: number
  standard_error: number
}

export interface TIFResponse {
  data: TIFDataPoint[]
  peak_theta: number
  peak_information: number
  coverage_low: number
  coverage_high: number
}

export interface ItemDiagnosticSummary {
  item_id: string
  status: 'good' | 'acceptable' | 'flagged' | 'problematic'
  discrimination: number
  difficulty: number
  guessing: number
  max_information: number
  flags: string[]
}

export interface DiagnosticsResponse {
  project_id: string
  tif: TIFResponse
  items: ItemDiagnosticSummary[]
  reliability: number
  n_flagged: number
}

// Recommendations schemas
export interface RecommendationItem {
  priority: 'critical' | 'high' | 'medium' | 'low'
  category: string
  title: string
  description: string
  action: string
  affected_items: string[]
}

export interface RecommendationsResponse {
  project_id: string
  overall_assessment: string
  is_ready_for_use: boolean
  reliability?: number
  recommendations: RecommendationItem[]
}

// Report schemas
export interface ReportRequest {
  project_id: string
  format: ReportFormat
  include_technical_appendix?: boolean
  include_item_details?: boolean
}

export interface ReportResponse {
  project_id: string
  format: ReportFormat
  download_url: string
  generated_at: string
  expires_at: string
}

// Health check
export interface HealthCheckResponse {
  status: string
  timestamp: string
  version: string
}
