import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schemas = components['schemas']

/** Typed client generated from the backend's OpenAPI (`npm run gen:api`).
 *  window.fetch is resolved per call so the optional API-token shim applies. */
export const api = createClient<paths>({ baseUrl: '', fetch: (r) => window.fetch(r) })

export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p
  if (error !== undefined || data === undefined) {
    const detail = (error as { detail?: { title?: string } | string } | undefined)?.detail
    const msg = typeof detail === 'string' ? detail : detail?.title ?? `${response.status} ${response.statusText}`
    throw new Error(msg)
  }
  return data
}
