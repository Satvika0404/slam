import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import snapshot from "../src/console/snapshot.json" with { type: "json" };
import {
  fromCase,
  graphLayers,
  orphanNodes,
  pythonSnippet,
  removeScenario,
  walk,
  wilson,
} from "../src/console/model";
import type { SystemGraph } from "../src/console/types";
import type { AuditCase } from "../src/types";

async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Intelligence console", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Read the pattern. Anticipate the return.",
    }),
  ).toBeVisible();
}
async function graphTab(page: Page) {
  await page.getByRole("tab", { name: "System graph" }).click();
}
const graph = snapshot.graph as SystemGraph;

test("graph traversal excludes the start node and orders cyclic dependencies through SCCs", () => {
  const a = graph.nodes[0],
    fixture: SystemGraph = {
      nodes: ["a", "b", "c", "d"].map((id) => ({ ...a, id })),
      edges: [
        { ...graph.edges[0], source: "a", target: "b" },
        { ...graph.edges[0], source: "b", target: "a" },
        { ...graph.edges[0], source: "b", target: "c" },
        { ...graph.edges[0], source: "c", target: "d" },
      ],
    };
  expect(walk(fixture, "a")).toEqual(["b", "c", "d"]);
  expect(walk(fixture, "a", true)).toEqual(["b"]);
  const layers = graphLayers(fixture);
  expect(layers.get("a")).toBe(layers.get("b"));
  expect(layers.get("d")).toBe(2);
  const removal = removeScenario(fixture, fixture, ["a", "b", "c", "d"], false);
  expect(removal.order.slice(0, 2)).toEqual(["d", "c"]);
  expect(removal.cyclic).toEqual(["a", "b"]);
});
test("cascade removes only newly orphaned DELETE copies and preserves held and redacted stores", () => {
  const node = graph.nodes[0],
    edge = graph.edges[0];
  const fixture: SystemGraph = {
    nodes: [
      { ...node, id: "source", action: "NONE" },
      { ...node, id: "copy", action: "DELETE" },
      { ...node, id: "held", action: "RETAIN" },
      { ...node, id: "ticket", action: "REDACT" },
      { ...node, id: "old_orphan", action: "DELETE" },
    ],
    edges: ["copy", "held", "ticket", "old_orphan"].map((target) => ({
      ...edge,
      source: "source",
      target,
    })),
  };
  const current = {
    ...fixture,
    edges: fixture.edges.filter((e) => e.target !== "old_orphan"),
  };
  const removal = removeScenario(fixture, current, ["source"], true);
  expect(removal.order).toEqual(["copy", "source"]);
  expect(removal.graph.nodes.map((n) => n.id)).toEqual([
    "held",
    "ticket",
    "old_orphan",
  ]);
  expect(orphanNodes(fixture, removal.graph).map((n) => n.id)).toEqual([
    "held",
    "ticket",
    "old_orphan",
  ]);
  expect(fixture.nodes.length).toBe(5);
});
test("Python export preserves Unicode and every graph attribute without executable input interpolation", () => {
  const fixture = {
    nodes: [
      {
        ...graph.nodes[0],
        label: 'Ålice "quoted" \\ newline\n__import__("os")',
      },
    ],
    edges: [],
  };
  const code = pythonSnippet(fixture);
  const parser = `import ast,json,sys
tree=ast.parse(sys.stdin.buffer.read().decode('utf-8'))
nodes=[];edges=[]
for stmt in tree.body:
 if not isinstance(stmt,ast.Expr) or not isinstance(stmt.value,ast.Call): continue
 call=stmt.value
 if not isinstance(call.func,ast.Attribute): continue
 if call.func.attr=='add_node': nodes.append(dict(id=ast.literal_eval(call.args[0]),**ast.literal_eval(call.keywords[0].value)))
 if call.func.attr=='add_edge': edges.append(dict(source=ast.literal_eval(call.args[0]),target=ast.literal_eval(call.args[1]),**ast.literal_eval(call.keywords[0].value)))
print(json.dumps(dict(nodes=nodes,edges=edges)))`;
  expect(
    JSON.parse(
      execFileSync("python", ["-c", parser], { input: code, encoding: "utf8" }),
    ),
  ).toEqual(fixture);
  expect(
    JSON.parse(
      execFileSync("python", ["-c", parser], {
        input: pythonSnippet(graph),
        encoding: "utf8",
      }),
    ),
  ).toEqual({ nodes: graph.nodes, edges: graph.edges });
  expect(wilson(0, 0)).toBeNull();
  expect(wilson(5, 10)![0]).toBeCloseTo(0.2366, 3);
});
test("all imported patterns, forecasts and citations are inspectable with provenance", async ({
  page,
}) => {
  await open(page);
  await expect(
    page.getByText("14 of 14 supplied patterns", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Monthly reported failure rates", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".intel-estimate>b")).toHaveText("89.4%");
  await page
    .getByRole("combobox", { name: "Operation", exact: true })
    .selectOption("REDACT_RECORD");
  await expect(
    page.getByRole("combobox", { name: "Target system", exact: true }),
  ).toHaveValue("support_platform");
  await page
    .getByRole("button", { name: "Recreation risk", exact: true })
    .click();
  await expect(
    page.getByText("4 of 14 supplied patterns", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).first().click();
  await page
    .getByRole("button", {
      name: "Primary profile deletion not confirmed",
      exact: false,
    })
    .click();
  await page
    .getByRole("button", { name: "Inspect activity_3796", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Imported citation inspector" }),
  ).toContainText("original evidence file or activity row is not included");
  await expect(
    page.getByRole("region", { name: "Imported citation inspector" }),
  ).toContainText("269");
  await page.getByRole("button", { name: "Close imported citation" }).click();
  await page
    .getByRole("searchbox", { name: "Search patterns" })
    .fill("no-such-pattern");
  await expect(
    page.getByText("No patterns match these filters."),
  ).toBeVisible();
});
test("retention filters, assumption slider and hold register use supplied inputs", async ({
  page,
}) => {
  await open(page);
  await page.getByRole("tab", { name: "Retention conflicts" }).click();
  await expect(page.locator(".intel-conflict")).toHaveCount(9);
  await page.getByRole("button", { name: "Low", exact: true }).click();
  await expect(page.locator(".intel-conflict")).toHaveCount(2);
  await page
    .getByRole("combobox", { name: "Conflict category" })
    .selectOption("Exports");
  await expect(
    page.getByText("No register entries match both filters."),
  ).toBeVisible();
  const before = await page
    .locator(".intel-age-row>strong")
    .first()
    .innerText();
  await page.getByRole("slider", { name: "Age threshold in days" }).fill("180");
  await expect(page.locator(".intel-age-control output")).toHaveText(
    "180 days",
  );
  expect(
    await page.locator(".intel-age-row>strong").first().innerText(),
  ).not.toBe(before);
  await expect(
    page.getByText("It is not supplied by deletion_rules.csv", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "04 May 2033", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".intel-policy-grid>div")).toHaveCount(15);
});
test("graph editing is reversible, previews retention conflicts and preserves scenario across tabs", async ({
  page,
}) => {
  await open(page);
  await graphTab(page);
  await expect(page.locator(".intel-map-node")).toHaveCount(22);
  await expect(page.locator(".intel-map-link")).toHaveCount(18);
  await page
    .getByRole("button", { name: "Simulate disable", exact: true })
    .first()
    .click();
  await expect(page.locator(".intel-map-link")).toHaveCount(17);
  await page.getByRole("tab", { name: "Error patterns" }).click();
  await graphTab(page);
  await expect(page.locator(".intel-map-link")).toHaveCount(17);
  await page.getByRole("button", { name: "Time machine", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "The truth has a timestamp." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Intelligence console", exact: true })
    .click();
  await expect(page.locator(".intel-map-link")).toHaveCount(17);
  await page.getByRole("button", { name: "Undo scenario change" }).click();
  await expect(page.locator(".intel-map-link")).toHaveCount(18);
  await page
    .getByRole("checkbox", { name: "Select Archive service", exact: true })
    .check();
  await page.getByRole("button", { name: "Preview removal (1)" }).click();
  await expect(
    page.getByRole("region", { name: "Scenario removal preview" }),
  ).toContainText("Retention conflict");
  await page
    .getByRole("button", { name: "Apply to scenario", exact: true })
    .click();
  await expect(page.locator(".intel-map-node")).toHaveCount(21);
  await expect(page.locator(".intel-graph-log")).toContainText(
    "RETENTION CONFLICT",
  );
  await page.getByRole("button", { name: "Undo scenario change" }).click();
  await expect(page.locator(".intel-map-node")).toHaveCount(22);
  await page
    .getByRole("checkbox", { name: "Select Account service", exact: true })
    .check();
  await page
    .getByRole("checkbox", { name: "Cascade newly orphaned DELETE copies" })
    .check();
  await page.getByRole("button", { name: "Preview removal (1)" }).click();
  await expect(
    page.getByRole("region", { name: "Scenario removal preview" }),
  ).toContainText("account_replication_cluster");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.locator(".intel-map-node")).toHaveCount(22);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download Python" }).click();
  expect((await download).suggestedFilename()).toBe(
    "aftertrace-graph-scenario.py",
  );
  await expect(page.locator(".workspace-footer .status")).toHaveText(
    "INCOMPLETE",
  );
});
test("current investigation never borrows imported counts or forecasts and opens original evidence", async ({
  page,
  request,
}) => {
  const before = (await (
    await request.get("/api/cases/demo_024?mode=demo")
  ).json()) as AuditCase;
  const derived = fromCase(before);
  expect(derived.meta.events).toBe(0);
  expect(derived.rate_fc.fc).toEqual([]);
  expect(derived.graph.edges).toEqual([]);
  await open(page);
  await page
    .getByRole("combobox", { name: "Console analysis source" })
    .selectOption("case");
  await expect(
    page.getByText("Monthly rates and forecasts cannot be computed", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(page.locator(".intel-stats").first()).toContainText(
    "Not measured",
  );
  await graphTab(page);
  await expect(page.locator(".intel-map-node")).toHaveCount(3);
  await expect(page.locator(".intel-map-link")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Inspect system search replica", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Inspect file_replica_01", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("file_replica_01");
  const after = await (
    await request.get("/api/cases/demo_024?mode=demo")
  ).json();
  expect(after.answer).toEqual(before.answer);
});
test("console keyboard navigation and three scenes fit laptop and mobile", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await open(page);
  await page.getByRole("tab", { name: "Error patterns" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "Retention conflicts" }),
  ).toBeFocused();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "System graph" })).toBeFocused();
  for (const size of [
    { width: 1440, height: 1000 },
    { width: 768, height: 1024 },
    { width: 360, height: 800 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(size);
    for (const [name, file] of [
      ["Error patterns", "patterns"],
      ["Retention conflicts", "retention"],
      ["System graph", "graph"],
    ]) {
      await page.getByRole("tab", { name }).click();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `../artifacts/aftertrace/console/${size.width}-${file}.png`,
        fullPage: true,
      });
      if (size.width === 1440 && file === "patterns")
        await page.screenshot({
          path: "../artifacts/aftertrace/console/overview.png",
        });
    }
  }
  expect(errors).toEqual([]);
});
test("imported console remains available if the participant dataset is missing", async ({
  page,
}) => {
  await open(page);
  await page
    .getByRole("combobox", { name: "Data mode" })
    .selectOption("dataset");
  await expect(
    page.getByRole("heading", {
      name: "Read the pattern. Anticipate the return.",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Console analysis source" }),
  ).toHaveValue("snapshot");
  await page.getByRole("tab", { name: "Error patterns" }).click();
  await expect(
    page.getByText("14 of 14 supplied patterns", { exact: false }),
  ).toBeVisible();
});
