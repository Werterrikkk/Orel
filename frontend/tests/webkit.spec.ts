import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'
const photo = readFileSync(
  fileURLToPath(new URL('../../data/datasets/ppe3/images/test/image1003.jpg', import.meta.url)),
).toString('base64')

test.beforeEach(async ({ page, request }) => {
  test.skip(
    !(await (await request.get('/api/bootstrap')).json()).models.ppe.available,
    'Activate trained PPE weights first.',
  )
  await request.put('/api/camera/configuration', {
    data: { require_helmet: true, require_vest: false, danger_zone: null },
  })
  // A canvas MediaStream checks WebKit playback without a physical camera.
  // Normal HTTP inference still uses the actual trained weights.
  await page.addInitScript((photo) => {
    // WebKit can replace the MediaDevices wrapper after device enumeration.
    Object.getPrototypeOf(navigator.mediaDevices).getUserMedia = async () => {
      const canvas = document.createElement('canvas')
      canvas.width = 640
      canvas.height = 360
      const context = canvas.getContext('2d')!,
        image = new Image()
      image.src = `data:image/jpeg;base64,${photo}`
      await image.decode()
      const draw = () => {
        context.fillStyle = '#000'
        context.fillRect(0, 0, 640, 360)
        if ((window as unknown as { hideTestPerson?: boolean }).hideTestPerson) return
        const scale = Math.min(640 / image.width, 360 / image.height)
        const width = image.width * scale,
          height = image.height * scale
        context.drawImage(image, (640 - width) / 2, (360 - height) / 2, width, height)
      }
      draw()
      setInterval(draw, 100)
      return canvas.captureStream(10)
    }
  }, photo)
})

test('WebKit renders a stream with real model labels', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Включить превью', exact: true }).click()
  await expect(page.locator('.live-status')).toContainText('Прямой эфир', { timeout: 15000 })
  await expect(page.locator('.live-overlay').getByText('Каска', { exact: true })).toBeVisible()
  await expect(page.locator('.stage-error')).toHaveCount(0)
  await page.screenshot({ path: '../reports/local/surveillance-webkit.png', fullPage: true })
  await page.getByRole('button', { name: 'Остановить', exact: true }).click()
  await expect(page.locator('.live-status')).toContainText('Превью выключено')
})

test('a person returning after two seconds recovers the displayed ID', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Включить превью', exact: true }).click()
  const label = page.locator('.live-overlay .detection.person text')
  await expect(label).toHaveText(/^Человек · \d+$/, { timeout: 15000 })
  const original = await label.textContent()
  await page.evaluate(() => {
    ;(window as unknown as { hideTestPerson: boolean }).hideTestPerson = true
  })
  await expect(label).toHaveCount(0)
  await expect(page.locator('.live-footer')).toContainText('Нет данных о людях')
  // Real blank JPEGs go through YOLO; no detection responses are replaced.
  await page.waitForTimeout(2000)
  await page.evaluate(() => {
    ;(window as unknown as { hideTestPerson: boolean }).hideTestPerson = false
  })
  await expect(label).toHaveText(original!)
  await expect(page.locator('.live-footer')).toContainText('1 чел.')
  await page.getByRole('button', { name: 'Остановить', exact: true }).click()
})

test('WebKit offers manual playback when autoplay is denied', async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLMediaElement.prototype.play
    ;(window as unknown as { allowPlayback: boolean }).allowPlayback = false
    HTMLMediaElement.prototype.play = function () {
      if (this.srcObject && !(window as unknown as { allowPlayback: boolean }).allowPlayback)
        return Promise.reject(new DOMException('Test denied', 'NotAllowedError'))
      return original.call(this)
    }
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Включить превью', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Показать изображение', exact: true }),
  ).toBeVisible()
  await page.evaluate(() => {
    ;(window as unknown as { allowPlayback: boolean }).allowPlayback = true
  })
  await page.getByRole('button', { name: 'Показать изображение', exact: true }).click()
  await expect(page.locator('.live-status')).toContainText('Прямой эфир', { timeout: 15000 })
  await expect(page.locator('.stage-error')).toHaveCount(0)
  await page.getByRole('button', { name: 'Остановить', exact: true }).click()
})

test('covered camera clears detections and saves a single camera event', async ({
  page,
  request,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Включить превью', exact: true }).click()
  await expect(page.locator('.live-status')).toContainText('Прямой эфир', { timeout: 15000 })
  const prior = (await (await request.get('/api/events')).json()).filter(
    (e: { code: string }) => e.code === 'camera_obscured',
  ).length
  await page.evaluate(() => {
    ;(window as unknown as { hideTestPerson: boolean }).hideTestPerson = true
  })
  await expect(page.locator('.camera-health-alert')).toContainText('Камера закрыта')
  await expect(page.locator('.detection')).toHaveCount(0)
  await expect
    .poll(
      async () =>
        (await (await request.get('/api/events')).json()).filter(
          (e: { code: string }) => e.code === 'camera_obscured',
        ).length,
      { timeout: 10000 },
    )
    .toBe(prior + 1)
  await page.screenshot({ path: '../reports/local/v2-camera-covered.png', fullPage: true })
  await page.evaluate(() => {
    ;(window as unknown as { hideTestPerson: boolean }).hideTestPerson = false
  })
  await expect(page.locator('.camera-health-alert')).toHaveCount(0)
  await expect(page.locator('.detection.person')).toHaveCount(1)
  await page.getByRole('button', { name: 'Остановить', exact: true }).click()
})
