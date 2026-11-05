import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { AuditCase, IdentityEdge } from "../src/types";
import {
  edgeStatus,
  validateEdge,
  layoutIdentity,
  shortestPath,
} from "../src/identity/model";
import { consumeExecution } from "../src/live";

async function openIdentity(page: Page) {
  await page.goto("/?legacy=1");
  await page
    .getByRole("button", { name: "Identity constellation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "One person. Many versions." }),
  ).toBeVisible();
}
const at = "2026-10-21T13:30:00Z";
const base: IdentityEdge = {
  id: "edge",
  source: "a",
  target: "b",
  relationship: "current_email",
  state: "verified",
  evidence_ids: ["proof"],
  valid_from: "2026-10-21T08:00:00Z",
  valid_to: null,
  evidence: [
    {
      source_id: "proof",
      captured_at: "2026-10-21T08:00:00Z",
      origin: "Identity directory",
      locator: "row 1",
      eligible: true,
    },
  ],
};
test("relationship colour states require evidence and valid lifecycle events", () => {
  expect(edgeStatus(base, at)).toBe("verified");
  expect(edgeStatus({ ...base, verification_state: "confirmed" }, at)).toBe(
    "confirmed",
  );
  expect(
    edgeStatus(
      { ...base, state: "candidate", verification_state: "candidate" },
      at,
    ),
  ).toBe("candidate");
  expect(
    edgeStatus(
      {
        ...base,
        verification_state: "conflict",
        conflicting_evidence_ids: ["proof"],
      },
      at,
    ),
  ).toBe("conflict");
  expect(edgeStatus({ ...base, valid_to: "2026-10-21T09:00:00Z" }, at)).toBe(
    "ended",
  );
  for (const kind of ["deleted", "removed"] as const)
    expect(
      edgeStatus(
        {
          ...base,
          lifecycle_event: {
            kind,
            at: "2026-10-21T09:00:00Z",
            evidence_ids: ["proof"],
          },
        },
        at,
      ),
    ).toBe(kind);
  expect(
    edgeStatus(
      { ...base, state: "deleted", evidence_ids: [], evidence: [] },
      at,
    ),
  ).toBe("unknown");
  expect(
    edgeStatus(
      {
        ...base,
        lifecycle_event: {
          kind: "deleted",
          at: "2026-10-21T09:00:00Z",
          evidence_ids: ["missing"],
        },
      },
      at,
    ),
  ).toBe("verified");
  expect(
    edgeStatus(
      {
        ...base,
        evidence: [
          {
            ...base.evidence![0],
            captured_at: "2026-10-22T00:00:00Z",
            eligible: false,
          },
        ],
      },
      at,
    ),
  ).toBe("future");
  expect(
    validateEdge({ ...base, target: "missing" }, new Set(["a", "b"])),
  ).toContain("endpoint");
  expect(
    validateEdge({ ...base, valid_to: "yesterday" }, new Set(["a", "b"])),
  ).toContain("timestamp");
});
test("original anchors remain stable and paths handle cycles without fabricating links", () => {
  const small = [
    { id: "a", label: "a", kind: "subject" },
    { id: "b", label: "b", kind: "email" },
  ];
  const bigger = [
    ...small,
    ...Array.from({ length: 60 }, (_, i) => ({
      id: `z${String(i).padStart(3, "0")}`,
      label: `z${i}`,
      kind: "resource",
    })),
  ];
  expect(layoutIdentity(small).a).toEqual(layoutIdentity(bigger).a);
  expect(
    new Set(Object.values(layoutIdentity(bigger)).map((v) => v.join(","))).size,
  ).toBe(bigger.length);
  const edges = [
    base,
    { ...base, id: "bc", source: "b", target: "c" },
    { ...base, id: "ca", source: "c", target: "a" },
  ];
  expect([...shortestPath(edges, "a", "c").edges]).toEqual(["ca"]);
  expect(shortestPath(edges, "a", "missing").nodes.size).toBe(0);
});
test("stream parser handles split frames and never invents completion after disconnect", async () => {
  const text =
    'event: execution\ndata: {"event":"stage.started","payload":{"stage":"identity"}}\n\nevent: execution\ndata: {"event":"run.completed","payload":{"processed":1}}\n\n';
  const encoder = new TextEncoder(),
    events: string[] = [];
  const bytes = encoder.encode(text);
  await consumeExecution(
    new Response(
      new ReadableStream({
        start(c) {
          for (let i = 0; i < bytes.length; i += 7)
            c.enqueue(bytes.slice(i, i + 7));
          c.close();
        },
      }),
    ),
    (e) => events.push(e.event),
  );
  expect(events).toEqual(["stage.started", "run.completed"]);
  await expect(
    consumeExecution(
      new Response('data: {"event":"stage.started","payload":{}}\n\n'),
      () => {},
    ),
  ).rejects.toThrow("before a terminal backend event");
});
test("existing identity renderer selects exact connections, endpoints, history and evidence", async ({
  page,
}) => {
  await openIdentity(page);
  await expect(page.locator(".identity-scene")).toHaveCSS(
    "background-color",
    "rgb(243, 246, 248)",
  );
  await page
    .getByRole("button", { name: "Current relationships", exact: true })
    .click();
  await expect(page.locator(".identity-edge.ended")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Historical relationships", exact: true })
    .click();
  await expect(page.locator(".identity-edge.ended")).not.toHaveCount(0);
  const hit = page.locator(".identity-edge.ended .edge-hit").first();
  await hit.scrollIntoViewIfNeeded();
  const point = await hit.evaluate((element) => {
    const p = element as SVGPathElement;
    const middle = p.getPointAtLength(p.getTotalLength() / 2);
    const screen = new DOMPoint(middle.x, middle.y).matrixTransform(
      p.getScreenCTM()!,
    );
    return { x: screen.x, y: screen.y };
  });
  await page.mouse.click(point.x, point.y);
  await expect(page.locator(".identity-edge.focused")).toHaveCount(1);
  await expect(page.locator(".edge-endpoint-selected")).toHaveCount(2);
  await expect(page.locator(".identity-inspector")).toContainText("ENDED");
  await expect(page.locator(".identity-inspector")).toContainText(
    "21 Oct 2026",
  );
  await page
    .getByRole("button", {
      name: "Inspect evidence audit_email_024",
      exact: true,
    })
    .click();
  await expect(page.getByRole("dialog")).toContainText("old_value");
  await page.keyboard.press("Escape");
  await expect(page.locator(".identity-edge.focused")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(page.locator(".identity-edge.focused")).toHaveCount(0);
  await page
    .getByRole("textbox", { name: "Exact identifier search" })
    .fill("m.vale@atlas.example");
  await page.getByRole("button", { name: "Find exact", exact: true }).click();
  await expect(page.locator(".identity-feedback")).toContainText("Exact match");
  await page
    .getByRole("textbox", { name: "Exact identifier search" })
    .fill("m.vale");
  await page.getByRole("button", { name: "Find exact", exact: true }).click();
  await expect(page.locator(".identity-feedback")).toContainText(
    "No exact identifier match",
  );
  await page
    .getByRole("combobox", { name: "Filter identity node type" })
    .selectOption("hash");
  await expect(page.locator(".node-kind-hash")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Fit identity graph to screen" })
    .click();
  await expect(page.locator(".graph-world")).not.toHaveAttribute(
    "style",
    /NaN/,
  );
});
test("deleted and conflicting relationships remain distinct from entity deletion in history", async ({
  page,
  request,
}) => {
  const value = (await (
    await request.get("/api/cases/demo_024")
  ).json()) as AuditCase;
  const n = value.identity_nodes[0],
    e = value.identity_edges[0];
  const fixture = {
    ...value,
    identity_nodes: value.identity_nodes.map((x) =>
      x.id === n.id
        ? {
            ...x,
            entity_state: "DELETED",
            entity_event_at: "2026-10-21T12:00:00Z",
            entity_evidence_ids: e.evidence_ids,
          }
        : x,
    ),
    identity_edges: [
      ...value.identity_edges,
      {
        ...e,
        id: "fixture_deleted",
        valid_to: "2026-10-21T12:00:00Z",
        lifecycle_event: {
          kind: "deleted",
          at: "2026-10-21T12:00:00Z",
          evidence_ids: e.evidence_ids,
          reason: "Explicit test deletion event",
        },
      },
      {
        ...e,
        id: "fixture_conflict",
        verification_state: "conflict",
        conflicting_evidence_ids: e.evidence_ids,
      },
      { ...e, id: "invalid", target: "missing-node" },
    ],
  };
  await page.route(/\/api\/cases\/demo_024(?:\?|$)/, (r) =>
    r.fulfill({ json: fixture }),
  );
  await openIdentity(page);
  await expect(
    page.getByText("1 invalid relationships excluded", { exact: false }),
  ).toBeVisible();
  await page.locator('[data-edge-id="fixture_deleted"]').focus();
  await page.locator('[data-edge-id="fixture_deleted"]').press("Enter");
  await expect(page.locator(".identity-inspector")).toContainText(
    "Explicit test deletion event",
  );
  await page
    .getByRole("button", { name: "Current relationships", exact: true })
    .click();
  await expect(page.locator('[data-edge-id="fixture_deleted"]')).toHaveCount(0);
  await page.locator('[data-edge-id="fixture_conflict"]').focus();
  await page.locator('[data-edge-id="fixture_conflict"]').press("Enter");
  await expect(page.locator(".identity-conflict-proof")).toContainText(
    "CONFLICTING OBSERVATIONS",
  );
  await page
    .getByRole("button", { name: `Inspect ${n.kind}: ${n.label}`, exact: true })
    .click();
  await expect(page.locator(".identity-entity-state")).toContainText(
    "ENTITY DELETED",
  );
});
test("large graphs expand progressively, stay stable and fit mobile layouts", async ({
  page,
  request,
}) => {
  const value = (await (
    await request.get("/api/cases/demo_024")
  ).json()) as AuditCase;
  const root = value.context.subject_id!,
    edge = value.identity_edges[0];
  const nodes = Array.from({ length: 150 }, (_, i) => ({
    id: `large_${i}`,
    label: `person_${i}@example.test`,
    kind: "email",
  }));
  const fixture = {
    ...value,
    identity_nodes: [value.identity_nodes.find((n) => n.id === root), ...nodes],
    identity_edges: nodes.map((n, i) => ({
      ...edge,
      id: `large_edge_${i}`,
      source: root,
      target: n.id,
      state: "verified",
      valid_to: null,
      lifecycle_event: null,
      system_ids: [i % 2 ? "crm" : "support"],
    })),
  };
  await page.route(/\/api\/cases\/demo_024(?:\?|$)/, (r) =>
    r.fulfill({ json: fixture }),
  );
  await openIdentity(page);
  await expect(page.locator(".identity-node")).toHaveCount(40);
  const firstStyle = await page
    .locator('[data-node-id="large_0"]')
    .getAttribute("style");
  await page.getByRole("button", { name: "Show next 40 identifiers" }).click();
  await expect(page.locator(".identity-node")).toHaveCount(80);
  expect(
    await page.locator('[data-node-id="large_0"]').getAttribute("style"),
  ).toBe(firstStyle);
  await page
    .getByRole("combobox", { name: "Filter identity system" })
    .selectOption("crm");
  await page
    .getByRole("button", { name: "Fit identity graph to screen" })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
});
test("live backend execution automatically advances and displays actual output and graph snapshots", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/?legacy=1");
  await page
    .getByRole("button", { name: "Live backend execution", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Run backend audit", exact: true })
    .click();
  await expect(page.locator(".run-final")).toContainText("1 processed", {
    timeout: 20000,
  });
  await expect(page.locator(".run-answer h3")).toHaveText("INCOMPLETE");
  await expect(page.locator(".run-journal")).toContainText("stage.completed");
  await expect(
    page.getByText("No model calls were made.", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Resolve identity Exact", exact: false })
    .click();
  await expect(
    page.locator(".run-stage-content .identity-edge"),
  ).not.toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Analyse dependencies NetworkX",
      exact: false,
    })
    .click();
  await expect(page.locator(".live-graph-readonly")).toContainText(
    "BACKEND DEPENDENCY SNAPSHOT",
  );
  await page
    .getByRole("button", { name: "Follow live phase", exact: true })
    .click();
  await expect(page.locator(".run-answer h3")).toHaveText("INCOMPLETE");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download validated CSV" }).click();
  expect((await download).suggestedFilename()).toBe("aftertrace-case.csv");
  await page.screenshot({
    path: "../artifacts/aftertrace/live-execution.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
test("batch evidence inspection uses the executed case and folio downloads the validated run output", async ({
  page,
}) => {
  await page.goto("/?legacy=1");
  await page
    .getByRole("button", { name: "Live backend execution", exact: true })
    .click();
  await page.getByLabel("Run scope", { exact: true }).selectOption("all");
  await page
    .getByRole("button", { name: "Run backend audit", exact: true })
    .click();
  await expect(page.locator(".run-final")).toContainText("3 processed", {
    timeout: 20000,
  });
  await page
    .getByRole("button", {
      name: "Reconstruct state Audit cutoff",
      exact: false,
    })
    .click();
  const evidence = page.locator(".run-resource-table button").first();
  await evidence.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const sourceLink = page.getByRole("link", {
    name: /Open original source|Open structured record/,
  });
  await expect(sourceLink).toHaveAttribute("href", /case_id=demo_026/);
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Follow live phase", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Open evidence-backed audit folio",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("link", { name: "Export case CSV", exact: true }),
  ).toHaveAttribute("href", /^data:text\/csv/);
});
test("preserved original HTML keeps its SVG, handlers, historical scenario and undo", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/reference/ghost-data-console.html?embed=graph#graph");
  await expect(page.locator("#gsvg .gn")).toHaveCount(22);
  await expect(page.locator(".at-connection")).toHaveCount(18);
  await page.locator(".at-connection").first().click();
  await expect(page.locator(".at-inspector")).toContainText(
    "UNVERIFIED SNAPSHOT ASSOCIATION",
  );
  await page
    .getByRole("button", { name: "Clear connection selection" })
    .click();
  await page.locator('[data-node="account_service"]').click();
  await page
    .locator('[data-cut="account_service|account_replication_cluster"]')
    .click();
  await expect(page.locator(".at-connection")).toHaveCount(17);
  await page
    .getByRole("button", { name: "Historical scenario", exact: true })
    .click();
  await expect(page.locator(".at-connection.at-removed")).toHaveCount(1);
  await page.locator(".at-connection.at-removed").focus();
  await page.locator(".at-connection.at-removed").press("Enter");
  await expect(page.locator(".at-inspector")).toContainText(
    "No observed ending/deletion timestamp",
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".at-connection.at-removed")).toHaveCount(0);
  expect(errors).toEqual([]);
});
