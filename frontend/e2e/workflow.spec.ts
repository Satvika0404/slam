import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";

function fixtureZip(): Buffer {
  const head =
    "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text\n";
  const tables: Record<string, string> = {
    "deletion_requests.csv":
      head +
      [
        "request_active,pat@example.test,2026-10-01T00:00:00Z,COMPLETE,2026-10-02T00:00:00Z,2026-10-04T00:00:00Z,Please delete my account.",
        "request_complete,lee@example.test,2026-10-01T00:00:00Z,COMPLETE,2026-10-02T00:00:00Z,2026-10-04T00:00:00Z,Please delete my account.",
        "request_access,sam@example.test,2026-10-01T00:00:00Z,COMPLETE,2026-10-02T00:00:00Z,2026-10-04T00:00:00Z,Please export my data.",
      ].join("\n") +
      "\n",
    "user_identities.csv":
      "user_id,name,email,phone,email_hash,updated_at\n" +
      [
        "user_1,Pat Example,pat@example.test,+155501001",
        "user_2,Lee Example,lee@example.test,+155501002",
        "user_3,Sam Example,sam@example.test,+155501003",
      ]
        .map((r, i) => `${r},${String(i + 1).repeat(64)},2026-10-01T00:00:00Z`)
        .join("\n") +
      "\n",
    "user_audit_log.csv":
      "audit_id,user_id,event_time,field_name,old_value,new_value\n",
    "system_activity.csv":
      "activity_id,event_time,event_type,source_system,target_system,resource_id,reported_result,details\n",
    "deletion_rules.csv":
      "rule_id,data_category,condition,required_action\nr1,USER_PROFILE,Always,DELETE\nr2,SEARCH_INDEX_ENTRY,Always,DELETE\nr3,DATA_FLOW,Always,RETAIN\nr4,BACKUP_ARCHIVE,Always,RETAIN\nr5,SUPPORT_MESSAGE,Shared context,REDACT\nr6,SECURITY_AUDIT_LOG,Within retention,RETAIN\n",
    "evidence_files.csv":
      "file_id,file_path,origin,captured_at\nfile_live,evidence/records.json,fixture_readback,2026-10-03T00:00:00Z\n",
  };
  const records = [
    ["account_1", "USER_PROFILE", "account_service", "PRESENT"],
    ["search_1", "SEARCH_INDEX_ENTRY", "search_service", "PRESENT"],
    ["data_flow_1", "DATA_FLOW", "integration_service", "ACTIVE"],
    ["backup_1", "BACKUP_ARCHIVE", "backup_service", "RESTORABLE"],
    ["support_1", "SUPPORT_MESSAGE", "support_platform", "IDENTIFIABLE"],
    ["audit_record_1", "SECURITY_AUDIT_LOG", "security_service", "PRESENT"],
  ].map(([resource_id, record_type, system, result]) => ({
    resource_id,
    record_type,
    system,
    result,
    recorded_at: "2026-10-03T00:00:00Z",
    user_id: "user_1",
    email: "pat@example.test",
    ...(record_type === "DATA_FLOW"
      ? { target_system: "search_service", target_resource_id: "search_1" }
      : {}),
    ...(record_type === "BACKUP_ARCHIVE"
      ? { target_system: "account_service", target_resource_id: "account_1" }
      : {}),
  }));
  records.push({
    resource_id: "account_2",
    record_type: "USER_PROFILE",
    system: "account_service",
    result: "ABSENT",
    recorded_at: "2026-10-03T00:00:00Z",
    user_id: "user_2",
    email: "lee@example.test",
  });
  records.push({
    resource_id: "account_3",
    record_type: "USER_PROFILE",
    system: "account_service",
    result: "PRESENT",
    recorded_at: "2026-10-03T00:00:00Z",
    user_id: "user_3",
    email: "sam@example.test",
  });
  tables["evidence/records.json"] = JSON.stringify({ records });
  return execFileSync(
    "python",
    [
      "-c",
      "import io,json,sys,zipfile; d=json.load(sys.stdin); b=io.BytesIO(); z=zipfile.ZipFile(b,'w'); [z.writestr('dataset/'+k,v) for k,v in d.items()]; z.close(); sys.stdout.buffer.write(b.getvalue())",
    ],
    { input: JSON.stringify(tables) },
  );
}

