import { expect, test } from '@playwright/test';

test('redirects unauthenticated visitors to sign in', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveTitle('Wonky Studio');
  await expect(page.getByRole('heading', { name: 'Wonky Studio' })).toBeVisible();
  await expect(page.getByText('Not authorized')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Continue with Google' })).toBeVisible();
});
