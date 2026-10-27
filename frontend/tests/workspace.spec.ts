import { test, expect } from '@playwright/test'
import { checkAccessibility } from './accessibility'

test('surveillance fills the viewport and stays accessible on desktop and mobile', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Эфир', exact: true })).toBeVisible()
  await checkAccessibility(page)
  const stage = (await page.locator('.surveillance-stage').boundingBox())!
  expect(stage.height).toBeGreaterThan(450)
  expect(stage.width).toBeGreaterThan(600)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await checkAccessibility(page)
  await page.screenshot({ path: '../reports/local/surveillance-mobile.png', fullPage: true })
})

test('four clicked corners and PPE requirements persist', async ({ page, request }) => {
  await request.put('/api/camera/configuration', {
    data: { require_helmet: true, require_vest: false, danger_zone: null },
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Зона и СИЗ', exact: true }).click()
  await page.getByRole('button', { name: 'Выделить на видео', exact: true }).click()
  const rect = (await page.locator('.live-overlay').boundingBox())!
  for (const [x, y] of [
    [0.2, 0.3],
    [0.8, 0.4],
    [0.9, 0.95],
    [0.1, 0.9],
  ])
    await page.mouse.click(rect.x + rect.width * x, rect.y + rect.height * y)
  await page.getByRole('button', { name: 'Сохранить зону', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Сохранить зону', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Зона и СИЗ', exact: true }).click()
  await page.getByLabel('Название', { exact: true }).fill('Проход у котла')
  await page.getByLabel('Жилет обязателен', { exact: true }).check()
  await page.getByRole('button', { name: 'Сохранить настройки', exact: true }).click()
  await expect(page.getByText('Настройки сохранены', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: 'Зона и СИЗ', exact: true }).click()
  await expect(page.getByLabel('Название', { exact: true })).toHaveValue('Проход у котла')
  await expect(page.getByLabel('Жилет обязателен', { exact: true })).toBeChecked()
  await checkAccessibility(page)
})

test('journal is accessible and exports CSV', async ({ page, request }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Журнал событий', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Журнал событий', exact: true }).first(),
  ).toBeVisible()
  await checkAccessibility(page)
  expect((await request.get('/api/events.csv')).ok()).toBe(true)
})
