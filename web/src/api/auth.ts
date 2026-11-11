// Optional API token: when the server runs with BIONEXUS_API_TOKEN(S), the
// workbench must present it on every write. Set it once in the browser:
//   localStorage.setItem('bn_token', '<your token>')
// Approvals are then attributed to the token's owner server-side.
const token = typeof localStorage !== 'undefined' ? localStorage.getItem('bn_token') : null
if (token) {
  const orig = window.fetch.bind(window)
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined))
    headers.set('X-BioNexus-Token', token)
    return orig(input, { ...init, headers })
  }
}
export {}
