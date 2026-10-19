import type { QualityReport } from "./export-quality.js";

export type RenderStatus = "queued" | "rendering" | "validating" | "done" | "error" | "cancelled";
export interface RenderJob {
  renderId: string; jobId: string; clipIndex: number; status: RenderStatus; progress: number;
  outputUrl?: string; error?: string; qualityReport?: QualityReport;
  controller?: AbortController; createdAt?: number;
}
export const renderJobs = new Map<string, RenderJob>();

export function bounded(value: string | undefined, fallback: number, max: number): number {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? Math.min(number, max) : fallback;
}
export const renderSettings = () => ({
  workers: bounded(process.env.RENDER_SERVICE_WORKERS, 1, 4),
  concurrency: bounded(process.env.REMOTION_CONCURRENCY, 2, 4),
  timeout: bounded(process.env.REMOTION_TIMEOUT_SECONDS, 600, 1800) * 1000,
});

/** FIFO slots; queued cancellation removes work immediately, no detached render. */
export class RenderGate {
  active = 0;
  private queue: Array<() => void> = [];
  constructor(readonly maximum: number) {}
  acquire(signal: AbortSignal): Promise<() => void> {
    return new Promise((resolve, reject) => {
      if (signal.aborted) { reject(new Error("Render cancelled")); return; }
      if (this.queue.length >= 64) { reject(new Error("Render queue is full")); return; }
      const abort = () => {
        this.queue = this.queue.filter(item => item !== grant);
        reject(new Error("Render cancelled while queued"));
      };
      const grant = () => {
        signal.removeEventListener("abort", abort);
        this.active++;
        let released = false;
        resolve(() => {
          if (released) return;
          released = true; this.active--;
          this.queue.shift()?.();
        });
      };
      signal.addEventListener("abort", abort, { once: true });
      if (this.active < this.maximum) grant(); else this.queue.push(grant);
    });
  }
}
export const renderGate = new RenderGate(renderSettings().workers);