async function loadRun(page: Page) {
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "One dataset. Every trace. Accounted for.",
    }),
  ).toBeVisible();
  await page.getByLabel("Upload dataset ZIP").setInputFiles({
    name: "fictional-workflow.zip",
    mimeType: "application/zip",
    buffer: fixtureZip(),
  });
  await expect(
    page.getByRole("button", { name: "Begin the audit" }),
  ).toBeEnabled();
  await expect(
    page.getByText("Uploaded dataset", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Begin the audit" }).click();
  await expect(
    page.getByRole("heading", { name: "See the change. Keep the proof." }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByText("pat@example.test", { exact: true }).first(),
  ).toBeVisible();
}

test("one input flows through audit, real deletion, graph history and final evidence", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  mkdirSync("../artifacts/aftertrace", { recursive: true });
  await loadRun(page);
  await expect(
    page
      .getByRole("navigation", { name: "Audit workflow" })
      .getByRole("button"),
  ).toHaveCount(4);
  await expect(page.getByLabel("Data mode")).toHaveCount(0);
  await expect(
    page.getByText("Imported console snapshot", { exact: true }),
  ).toHaveCount(0);
  const runId = await page.evaluate(() =>
    sessionStorage.getItem("aftertrace.workflow.run"),
  );
  const original = await (
    await request.get(`/api/workflow/runs/${runId}/export`)
  ).text();
  await expect(page.locator('[data-resource-id="account_1"]')).toHaveAttribute(
    "data-state",
    "PRESENT",
  );
  await page.screenshot({
    path: "../artifacts/aftertrace/workflow-before.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Prepare working copy", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Execute reviewed plan", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Execute reviewed plan", exact: true })
    .click();
  await expect(
    page.getByText("Execution finished. Evidence recorded.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continue to final report" }).click();
  await expect(
    page.getByRole("heading", { name: "Verified in the working copy." }),
  ).toBeVisible();
  await page.screenshot({
    path: "../artifacts/aftertrace/workflow-result.png",
    fullPage: true,
  });
  expect(
    await (await request.get(`/api/workflow/runs/${runId}/export`)).text(),
  ).toBe(original);
  await page.getByRole("button", { name: "Return to the graph" }).click();
  await expect(page.locator('[data-resource-id="account_1"]')).toHaveAttribute(
    "data-state",
    "ABSENT",
  );
  await expect(page.locator('[data-resource-id="search_1"]')).toHaveAttribute(
    "data-state",
    "ABSENT",
  );
  await expect(
    page.locator('[data-resource-id="audit_record_1"]'),
  ).toHaveAttribute("data-state", "PRESENT");
  await expect(page.locator(".intel-map-link.execution-ended")).toHaveCount(2);
  await page
    .locator('[data-resource-id="account_1"]')
    .getByRole("button")
    .click();
  await expect(page.getByRole("dialog")).toContainText('"verified": true');
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Before", exact: true }).click();
  await expect(page.locator('[data-resource-id="account_1"]')).toHaveAttribute(
    "data-state",
    "PRESENT",
  );
  await page.getByRole("button", { name: "Latest state", exact: true }).click();
  await expect(page.locator('[data-resource-id="account_1"]')).toHaveAttribute(
    "data-state",
    "ABSENT",
  );
  await page.getByRole("button", { name: "Replay recorded changes" }).click();
  await expect(
    page.getByText("RECORDED PLAYBACK", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Pause recorded playback" }).click();
  await page.getByRole("button", { name: "Latest state", exact: true }).click();
  await page.screenshot({
    path: "../artifacts/aftertrace/workflow-graph-after.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: /request_access/ }).click();
  await expect(
    page.getByText("This request does not authorize deletion.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Execute reviewed plan" }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("late local input cannot replace an uploaded dataset", async ({
  page,
}) => {
  await page.route("**/api/workflow/input", async (route) => {
    if (route.request().method() === "GET")
      await new Promise((resolve) => setTimeout(resolve, 700));
    await route.continue();
  });
  await loadRun(page);
  await expect(page.locator(".wf-run-ribbon")).toContainText("3 requests");
  await expect(page.locator(".wf-run-ribbon")).toContainText(
    "Uploaded dataset",
  );
});

test("verified graph motion respects reduced motion and working copies survive reload", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await loadRun(page);
  await page
    .getByRole("button", { name: "Prepare working copy", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Execute reviewed plan", exact: true })
    .click();
  await expect(
    page.getByText("Execution finished. Evidence recorded.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".intel-map-link.execution-ended").first(),
  ).toHaveCSS("animation-name", "wf-connection-end");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(
    page.locator(".intel-map-link.execution-ended").first(),
  ).toHaveCSS("animation-name", "none");
  await page.reload();
  await expect(
    page.getByText("Execution finished. Evidence recorded.", { exact: true }),
  ).toBeVisible();
  await expect(page.locator('[data-resource-id="account_1"]')).toHaveAttribute(
    "data-state",
    "ABSENT",
  );
});

test("workflow layout and evidence stay usable at laptop and mobile widths", async ({
  page,
}) => {
  test.setTimeout(90000);
  await loadRun(page);
  for (const width of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await expect(
      page.getByRole("button", { name: "Prepare working copy", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `../artifacts/aftertrace/workflow-${width}.png`,
      fullPage: true,
    });
  }
  await page
    .getByRole("navigation", { name: "Audit workflow" })
    .getByRole("button", { name: "Audit", exact: true })
    .click();
  await page.getByRole("button", { name: "evidence", exact: true }).click();
  await page.locator(".wf-source-browser").getByRole("button").first().click();
  await expect(page.getByRole("dialog")).toContainText("file_live");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "identity", exact: true }).click();
  await expect(page.getByLabel("Exact identifier search")).toBeVisible();
});

test("input errors are recoverable and do not relabel old evidence", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Upload dataset ZIP").setInputFiles({
    name: "bad.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("not a zip"),
  });
  await expect(page.getByRole("alert")).toContainText("Upload a ZIP");
  await page.getByRole("button", { name: "Dismiss error" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(
    page.getByRole("heading", {
      name: "One dataset. Every trace. Accounted for.",
    }),
  ).toBeVisible();
});
