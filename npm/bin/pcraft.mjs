#!/usr/bin/env node
/**
 * pcraft -- the Node launcher for the `prompt-crafter` Python toolkit.
 *
 * WHY A LAUNCHER AND NOT A PORT. The measured pieces here are Python: the contract
 * schema, the fail-closed loader, the gate's tiering and its four-way exit contract.
 * Re-implementing any of them in Node would create a second copy of a threshold, and a
 * threshold with two copies is a threshold that drifts -- precisely the failure this
 * project exists to catch. So this package installs a command and forwards it, verbatim,
 * to the Python that holds the truth.
 *
 * WHAT IT WILL NOT DO. It does not install Python, does not pip-install anything behind
 * your back, and does not guess at a substitute when the toolkit is absent. A launcher
 * that silently installed things would turn `npx` into a package manager aimed at your
 * machine. When the toolkit is missing it says so, prints the one command that fixes it,
 * and exits non-zero.
 *
 * THE EXIT CODE IS THE POINT. The gate distinguishes "a required claim failed" (2) from
 * "I could not check" (4), and a launcher that flattened those would undo the whole
 * design one layer up. The child's code is inherited unchanged.
 *
 * NOTHING IS IMPORTED AT THE TOP OF THIS FILE, and that is deliberate (F-32b0166f). ESM
 * resolves every static `import` before the first statement of the body runs, so
 * `import ... from "node:child_process"` on a Node too old for the `node:` protocol
 * (unflagged from 14.18) killed the process in module resolution -- with a raw resolution
 * error, before locate(), before fail(), before any of the clean-failure machinery this
 * file otherwise guarantees for every missing-dependency case. The version check below has
 * to run first, so child_process is loaded dynamically, further down, once it is safe.
 */

const PYPI = "prompt-crafter";
const IMPORT_NAME = "pcraft";
const DOCS = "https://mcp-tool-shop-org.github.io/prompt-craft/";

/**
 * The oldest Node this FILE can run on, which is NOT the same question as the supported
 * range. package.json declares `engines: >=18` -- the version this package is tested and
 * supported on, and the LTS floor. This constant is the hard floor underneath it: 14.18 is
 * where `node:` protocol imports became unflagged, and nothing here needs anything newer.
 *
 * Calibrating the runtime guard to `engines` instead would REJECT installs that work today
 * -- npm's engine range is a warning by default (`engine-strict` is off), so a 14.18-17.x
 * user currently runs this launcher fine, and a guard that mirrored the declared value
 * would break them to enforce a support policy rather than a technical requirement.
 * `tests/test_amend_cli.py::test_the_launchers_hard_floor_is_calibrated_to_the_code_not_to_engines`
 * pins both directions: at or above the `node:` floor, at or below the declared engines.
 */
const MIN_NODE = [14, 18, 0];

function nodeVersion() {
  const raw =
    process.versions && process.versions.node ? String(process.versions.node) : "0.0.0";
  const parts = raw.split(".").map(function (part) {
    const n = parseInt(part, 10);
    return isNaN(n) ? 0 : n;
  });
  return [parts[0] || 0, parts[1] || 0, parts[2] || 0];
}

function nodeIsTooOld() {
  const have = nodeVersion();
  for (let i = 0; i < 3; i++) {
    if (have[i] > MIN_NODE[i]) return false;
    if (have[i] < MIN_NODE[i]) return true;
  }
  return false;
}

const FLOOR = MIN_NODE.join(".");

if (nodeIsTooOld()) {
  process.stderr.write(
    "pcraft: this launcher needs Node " +
      FLOOR +
      " or newer; this one is " +
      nodeVersion().join(".") +
      ".\n\n" +
      "  Below " +
      FLOOR +
      " the `node:` imports this file uses do not resolve, so it would die\n" +
      "  in module resolution before it could tell you anything useful.\n\n" +
      "  The published package supports Node >=18. This is the hard floor underneath that.\n" +
      "  Docs: " +
      DOCS +
      "\n"
  );
  process.exit(127);
}

/** Interpreter candidates, in the order worth trying on each platform. */
function candidates() {
  const fromEnv = process.env.PCRAFT_PYTHON;
  const list = fromEnv ? [fromEnv] : [];
  // `py -3` is the Windows launcher and resolves when `python3` is only the Store stub.
  return process.platform === "win32"
    ? [...list, "python", "py", "python3"]
    : [...list, "python3", "python"];
}

/** Args that turn a bare candidate into a working interpreter invocation. */
function argsFor(exe) {
  return exe === "py" ? ["-3"] : [];
}

/**
 * PCRAFT_PYTHON was set, and it cannot serve. Say so and stop.
 *
 * This REFUSES rather than moving on to the next candidate, which is the whole fix
 * (F-d7c0c054). Every failure reason -- not on PATH, wrong permissions, a real interpreter
 * whose venv was just rebuilt and not yet reinstalled -- used to take the same silent
 * `continue`, so locate() quietly fell through to PATH. Measured end to end:
 * `PCRAFT_PYTHON=C:/definitely/not/a/real/path/python.exe node bin/pcraft.mjs --version`
 * exited 0 and printed an ordinary version banner, with nothing anywhere saying the
 * configured interpreter had been rejected or that a different one answered.
 *
 * npm/README.md aims this variable at people who "keep several" interpreters -- exactly the
 * population with another pcraft on PATH ready to absorb the mistake, at a different
 * version with different pins. `bind --no-mock` spends real GPU/Cloud money on the
 * assumption that the interpreter you configured is the one running. An explicit setting
 * that is wrong is a stop, not a hint.
 *
 * The two reasons stay distinguished, per this module's own doctrine: "an interpreter that
 * exists but lacks the package is a DIFFERENT problem from no interpreter at all."
 */
