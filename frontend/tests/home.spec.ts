import { expect, test } from '@playwright/test';

test('shows the Wonky Studio home page', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveTitle('Wonky Studio');
  await expect(page.getByRole('heading', { name: 'Wonky Studio' })).toBeVisible();
  await expect(page.getByText('Asset management')).toBeVisible();
});

