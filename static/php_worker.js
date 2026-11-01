/* The Web Worker a PHP site runs in (php.js starts it; php_core.js is the
 * PHP side of it).
 *
 * A worker and not the page's own thread, because PHP compiled to
 * WebAssembly cannot be interrupted: `while (true) {}` in a student's page
 * never returns, and PHP's own max_execution_time needs a timer signal that
 * WebAssembly does not have. On the page's thread that froze the whole
 * editor, Stop button included. In a worker it freezes only the worker, and
 * php.js ends it after a time limit and starts another.
 *
 * PHP is loaded from jsDelivr, as Pyodide is for Flask projects: about
 * 20 MB the first time, cached by the browser after. It is WordPress
 * Playground's build (GPL), used unmodified and never copied into this
 * repository.
 */
import { makeCore } from "./php_core.js";

const V = "3.1.61";
const CDN = "https://cdn.jsdelivr.net/npm/";

let core = null;

async function getCore() {
  if (core) return core;
  const { PHP, PHPRequestHandler, setPhpIniEntries } = await import(CDN + "@php-wasm/universal@" + V + "/+esm");
  const { loadWebRuntime } = await import(CDN + "@php-wasm/web@" + V + "/+esm");
  core = makeCore({ PHP, PHPRequestHandler, setPhpIniEntries, load: () => loadWebRuntime("8.4") });
  return core;
}

self.onmessage = async (e) => {
  const { id, op, args } = e.data || {};
  try {
    const c = await getCore();
    const result = await c[op](args || {});
    self.postMessage({ id, ok: true, result });
  } catch (err) {
    self.postMessage({ id, ok: false, error: String((err && err.message) || err) });
  }
};
