import { test, expect } from '@playwright/test'
import { checkAccessibility } from './accessibility'

const start = async (page: import('@playwright/test').Page) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Включить превью', exact: true }).click()
}
const running = async (page: import('@playwright/test').Page) =>
  expect(page.locator('.live-status')).toContainText('Прямой эфир', { timeout: 15000 })

test.beforeEach(async ({ request }) => {
  test.skip(
    !(await (await request.get('/api/bootstrap')).json()).models.ppe.available,
    'Activate trained PPE weights first.',
  )
  await request.put('/api/camera/configuration', {
    data: { require_helmet: true, require_vest: false, danger_zone: null },
  })
})

test('real model labels PPE, escalates after ten seconds and saves one episode', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  let pending = 0,
    maxPending = 0
  const hashes = new Set<string>()
  page.on('request', (request) => {
    if (request.url().includes('/frames?')) maxPending = Math.max(maxPending, ++pending)
  })
  page.on('requestfinished', (request) => {
    if (request.url().includes('/frames?')) pending--
  })
  page.on('requestfailed', (request) => {
    if (request.url().includes('/frames?')) pending--
  })
  page.on('response', async (response) => {
    if (response.url().includes('/frames?') && response.ok()) {
      const body = await response.json().catch(() => null)
      if (body) hashes.add(body.model.weights_sha256)
    }
  })
  const previous = (await (await request.get('/api/events')).json()).length
  await start(page)
  await expect(page.locator('.live-overlay text').getByText('Каска', { exact: true })).toBeVisible({
    timeout: 15000,
  })
  await expect(page.locator('.live-overlay text').getByText(/^Человек · \d+$/)).toBeVisible()
  expect(
    await page.evaluate(
      () => (document.querySelector('video')!.srcObject as MediaStream).getAudioTracks().length,
    ),
  ).toBe(0)
  await page.screenshot({ path: '../reports/local/surveillance-live.png', fullPage: true })
  await expect(
    page.getByText('Перепроверяем сигнал по нескольким кадрам…', { exact: true }),
  ).toBeVisible({ timeout: 15000 })
  await expect(page.locator('.video-alert')).toHaveCount(0)
  expect((await (await request.get('/api/events')).json()).length).toBe(previous)
  await expect(
    page.locator('.video-alert.warning').getByText('Наденьте СИЗ', { exact: true }),
  ).toBeVisible({ timeout: 15000 })
  await expect(
    page.locator('.video-alert.critical').getByText('Наденьте СИЗ', { exact: true }),
  ).toBeVisible({ timeout: 15000 })
  await expect
    .poll(async () => (await (await request.get('/api/events')).json()).length)
    .toBe(previous + 1)
  await page.screenshot({ path: '../reports/local/surveillance-critical.png', fullPage: true })
  await checkAccessibility(page)
  expect(maxPending).toBe(1)
  expect(
    hashes.has((await (await request.get('/api/bootstrap')).json()).models.ppe.weights_sha256),
  ).toBe(true)
  const event = (await (await request.get('/api/events')).json())[0]
  expect(event.severity).toBe('critical')
  expect((await request.get(event.snapshot_url)).ok()).toBe(true)
  await page.getByRole('button', { name: 'Журнал событий', exact: true }).click()
  await page.getByLabel('Уровень сигнала', { exact: true }).selectOption('critical')
  await page.getByRole('button', { name: 'Наденьте СИЗ', exact: true }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: 'Отметить проверенным' }).click()
  await expect(page.getByRole('button', { name: 'Вернуть на проверку' })).toBeVisible()
  await checkAccessibility(page)
  expect(errors).toEqual([])
})

test('danger zone and PPE stay visible together and the zone can be drawn on video', async ({
  page,
  request,
}) => {
  await request.put('/api/camera/configuration', {
    data: { require_helmet: true, require_vest: true, danger_zone: null },
  })
  await start(page)
  await running(page)
  await page.getByRole('button', { name: 'Зона и СИЗ', exact: true }).click()
  await page.getByRole('button', { name: 'Выделить на видео', exact: true }).click()
  const rect = (await page.locator('.live-overlay').boundingBox())!
  for (const [x, y] of [
    [0.1, 0.1],
    [0.9, 0.1],
    [0.9, 0.98],
    [0.1, 0.98],
  ])
    await page.mouse.click(rect.x + rect.width * x, rect.y + rect.height * y)
  await page.getByRole('button', { name: 'Сохранить зону', exact: true }).click()
  await expect(
    page.locator('.video-alert').getByText('Покиньте опасную зону', { exact: true }),
  ).toBeVisible({ timeout: 6000 })
  await expect(page.locator('.video-alert').getByText('Наденьте СИЗ', { exact: true })).toBeVisible(
    { timeout: 15000 },
  )
  await expect(
    page.locator('.video-alert').getByText('Покиньте опасную зону', { exact: true }),
  ).toBeVisible()
  const ppe = page.getByRole('region', { name: 'Контроль каски и жилета' })
  await expect(ppe.locator('.gear-result small')).toHaveCount(2)
  await expect(ppe.locator('.gear-result small').first()).toHaveText('Не обнаружена', {
    timeout: 15000,
  })
  await checkAccessibility(page)
  await page.screenshot({ path: '../reports/local/surveillance-zone.png', fullPage: true })
  await page.getByRole('button', { name: 'Полный экран', exact: true }).click()
  await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(true)
  await page.getByRole('button', { name: 'Выйти из полного экрана', exact: true }).click()
  await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(false)
  await page.getByRole('button', { name: 'Остановить', exact: true }).click()
  await expect(page.locator('.video-alert')).toHaveCount(0)
})

