import { expect, test } from '@playwright/test'
import { ApiError, formatApiError } from '../src/api/core'
import { clerkBrowserScriptUrl, safeNextPath } from '../src/pages/LoginPage'

test('formatApiError never returns a non-string detail from a 422 body', () => {
  const error = new ApiError(
    'Request failed: 422',
    422,
    JSON.stringify({ detail: [{ loc: ['body', 'name'], msg: 'field required' }] }),
  )
  const message = formatApiError(error)
  expect(typeof message).toBe('string')
  expect(message).not.toContain('[object Object]')
})

test('Clerk browser script URL is pinned to an exact version', () => {
  const url = clerkBrowserScriptUrl('clerk.example.com')
  expect(url).not.toContain('@latest')
  expect(url).toMatch(/@clerk\/clerk-js@\d+\.\d+\.\d+\/dist\/clerk\.browser\.js$/)
})

test('safeNextPath rejects protocol-relative redirects', () => {
  expect(safeNextPath('//evil.test/x')).toBe('/containers')
  expect(safeNextPath('/containers')).toBe('/containers')
})
