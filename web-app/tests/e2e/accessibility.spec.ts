import { expect, test, type Page } from "@playwright/test";
import { installRoutes } from "./support/mock-local-api";

async function collectUnnamedInteractiveControls(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const interactiveSelectors = [
      "button",
      "[role='button']",
      "a[href]",
      "[role='link']",
      "input",
      "textarea",
      "select",
      "[role='checkbox']",
      "[role='combobox']",
      "[role='menuitem']",
      "[role='menuitemcheckbox']",
      "[role='menuitemradio']",
      "[role='radio']",
      "[role='switch']",
      "[role='tab']",
    ].join(",");

    const describe = (el: Element) => {
      const id = el.id ? `#${el.id}` : "";
      const className = typeof (el as HTMLElement).className === "string" ? String((el as HTMLElement).className).trim().replace(/\s+/g, ".") : "";
      return `${el.tagName.toLowerCase()}${id}${className ? `.${className}` : ""}`;
    };

    const getAssociatedLabel = (el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement) => {
      const labels = Array.from(el.labels ?? [])
        .map((label) => label.textContent?.replace(/\s+/g, " ").trim() ?? "")
        .filter(Boolean);
      if (labels.length) return labels.join(" ");
      const ariaLabelledBy = el.getAttribute("aria-labelledby");
      if (ariaLabelledBy) {
        const label = ariaLabelledBy
          .split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim() ?? "")
          .filter(Boolean)
          .join(" ")
          .trim();
        if (label) return label;
      }
      return "";
    };

    const controls = Array.from(document.querySelectorAll(interactiveSelectors))
      .filter((el) => el instanceof HTMLElement)
      .filter((el) => {
        const style = window.getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && el.getClientRects().length > 0;
      });

    const issues: string[] = [];
    for (const el of controls) {
      const ariaLabel = el.getAttribute("aria-label")?.replace(/\s+/g, " ").trim() ?? "";
      const title = el.getAttribute("title")?.replace(/\s+/g, " ").trim() ?? "";
      const text = el.textContent?.replace(/\s+/g, " ").trim() ?? "";

      let label = ariaLabel || title || text;
      if ((el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) && !label) {
        label = getAssociatedLabel(el);
        if (!label) label = el.placeholder?.replace(/\s+/g, " ").trim() ?? "";
      }

      if (!label) {
        issues.push(describe(el));
      }
    }

    return issues;
  });
}

test("unlocked shell keeps critical controls named in the accessibility tree", async ({ page }) => {
  await installRoutes(page, false);

  await page.goto("/#t=launch-token", { waitUntil: "commit" });

  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("button", { name: "Lock vault" })).toBeVisible();

  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await expect(skipLink).toBeAttached();
  await expect(skipLink).toHaveAttribute("href", "#main-content");
  await expect(page.locator("main#main-content")).toBeAttached();

  const unnamedControls = await collectUnnamedInteractiveControls(page);
  expect(unnamedControls).toEqual([]);
});

test("vault tab exposes labeled search and disclosure state", async ({ page }) => {
  await installRoutes(page, false);

  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Vault" }).click();

  await expect(page.getByLabel("Search keys or providers")).toBeVisible();
  await expect(page.getByRole("button", { name: "All", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Group by provider" })).toHaveAttribute("aria-pressed", "false");

  const addKey = page.getByRole("button", { name: "Add key" });
  await expect(addKey).toHaveAttribute("aria-expanded", "false");
  await addKey.click();
  await expect(page.getByRole("button", { name: "Cancel" })).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("New key")).toBeVisible();

  const unnamedControls = await collectUnnamedInteractiveControls(page);
  expect(unnamedControls).toEqual([]);
});

test("health tab exposes labeled filters and disclosure state", async ({ page }) => {
  await installRoutes(page, false);

  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Health" }).click();

  await expect(page.getByLabel(/Staleness threshold/i)).toBeVisible();

  const disclosure = page.getByRole("button", { name: "Healthy keys (0)" });
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  await disclosure.click();
  await expect(disclosure).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("region", { name: "Healthy keys (0)" })).toBeVisible();
  await expect(page.getByText("No healthy keys.")).toBeVisible();
});

test("locked shell keeps login controls named in the accessibility tree", async ({ page }) => {
  await installRoutes(page, true);

  await page.goto("/#t=launch-token", { waitUntil: "commit" });

  await expect(page.getByLabel("Master password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Master Password" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Recovery Code" })).toBeVisible();

  const unnamedControls = await collectUnnamedInteractiveControls(page);
  expect(unnamedControls).toEqual([]);
});