function refuseConfigured(configured, ran, detail) {
  const why = ran
    ? "it could not import the toolkit"
    : "nothing could be started from that path";
  const remedy = ran
    ? "  That interpreter exists; the toolkit is not installed in it:\n\n" +
      "      " +
      configured +
      " -m pip install " +
      PYPI +
      "\n\n"
    : "  Check the path, or unset PCRAFT_PYTHON to fall back to PATH:\n\n" +
      "      pip install " +
      PYPI +
      "\n\n";
  process.stderr.write(
    "pcraft: PCRAFT_PYTHON is set to " +
      configured +
      ", but " +
      why +
      (detail ? " (" + detail + ")" : "") +
      ".\n\n" +
      remedy +
      "  This is refused, not skipped: falling through to the next interpreter on PATH\n" +
      "  would run a DIFFERENT " +
      PYPI +
      " -- another version, other pins, possibly not the\n" +
      "  code you meant to exercise -- and report success. `pcraft doctor` names the\n" +
      "  interpreter that actually answered.\n" +
      "  Docs: " +
      DOCS +
      "\n"
  );
  process.exit(127);
}

/**
 * Find an interpreter that can actually import the toolkit.
 *
 * Deliberately two questions, not one: an interpreter that exists but lacks the package
 * is a DIFFERENT problem from no interpreter at all, and telling them apart is the whole
 * value of this check. Reporting "python not found" to someone who has three Pythons and
 * no package sends them to fix the wrong thing -- the same conflation the gate itself
 * refuses to make between "failed" and "could not run".
 */
function locate(spawnSync) {
  const configured = process.env.PCRAFT_PYTHON;
  const list = candidates();
  let sawInterpreter = false;
  for (let i = 0; i < list.length; i++) {
    const exe = list[i];
    // Index, not name equality: PCRAFT_PYTHON is prepended by candidates(), so only the
    // first entry is the configured one even when it spells the same word as a default.
    const isConfigured = Boolean(configured) && i === 0;
    const pre = argsFor(exe);
    const probe = spawnSync(exe, [...pre, "-c", `import ${IMPORT_NAME}`], {
      stdio: "ignore",
      shell: false,
    });
    if (probe.error) {
      if (isConfigured) {
        refuseConfigured(exe, false, probe.error.code || probe.error.message);
      }
      continue; // this candidate is not on PATH at all
    }
    sawInterpreter = true;
    if (probe.status === 0) return { exe, pre, sawInterpreter };
    if (isConfigured) {
      refuseConfigured(exe, true, "exit " + probe.status);
    }
  }
  return { exe: null, pre: null, sawInterpreter };
}

function fail(found) {
  const what = found.sawInterpreter
    ? `Python is installed, but the ${PYPI} toolkit is not importable from it.`
    : "No Python interpreter was found on PATH.";
  process.stderr.write(
    `pcraft: ${what}\n\n` +
      `  This package is a launcher. The toolkit itself is Python:\n\n` +
      `      pip install ${PYPI}\n\n` +
      `  Point at a specific interpreter with PCRAFT_PYTHON if you use one.\n` +
      `  Docs: ${DOCS}\n`
  );
  process.exit(127);
}

const argv = process.argv.slice(2);

// A self-test that does not need Python present: it proves this file parses, clears its own
// Node floor, resolves its candidate list and reports honestly. `npm test` runs it in CI
// where Python may be absent. It stays ABOVE the dynamic import so it needs no child
// process at all.
if (argv[0] === "--node-selftest") {
  const list = candidates();
  if (!Array.isArray(list) || list.length === 0) {
    process.stderr.write("selftest: no interpreter candidates\n");
    process.exit(1);
  }
  if (argsFor("py")[0] !== "-3") {
    process.stderr.write("selftest: the Windows launcher lost its -3\n");
    process.exit(1);
  }
  process.stdout.write(
    `pcraft launcher ok -- node >=${FLOOR} (running ${nodeVersion().join(".")}); ` +
      `candidates: ${list.join(", ")}\n`
  );
  process.exit(0);
}

function run(spawn, spawnSync) {
  const found = locate(spawnSync);
  if (!found.exe) fail(found);

  // Forward everything verbatim and inherit the child's exit code, so the gate's 2-vs-4
  // distinction survives the trip through Node.
  const child = spawn(found.exe, [...found.pre, "-m", `${IMPORT_NAME}.cli`, ...argv], {
    stdio: "inherit",
    shell: false,
  });
  child.on("exit", (code, signal) =>
    // Written out rather than `code ?? 0`: `??` is a PARSE-level feature (Node 14.0), and a
    // syntax error is raised before the version guard above can run, which would put this
    // file back to dying without a message on exactly the Nodes that guard exists for.
    process.exit(signal ? 1 : code === null || code === undefined ? 0 : code)
  );
  child.on("error", () => fail(found));
}

// Dynamic, and with a `.then` rather than top-level `await`, for the same parse-level reason
// as the ternary above: top-level await would be a syntax error on an old Node and would
// take the version guard down with it.
import("node:child_process").then(
  (childProcess) => run(childProcess.spawn, childProcess.spawnSync),
  (err) => {
    process.stderr.write(
      "pcraft: could not load node:child_process (" +
        (err && err.message ? err.message : String(err)) +
        ").\n  This launcher needs Node " +
        FLOOR +
        " or newer.\n  Docs: " +
        DOCS +
        "\n"
    );
    process.exit(127);
  }
);