test('denied permission keeps the camera off', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException('Test denied', 'NotAllowedError')
    }
  })
  await start(page)
  await expect(page.locator('.stage-error')).toContainText('Доступ к камере запрещён')
  await expect(page.getByRole('button', { name: 'Включить превью', exact: true })).toBeEnabled()
})

test('leaving surveillance stops tracks and releases the lease', async ({ page, request }) => {
  await start(page)
  await running(page)
  await page.evaluate(() => {
    ;(window as unknown as { testTracks: MediaStreamTrack[] }).testTracks = (
      document.querySelector('video')!.srcObject as MediaStream
    ).getTracks()
  })
  const deleted = page.waitForResponse(
    (response) =>
      response.request().method() === 'DELETE' && response.url().includes('/camera/sessions/'),
  )
  await page.getByRole('button', { name: 'Камеры', exact: true }).click()
  expect((await deleted).status()).toBe(204)
  expect(
    await page.evaluate(() =>
      (window as unknown as { testTracks: MediaStreamTrack[] }).testTracks.every(
        (track) => track.readyState === 'ended',
      ),
    ),
  ).toBe(true)
  const next = await request.post('/api/camera/sessions')
  expect(next.status()).toBe(201)
  await request.delete(`/api/camera/sessions/${(await next.json()).id}`)
})

test('cancelling pending permission releases a late stream', async ({ page }) => {
  await page.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await original(constraints)
      ;(window as unknown as { lateStream: MediaStream }).lateStream = stream
      await new Promise((resolve) => setTimeout(resolve, 700))
      return stream
    }
  })
  await start(page)
  await page.waitForFunction(() => !!(window as unknown as { lateStream?: MediaStream }).lateStream)
  await page.getByRole('button', { name: 'Остановить', exact: true }).click()
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as unknown as { lateStream: MediaStream }).lateStream
          .getTracks()
          .every((track) => track.readyState === 'ended'),
      ),
    )
    .toBe(true)
})

test('stalled transport hides boxes and warnings then recovers', async ({ page }) => {
  let stalled = false
  await page.route('**/api/camera/sessions/*/frames?*', async (route) => {
    if (stalled) await new Promise((resolve) => setTimeout(resolve, 2800))
    await route.continue().catch(() => {})
  })
  await start(page)
  await running(page)
  stalled = true
  await expect(page.locator('.live-status')).toContainText('Нет свежего результата', {
    timeout: 4000,
  })
  await expect(page.locator('.live-overlay .detection')).toHaveCount(0)
  await expect(page.locator('.video-alert')).toHaveCount(0)
  stalled = false
  await running(page)
  await page.getByRole('button', { name: 'Остановить', exact: true }).click()
})

test('ending a track clears detections and allows restarting', async ({ page }) => {
  await start(page)
  await running(page)
  await page.evaluate(() =>
    (document.querySelector('video')!.srcObject as MediaStream).getVideoTracks()[0].stop(),
  )
  await expect(page.locator('.stage-error')).toContainText('Камера отключилась')
  await expect(page.getByRole('button', { name: 'Включить превью', exact: true })).toBeEnabled()
})

test('interrupted play promise does not fail a working camera', async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLMediaElement.prototype.play
    let interrupted = false
    HTMLMediaElement.prototype.play = function () {
      if (this.srcObject && !interrupted) {
        interrupted = true
        return Promise.reject(new DOMException('Test interrupted load', 'AbortError'))
      }
      return original.call(this)
    }
  })
  await start(page)
  await running(page)
  await expect(page.locator('.stage-error')).toHaveCount(0)
  await page.getByRole('button', { name: 'Остановить', exact: true }).click()
})
