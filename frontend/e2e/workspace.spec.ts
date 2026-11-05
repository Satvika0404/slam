import { test, expect } from "@playwright/test";
test.beforeEach(async ({ page, request }) => {
  await expect
    .poll(async () => (await request.get("/api/health")).ok(), {
      timeout: 15000,
    })
    .toBeTruthy();
  await page.goto("/?legacy=1");
  await expect(
    page.getByRole("heading", { name: "Gone. Or just out of sight?" }),
  ).toBeVisible();
});
test("identity provenance, filters, pan/zoom and node dragging", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Identity constellation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "One person. Many versions." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "historical email historical", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Inspect evidence audit_email_024",
      exact: true,
    })
    .click();
  await expect(page.getByRole("dialog")).toContainText("old_value");
  await expect(page.getByRole("dialog")).toContainText("m.vale@atlas.example");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Zoom identity graph in", exact: true })
    .click();
  await expect(page.locator(".graph-controls")).toContainText("115%");
  await page
    .getByRole("button", { name: "Reset identity view", exact: true })
    .click();
  const node = page.getByRole("button", {
    name: "Inspect email: m.vale@atlas.example",
    exact: true,
  });
  const before = await node.boundingBox();
  await page.mouse.move(
    before!.x + before!.width / 2,
    before!.y + before!.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    before!.x + before!.width / 2 - 40,
    before!.y + before!.height / 2 - 25,
    { steps: 5 },
  );
  await page.mouse.up();
  const after = await node.boundingBox();
  expect(after!.x).toBeLessThan(before!.x - 20);
  await page.getByRole("button", { name: "candidate", exact: true }).click();
  await expect(page.locator(".graph-empty")).toContainText(
    "No candidate relationships",
  );
});
test("cutoff reconstructs the backend result, later evidence remains inspectable", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Time machine", exact: true }).click();
  await expect(page.locator(".workspace-footer .status")).toHaveText(
    "INCOMPLETE",
  );
  await expect(page.locator(".timeline-event.future")).toHaveCount(1);
  await page
    .getByRole("slider", { name: "Audit cutoff time", exact: true })
    .press("End");
  await expect(page.locator(".workspace-footer .status")).toHaveText(
    "COMPLETE",
  );
  await expect(page.locator(".state-snapshot")).toContainText("ABSENT");
  await page
    .getByRole("button", { name: "Decision chamber", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Inspect Verify: PASSED", exact: true })
    .click();
  await expect(page.locator(".stage-description")).toContainText("PASSED");
  await page
    .getByRole("button", {
      name: "Inspect evidence file_primary_02",
      exact: true,
    })
    .click();
  await expect(page.getByRole("dialog")).toContainText("ABSENT");
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Open audit folio", exact: true })
    .click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export case CSV" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("aftertrace-case.csv");
});
test("conflicting evidence prevents COMPLETE certification and preserves the engine's INCOMPLETE output", async ({
  page,
}) => {
  await page
    .getByLabel("Select investigation case", { exact: true })
    .selectOption("demo_026");
  await expect(page.locator(".workspace-footer .status")).toHaveText(
    "INCOMPLETE",
  );
  await page
    .getByRole("button", { name: "Decision chamber", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Inspect Evidence: CONFLICT DETECTED",
      exact: true,
    })
    .click();
  await expect(page.locator(".stage-description")).toContainText(
    "CONFLICT DETECTED",
  );
  await page
    .getByRole("button", { name: "Open audit folio", exact: true })
    .click();
  await expect(page.locator(".folio-blockers")).toContainText(
    "Not certified complete",
  );
  await expect(
    page.getByRole("link", { name: "Export case CSV", exact: true }),
  ).toBeEnabled();
});
test("FTS desk searches actual source content and opens source details", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Forensic desk", exact: true })
    .click();
  await page.getByLabel("Search evidence with FTS5").fill("index_024");
  await page.getByRole("button", { name: "Find traces" }).click();
  await expect(page.locator(".source-explorer>button")).toHaveCount(2);
  await page
    .locator(".source-explorer>button")
    .filter({ hasText: "file_replica_01" })
    .click();
  await expect(page.locator(".document-paper")).toContainText("PRESENT");
  await page.getByRole("button", { name: "Inspect provenance" }).click();
  await expect(page.getByRole("dialog")).toContainText("file_replica_01");
});
test("desktop scenes, mobile layout, reduced motion and presentation controls", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.screenshot({
    path: "../artifacts/aftertrace/portal.png",
    fullPage: true,
  });
  for (const [name, file] of [
    ["Identity constellation", "identity"],
    ["Time machine", "timeline"],
    ["Decision chamber", "decision"],
    ["Source nebula", "sources"],
    ["Forensic desk", "desk"],
    ["Audit folio", "folio"],
    ["Experiment observatory", "observatory"],
  ]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.locator("main h1")).toBeVisible();
    await page.mouse.move(1000, 150);
    await page.screenshot({
      path: `../artifacts/aftertrace/${file}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "Identity constellation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "One person. Many versions." }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(391);
  await page.screenshot({
    path: "../artifacts/aftertrace/mobile-identity.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Present case", exact: true }).click();
  await page.getByRole("button", { name: "Next story scene" }).click();
  await expect(page.locator(".story-bar")).toContainText("Source nebula");
  await page.getByRole("button", { name: "Exit presentation" }).click();
  expect(errors).toEqual([]);
});
test("dataset mode reports missing input instead of substituting demo", async ({
  page,
}) => {
  await page.route("**/api/**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("mode") === "dataset") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Participant dataset is not installed on this server.",
        }),
      });
    } else await route.continue();
  });
  await page.getByLabel("Data mode", { exact: true }).selectOption("dataset");
  await expect(page.getByRole("alert")).toContainText(
    "Participant dataset is not installed",
  );
  await expect(page.getByLabel("Data mode", { exact: true })).toHaveValue(
    "dataset",
  );
});
