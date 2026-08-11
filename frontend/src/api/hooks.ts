import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import { ApiError, del, get, patch, post, postForm } from './client'
import type {
  AnalysisResult,
  AnalysisRun,
  Dataset,
  Project,
  ProjectCreate,
  Session,
  User,
} from './types'

export const keys = {
  me: ['me'] as const,
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  datasets: (projectId: string) => ['projects', projectId, 'datasets'] as const,
  dataset: (id: string) => ['datasets', id] as const,
  runs: (datasetId: string) => ['datasets', datasetId, 'analyses'] as const,
  run: (id: string) => ['analyses', id] as const,
  results: (id: string) => ['analyses', id, 'results'] as const,
}

/* --- auth ---------------------------------------------------------------- */

export function useCurrentUser(): UseQueryResult<User | null> {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return await get<User>('/auth/me')
      } catch (error) {
        // A 401 is the answer "nobody is signed in", not a failure to answer.
        // Retrying or surfacing it as an error would put an error banner on the
        // login screen of every first-time visitor.
        if (error instanceof ApiError && error.isUnauthenticated) return null
        throw error
      }
    },
    retry: false,
    staleTime: 60_000,
  })
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      post<Session>('/auth/login', body),
    onSuccess: (session) => client.setQueryData(keys.me, session.user),
  })
}

export function useRegister() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      post<Session>('/auth/register', body),
    onSuccess: (session) => client.setQueryData(keys.me, session.user),
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => post<void>('/auth/logout'),
    onSuccess: () => {
      client.setQueryData(keys.me, null)
      client.clear()
    },
  })
}

/* --- projects ------------------------------------------------------------ */

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: () => get<Project[]>('/projects') })
}

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: keys.project(id ?? ''),
    queryFn: () => get<Project>(`/projects/${id}`),
    enabled: Boolean(id),
  })
}

export function useCreateProject() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: ProjectCreate) => post<Project>('/projects', body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.projects }),
  })
}

export function useUpdateProject(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<ProjectCreate>) => patch<Project>(`/projects/${id}`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.projects })
      void client.invalidateQueries({ queryKey: keys.project(id) })
    },
  })
}

export function useDeleteProject() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => del<void>(`/projects/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.projects }),
  })
}

/* --- datasets ------------------------------------------------------------ */

export function useDatasets(projectId: string | undefined) {
  return useQuery({
    queryKey: keys.datasets(projectId ?? ''),
    queryFn: () => get<Dataset[]>(`/projects/${projectId}/datasets`),
    enabled: Boolean(projectId),
  })
}

export function useDataset(id: string | undefined) {
  return useQuery({
    queryKey: keys.dataset(id ?? ''),
    queryFn: () => get<Dataset>(`/datasets/${id}`),
    enabled: Boolean(id),
  })
}

export interface UploadArgs {
  file: File
  idColumn: string | null
  groupColumns: string[]
}

export function useUploadDataset(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, idColumn, groupColumns }: UploadArgs) => {
      const form = new FormData()
      form.append('file', file)
      // Both are `Form(default=None)`; omitting is meaningfully different from
      // sending an empty string, which would be a column named "".
      if (idColumn) form.append('id_column', idColumn)
      if (groupColumns.length > 0) form.append('group_columns', JSON.stringify(groupColumns))
      return postForm<Dataset>(`/projects/${projectId}/datasets`, form)
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.datasets(projectId) }),
  })
}

/* --- analyses ------------------------------------------------------------ */

export function useRuns(datasetId: string | undefined) {
  return useQuery({
    queryKey: keys.runs(datasetId ?? ''),
    queryFn: () => get<AnalysisRun[]>(`/datasets/${datasetId}/analyses`),
    enabled: Boolean(datasetId),
  })
}

export function useCreateAnalysis(datasetId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { models: string[]; seed: number }) =>
      post<AnalysisRun>(`/datasets/${datasetId}/analyses`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runs(datasetId) }),
  })
}

const TERMINAL: ReadonlySet<string> = new Set(['succeeded', 'failed'])

/**
 * Poll target. `GET /analyses/{id}` reads the durable row, so the status is
 * correct across a worker or API restart; the interval simply stops once the
 * run reaches a terminal state.
 */
export function useRun(id: string | undefined) {
  return useQuery({
    queryKey: keys.run(id ?? ''),
    queryFn: () => get<AnalysisRun>(`/analyses/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status != null && TERMINAL.has(status) ? false : 2000
    },
  })
}

/**
 * Results are only fetched once the run has succeeded. Fetching earlier gets a
 * 409 by design — the backend refuses to serve a results document for an
 * incomplete run, because that document would be a page of absent numbers
 * presented as findings.
 */
export function useResults(id: string | undefined, ready: boolean) {
  return useQuery({
    queryKey: keys.results(id ?? ''),
    queryFn: () => get<AnalysisResult>(`/analyses/${id}/results`),
    enabled: Boolean(id) && ready,
    staleTime: Infinity,
  })
}
