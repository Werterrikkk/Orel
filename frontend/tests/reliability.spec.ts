import { test, expect } from '@playwright/test'
import { checkAccessibility } from './accessibility'

test('initial connection recovers without reloading', async ({ page }) => {
  let unavailable = true
  await page.route('**/api/bootstrap', (route) => (unavailable ? route.abort() : route.continue()))
  await page.goto('/')
  await expect(page.locator('.console-error')).toContainText('Нет ответа от локального сервера')
  unavailable = false
  await expect(page.locator('.console-error')).toHaveCount(0, { timeout: 6000 })
  await expect(page.getByRole('button', { name: 'Включить превью', exact: true })).toBeEnabled()
})

test('Rubetek waits for SDK while laptop preview is available', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Камеры', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Rubetek', exact: true })).toBeVisible()
  await expect(page.getByText('Ожидает подключения', { exact: true })).toBeVisible()
  await expect(page.getByText('На камере · планируется', { exact: true })).toBeVisible()
  await checkAccessibility(page)
  await page.getByRole('button', { name: 'Открыть превью' }).click()
  await expect(page.getByRole('heading', { name: 'Эфир', exact: true })).toBeVisible()
})

test('old backend receives an actionable version message', async ({ page }) => {
  await page.route('**/api/sources', (route) =>
    route.fulfill({ status: 404, json: { detail: 'Not Found' } }),
  )
  await page.goto('/')
  await expect(page.locator('.console-error')).toContainText('Перезапустите приложение')
})
