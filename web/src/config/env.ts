/** Runtime configuration, read once so the rest of the app never touches import.meta.env directly. */
const apiUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export const env = {
  apiUrl: apiUrl.replace(/\/+$/, ''),
} as const
