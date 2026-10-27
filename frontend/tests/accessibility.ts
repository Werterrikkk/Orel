import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

export async function checkAccessibility(page: Page) {
  // Measure the rendered text after fonts and finite entrance transitions settle.
  // A spinner may run forever; it must not block the accessibility audit.
  await page.evaluate(async () => {
    await document.fonts.ready
    await Promise.all(
      document
        .getAnimations()
        .filter((animation) => animation.effect?.getTiming().iterations !== Infinity)
        .map((animation) => animation.finished.catch(() => undefined)),
    )
  })
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze()
  expect(
    results.violations.map(({ id, nodes }) => ({
      id,
      nodes: nodes.map(({ target, failureSummary }) => ({ target, failureSummary })),
    })),
  ).toEqual([])
}
