import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";

function database(): Buffer {
  return execFileSync("python", [
    "-c",
    `
import sqlite3,tempfile,pathlib,sys
with tempfile.TemporaryDirectory() as root:
 p=pathlib.Path(root)/'source.db'
 with sqlite3.connect(p) as db:
  db.execute('CREATE TABLE customers(id TEXT PRIMARY KEY,email TEXT,name TEXT)')
  db.executemany('INSERT INTO customers VALUES(?,?,?)',[('a','pat@example.test','Pat'),('b','pat@example.test','Pat'),('c','other@example.test','Other')])
  db.execute('CREATE TABLE receipts(id TEXT PRIMARY KEY,email TEXT)')
  db.execute("INSERT INTO receipts VALUES('retained','pat@example.test')")
 db.close()
 sys.stdout.buffer.write(p.read_bytes())
`,
  ]);
}

test("connected database drives full graph, verified removals, recovery and sync experiments", async ({
  page,
}) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  await page
    .getByLabel("Connect SQLite database")
    .setInputFiles({
      name: "customers.db",
      mimeType: "application/octet-stream",
      buffer: database(),
    });
  const dialog = page.getByRole("dialog", { name: "Map database tables" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("receipts action").selectOption("RETAIN");
  await dialog.getByRole("button", { name: "Use mapped snapshot" }).click();
  await expect(dialog).toHaveCount(0);
  await page
    .getByLabel("Deletion request")
    .fill("Please delete all personal data for pat@example.test");
  await page.getByRole("button", { name: "Begin the audit" }).click();
  await expect(
    page.getByRole("heading", { name: "See the change. Keep the proof." }),
  ).toBeVisible();
  const graph = page.locator(".wf-graph-shell");
  await expect(graph.locator('[data-node-kind="system"]')).toHaveCount(2);
  await expect(graph.locator('[data-node-kind="record"]')).toHaveCount(3);
  await graph
    .getByRole("button", { name: "Inspect record customers/a", exact: true })
    .click();
  await expect(page.getByLabel("Record evidence chain")).toContainText(
    "connected_snapshot",
  );
  await page
    .getByLabel("Record evidence chain")
    .getByRole("button", { name: "connected_snapshot" })
    .click();
  await expect(page.getByRole("dialog")).toContainText("customers/a");
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Prepare working copy", exact: true })
    .click();
  await page.screenshot({
    path: "../artifacts/aftertrace/connected-before.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Execute reviewed plan", exact: true })
    .click();
  await expect(
    page.getByText("Execution finished. Evidence recorded.", { exact: true }),
  ).toBeVisible();
  await expect(graph.locator(".intel-map-node.execution-deleted")).toHaveCount(
    2,
  );
  await expect(
    graph.locator(".intel-map-node.execution-deleted").first(),
  ).toHaveCSS("animation-name", "wf-row-delete");
  await expect(
    graph.getByRole("button", {
      name: "Inspect record receipts/retained",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    graph.getByRole("button", {
      name: "Inspect system customers",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("Show deleted nodes in graph history").check();
  await expect(graph.locator(".intel-map-node.execution-ended")).toHaveCount(2);
  await expect(
    graph.getByRole("button", {
      name: "Inspect record customers/a",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("Show deleted nodes in graph history").uncheck();
  await page.getByRole("button", { name: "Before", exact: true }).click();
  await expect(graph.locator(".intel-map-node.execution-deleted")).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Latest state", exact: true }).click();
  await expect(graph.locator(".intel-map-node.execution-deleted")).toHaveCount(
    2,
  );
  await page
    .getByRole("button", { name: "sync experiment", exact: true })
    .click();
  await page.getByLabel("Sync experiment row").selectOption({ index: 1 });
  await page
    .getByRole("button", { name: "Run sync again", exact: true })
    .click();
  await expect(page.locator(".wf-sync-branches .recreated")).toContainText(
    "Row recreated",
  );
  await expect(page.locator(".wf-sync-branches .protected")).toContainText(
    "Row remains absent",
  );
  await page.screenshot({
    path: "../artifacts/aftertrace/connected-sync.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "self-healing", exact: true }).click();
  await page
    .getByRole("button", { name: "Test recovery", exact: true })
    .click();
  await expect(page.locator(".wf-healing-arm")).toHaveClass(/recovered/);
  await expect(page.locator(".wf-recovery-result")).toContainText("6/6 checks");
  await page.screenshot({
    path: "../artifacts/aftertrace/connected-recovery.png",
    fullPage: true,
  });
  await page
    .getByLabel("Recovery CSV input")
    .fill("email,email,resource_id\na,b,r1\n");
  await page
    .getByRole("button", { name: "Test recovery", exact: true })
    .click();
  await expect(page.locator(".wf-healing-arm")).toHaveClass(/unresolved/);
  await expect(page.locator(".wf-recovery-result")).toContainText("blocked");
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  }
  expect(errors).toEqual([]);
});
