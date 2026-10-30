import { ApiError } from '../api/client'

/** A message safe to show a user, whatever was thrown. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
