import { expect, type APIRequestContext } from '@playwright/test'

export const fullZone = {
  name: 'Тестовая зона',
  left: 0.02,
  top: 0.02,
  right: 0.98,
  bottom: 0.98,
  require_helmet: true,
  require_vest: true,
}

export async function analyzedDemo(request: APIRequestContext) {
  const opened = await request.post('/api/demo')
  expect(opened.ok()).toBe(true)
  const source = await opened.json()
  if (source.status !== 'ready') {
    if (source.status !== 'processing') {
      const response = await request.post(`/api/videos/${source.id}/analysis`, {
        data: { model: 'person' },
      })
      expect(response.ok()).toBe(true)
    }
    await expect
      .poll(async () => (await (await request.get(`/api/videos/${source.id}`)).json()).status, {
        timeout: 90_000,
      })
      .toBe('ready')
  }
  return (await request.get(`/api/videos/${source.id}`)).json()
}
