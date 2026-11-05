import { lazy, Suspense } from "react";
import Workflow from "./workflow/Workflow";

// Archived scenes stay available in development for renderer regression checks.
// Production always opens the single-input workflow.
const Legacy = lazy(() => import("./LegacyApp"));
export default function App() {
  const archived =
    import.meta.env.DEV && new URLSearchParams(location.search).has("legacy");
  return archived ? (
    <Suspense fallback={<p>Loading archived workspace…</p>}>
      <Legacy />
    </Suspense>
  ) : (
    <Workflow />
  );
}
