import { test, expect, chromium } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { AuditCase } from "../src/types";

test.beforeEach(async ({ request }) => {
  await expect
    .poll(async () => (await request.get("/api/health")).ok())
    .toBeTruthy();
});
async function open(page: Page) {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Gone. Or just out of sight?" }),
  ).toBeVisible();
}

test("loading waits for the actual response and shows no simulated progress", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(/\/api\/cases\/demo_024(?:\?|$)/, async (route) => {
    await gate;
    await route.continue();
  });
  await page.goto("/");
  await expect(
    page.getByRole("status", { name: "Loading investigation workspace" }),
  ).toBeVisible();
  await expect(page.locator(".loading-caption")).toHaveText(
    "NO SIMULATED PROGRESS",
  );
  await page.screenshot({
    path: "../artifacts/aftertrace/refined/loading.png",
    fullPage: true,
  });
  release();
  await expect(
    page.getByRole("heading", { name: "Gone. Or just out of sight?" }),
  ).toBeVisible();
});

test("connection error has a working retry and preserves real case results", async ({
  page,
}) => {
  let failed = true;
  await page.route(/\/api\/cases\/demo_024(?:\?|$)/, async (route) => {
    if (failed)
      await route.fulfill({
        status: 503,
        json: { detail: "Local API is temporarily unavailable." },
      });
    else await route.continue();
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText(
    "Local API is temporarily unavailable.",
  );
  await expect(page.locator(".recovery-record")).toContainText(
    "Not established.",
  );
  await page.screenshot({
    path: "../artifacts/aftertrace/refined/error.png",
    fullPage: true,
  });
  failed = false;
  await page
    .getByRole("button", { name: "Retry connection", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Gone. Or just out of sight?" }),
  ).toBeVisible();
  await expect(page.locator(".workspace-footer .status")).toHaveText(
    "INCOMPLETE",
  );
});

test("empty evidence gets explicit archive, desk and timeline states", async ({
  page,
  request,
}) => {
  const value = (await (
    await request.get("/api/cases/demo_024?mode=demo")
  ).json()) as AuditCase;
  const empty = {
    ...value,
    sources: [],
    events: [],
    identity_nodes: [],
    identity_edges: [],
    context: {
      ...value.context,
      resource_states: [],
      eligible_observation_ids: [],
      excluded_future_observation_ids: [],
      coverage_issues: ["No sources loaded."],
    },
    answer: {
      ...value.answer,
      deletion_status: null,
      ready_for_export: false,
      steps: [],
      blocking_issues: ["No sources loaded."],
    },
  };
  await page.route(/\/api\/cases\/demo_024(?:\?|$)/, (route) =>
    route.fulfill({ json: empty }),
  );
  await open(page);
  await page
    .getByRole("button", { name: "Source nebula", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "The archive is waiting." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Forensic desk", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Choose a source to begin." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Time machine", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No timeline has been established." }),
  ).toBeVisible();
  await page.screenshot({
    path: "../artifacts/aftertrace/refined/empty.png",
    fullPage: true,
  });
});

test("failed parsing remains visibly failed and source inspection remains available", async ({
  page,
  request,
}) => {
  const value = (await (
    await request.get("/api/cases/demo_024?mode=demo")
  ).json()) as AuditCase;
  const failed = {
    ...value,
    sources: value.sources.map((s, i) =>
      i === 0 ? { ...s, parse_status: "failed" } : s,
    ),
    answer: {
      ...value.answer,
      deletion_status: null,
      ready_for_export: false,
      steps: [],
      blocking_issues: ["Source parsing failed."],
    },
  };
  await page.route(/\/api\/cases\/demo_024(?:\?|$)/, (route) =>
    route.fulfill({ json: failed }),
  );
  await open(page);
  await page
    .getByRole("button", { name: "Source nebula", exact: true })
    .click();
  const row = page
    .locator(".manifest-row")
    .filter({ hasText: "file_identity" });
  await expect(row.locator(".status")).toHaveText("failed");
  await row.click();
  await expect(page.getByRole("dialog")).toContainText("file_identity");
});

test("laptop and mobile layouts keep every chapter usable without horizontal overflow", async ({
  page,
}) => {
  const scenes = [
    "The portal",
    "Source nebula",
    "Identity constellation",
    "Forensic desk",
    "Time machine",
    "Decision chamber",
    "Audit folio",
    "Experiment observatory",
  ];
  await page.setViewportSize({ width: 1366, height: 768 });
  await open(page);
  for (const name of scenes) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.locator("main h1")).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(1366);
    if (
      [
        "The portal",
        "Identity constellation",
        "Decision chamber",
        "Source nebula",
      ].includes(name)
    ) {
      await page.mouse.move(900, 150);
      await page.screenshot({
        path: `../artifacts/aftertrace/refined/laptop-${name.toLowerCase().replaceAll(" ", "-")}.png`,
        fullPage: true,
      });
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const name of scenes) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.locator("main h1")).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(390);
  }
  await page
    .getByRole("button", { name: "Identity constellation", exact: true })
    .click();
  await page.screenshot({
    path: "../artifacts/aftertrace/refined/mobile-identity.png",
    fullPage: true,
  });
});

test("native chapter transitions are interruptible and reduced-motion navigation stays direct", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await open(page);
  await page
    .getByRole("button", { name: "Identity constellation", exact: true })
    .click();
  await page.getByRole("button", { name: "Time machine", exact: true }).click();
  await page
    .getByRole("button", { name: "Decision chamber", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Proof before pronouncement." }),
  ).toBeVisible();
  await expect
    .poll(() => page.locator("html").getAttribute("data-scene-motion"))
    .toBeNull();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page
    .getByRole("button", { name: "Identity constellation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "One person. Many versions." }),
  ).toBeVisible();
  expect(
    await page
      .locator(".scene-wrap")
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe("none");
  await page
    .getByRole("button", { name: "Open command palette", exact: true })
    .click();
  const input = page.getByRole("textbox", {
    name: "Search scenes",
    exact: true,
  });
  await expect(input).toBeFocused();
  await input.fill("nothing-matches");
  await expect(page.locator(".palette-empty")).toBeVisible();
  await input.press("Tab");
  await expect(input).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("signature scenes work with WebGL explicitly disabled", async () => {
  const browser = await chromium.launch({ args: ["--disable-webgl"] });
  try {
    const page = await browser.newPage({
      viewport: { width: 1280, height: 800 },
      reducedMotion: "reduce",
    });
    await page.goto("http://127.0.0.1:5173/");
    await expect(
      page.getByRole("heading", { name: "Gone. Or just out of sight?" }),
    ).toBeVisible();
    for (const name of [
      "Identity constellation",
      "Time machine",
      "Decision chamber",
    ]) {
      await page.getByRole("button", { name, exact: true }).click();
      await expect(page.locator("main h1")).toBeVisible();
    }
    await expect(page.locator(".seal-result")).toHaveText("INCOMPLETE");
  } finally {
    await browser.close();
  }
});
