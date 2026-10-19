import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { validateRenderedExport, ExportQualityFailure } from "./export-quality.js";

type Runner = NonNullable<Parameters<typeof validateRenderedExport>[4]>;

test("accepted warnings are returned and subprocess resources are bounded", async () => {
  const runner = (async (_python: string, args: string[], options: Record<string, unknown>) => {
    assert.equal(options.windowsHide, true);
    assert.equal(options.timeout, 200000);
    assert.ok(args.includes("--master-audio"));
    assert.equal(options.maxBuffer, 512 * 1024);
    assert.ok(args.includes("--reference"));
    assert.ok(args.includes("video with spaces.mp4"));
    return { stdout: JSON.stringify({ status: "WARNING", accepted: true }), stderr: "" };
  }) as Runner;
  const report = await validateRenderedExport("video with spaces.mp4", "clip_1", { fps: 30 }, "source.mp4", runner);
  assert.equal(report.status, "WARNING");
});

test("a Python FAIL exit carries its structured report", async () => {
  const runner = (async () => {
    throw { stdout: JSON.stringify({ status: "FAIL", accepted: false, problems: [{ code: "MISSING_AUDIO" }] }) };
  }) as unknown as Runner;
  await assert.rejects(validateRenderedExport("out.mp4", "clip_1", {}, undefined, runner),
    (err: unknown) => err instanceof ExportQualityFailure && err.report.status === "FAIL");
});

test("validator errors and malformed verdicts cannot mark a render done", async () => {
  for (const stdout of ["not json", '{"status":"PASS","accepted":false}', ""]) {
    const runner = (async () => ({ stdout, stderr: "" })) as unknown as Runner;
    await assert.rejects(validateRenderedExport("out.mp4", "clip_1", {}, undefined, runner));
  }
});

test("real Python CLI rejects a missing artifact", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "openshorts-quality-"));
  try {
    await assert.rejects(validateRenderedExport(path.join(dir, "missing.mp4"), "clip_1", {}),
      (err: unknown) => err instanceof ExportQualityFailure && err.report.status === "FAIL");
  } finally {
    assert.ok(path.resolve(dir).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
