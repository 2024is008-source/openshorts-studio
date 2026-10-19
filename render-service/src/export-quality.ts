import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export interface QualityReport {
  status: "PASS" | "WARNING" | "FAIL";
  accepted: boolean;
  [key: string]: unknown;
}

export class ExportQualityFailure extends Error {
  constructor(public report: QualityReport) {
    super("Export failed technical quality checks. See quality_report.");
  }
}

export async function validateRenderedExport(
  output: string, clipId: string, expected: Record<string, unknown>,
  reference?: string, runner: typeof run = run,
): Promise<QualityReport> {
  const venv = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const python = process.env.PYTHON_EXECUTABLE || (fs.existsSync(venv) ? venv : process.platform === "win32" ? "python" : "python3");
  const args = [...(process.env.OPENSHORTS_FROZEN === '1' ? ['--worker', 'export_quality.py'] : [path.join(root, "export_quality.py")]), "--input", output,
    "--clip-id", clipId, "--expected", JSON.stringify(expected), "--master-audio"];
  if (reference) args.push("--reference", reference);
  let stdout: string;
  try {
    stdout = String((await runner(python, args, { timeout: 200000, maxBuffer: 512 * 1024,
      windowsHide: true, env: { ...process.env, PYTHONUTF8: "1" } })).stdout);
  } catch (error) {
    // Python returns the structured FAIL report with exit code 1.
    stdout = String((error as { stdout?: string }).stdout || "");
    if (!stdout) throw new Error("Export validator unavailable or timed out; output was not accepted.");
  }
  let report: QualityReport;
  try { report = JSON.parse(stdout); }
  catch { throw new Error("Export validator returned an invalid report; output was not accepted."); }
  if (!["PASS", "WARNING", "FAIL"].includes(report.status)
      || report.accepted !== (report.status !== "FAIL")) {
    throw new Error("Export validator returned an invalid verdict.");
  }
  if (!report.accepted) throw new ExportQualityFailure(report);
  return report;
}
