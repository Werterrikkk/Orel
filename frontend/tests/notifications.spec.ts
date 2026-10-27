import { test, expect } from '@playwright/test'
import { checkAccessibility } from './accessibility'
import type { TelegramStatus } from '../src/types'

const initial = (): TelegramStatus => ({
  configured: false,
  enabled: false,
  bot_username: '',
  chat_id: '',
  pending: 0,
  cooldown_seconds: 30,
  last_test_at: null,
  queue_error: null,
  deliveries: [],
})

test('Telegram setup is readable and does not offer sending before configuration', async ({
  page,
}) => {
  await page.route('**/api/telegram', (route) => route.fulfill({ json: initial() }))
  await page.goto('/')
  await page.getByRole('button', { name: 'Уведомления', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Telegram', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '@BotFather' })).toHaveAttribute(
    'href',
    'https://t.me/BotFather',
  )
  await expect(page.getByRole('button', { name: 'Отправить тест', exact: true })).toBeDisabled()
  await checkAccessibility(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  await checkAccessibility(page)
  await page.screenshot({ path: '../reports/local/telegram-setup-mobile.png', fullPage: true })
})

test('bot setup, explicit chat selection and test delivery handle API responses', async ({
  page,
}) => {
  // Test-only API responses. No real bot token or external messages are used.
  let status = initial(),
    testsSent = 0
  await page.route('**/api/telegram', async (route) => {
    if (route.request().method() === 'PUT')
      status = { ...status, ...route.request().postDataJSON() }
    await route.fulfill({ json: status })
  })
  await page.route('**/api/telegram/bot', async (route) => {
    expect(route.request().postDataJSON().token).toContain('TEST_ONLY')
    status = { ...status, configured: true, bot_username: 'orel_test_bot' }
    await route.fulfill({ json: status })
  })
  await page.route('**/api/telegram/chats', (route) =>
    route.fulfill({ json: [{ id: '42', title: 'Демо-чат', type: 'private' }] }),
  )
  await page.route('**/api/telegram/test', async (route) => {
    testsSent++
    status = { ...status, last_test_at: '2026-10-22T12:00:00+00:00' }
    await route.fulfill({ json: status })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Уведомления', exact: true }).click()
  const token = page.getByLabel('Токен бота', { exact: true })
  await expect(token).toHaveAttribute('type', 'password')
  await token.fill('123456:TEST_ONLY_NOT_A_REAL_TOKEN_VALUE')
  await page.getByRole('button', { name: 'Проверить и подключить', exact: true }).click()
  await expect(token).toHaveValue('')
  await page.getByRole('button', { name: 'Найти чаты', exact: true }).click()
  await page.getByRole('combobox', { name: 'Доступные чаты', exact: true }).selectOption('42')
  await page.getByLabel('Отправлять события в Telegram', { exact: true }).check()
  await page.getByRole('button', { name: 'Сохранить настройки', exact: true }).click()
  await expect(page.getByText('Уведомления включены', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Отправить тест', exact: true }).click()
  await expect(
    page.getByText('Тестовое сообщение отправлено в сохранённый чат.', { exact: true }),
  ).toBeVisible()
  expect(testsSent).toBe(1)
  await checkAccessibility(page)
  await page.screenshot({ path: '../reports/local/telegram-configured.png', fullPage: true })
})
