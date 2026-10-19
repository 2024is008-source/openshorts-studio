import express from "express";
import { timingSafeEqual } from "node:crypto";
import path from "node:path";
import { v4 as uuidv4 } from "uuid";
import { z } from "zod";
import { initBundle } from "./bundle.js";
import { executeRender } from "./render-worker.js";
import { renderJobs, renderSettings } from "./render-jobs.js";
import type { RenderJob } from "./render-jobs.js";
export { renderJobs } from "./render-jobs.js";
export type { RenderJob, RenderStatus } from "./render-jobs.js";

// --- Render status types ---


// --- Request validation schema ---

const renderRequestSchema = z.object({
  jobId: z.string().regex(/^[a-zA-Z0-9_-]{1,128}$/),
  clipIndex: z.number().int().min(0),
  props: z.object({
    videoUrl: z.string(),
    durationInFrames: z.number().int().positive().max(432000),
    fps: z.number().positive().max(240),
    width: z.number().int().min(2).max(8192).refine(n => n % 2 === 0),
    height: z.number().int().min(2).max(8192).refine(n => n % 2 === 0),
    subtitles: z.any().nullable().optional(),
    hook: z.any().nullable().optional(),
    effects: z.any().nullable().optional(),
    audioExpected: z.boolean().optional(),
  }).refine(p => p.durationInFrames / p.fps <= 1800 && p.width * p.height <= 33177600),
});

// --- Express app ---

const app = express();
const desktopToken = process.env.OPENSHORTS_RENDER_TOKEN;
app.use((req, res, next) => {
  if (!desktopToken) { next(); return; }
  // Media uses a separate capability URL, consumed only by owned Chromium.
  const mediaPrefix = `/desktop-media/${desktopToken}/`;
  if (req.path.startsWith(mediaPrefix)) { next(); return; }
  const provided = Buffer.from(req.header('X-OpenShorts-Render') || '');
  const expected = Buffer.from(desktopToken);
  if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
    res.status(403).json({ error: 'Desktop renderer session required' }); return;
  }
  next();
});
app.use(express.json({ limit: "10mb" }));

const PORT = parseInt(process.env.PORT || "3100", 10);
const OUTPUT_DIR = process.env.OUTPUT_DIR || path.resolve(import.meta.dirname, '../../output');

// Serve video files from the shared output volume so Remotion can access them via HTTP
app.use("/output", express.static(OUTPUT_DIR));
if (desktopToken) app.use(`/desktop-media/${desktopToken}`, express.static(OUTPUT_DIR, { dotfiles: 'deny' }));

// Health check
app.get("/health", (_req, res) => {
  res.json({ ok: true, renderer: "remotion", encoder: "libx264", limits: renderSettings() });
});

// Submit a render job
app.post("/render", (req, res) => {
  const parsed = renderRequestSchema.safeParse(req.body);

  if (!parsed.success) {
    res.status(400).json({
      error: "Invalid request body",
      details: parsed.error.issues,
    });
    return;
  }

  const { jobId, clipIndex, props } = parsed.data;
  // Retain active work; bound terminal in-memory status records independently
  // of the existing media/project retention policy.
  for (const [id, entry] of renderJobs) {
    if (['done','error','cancelled'].includes(entry.status) &&
        (renderJobs.size >= 256 || Date.now() - (entry.createdAt || 0) > 3600000)) renderJobs.delete(id);
  }
  if (renderJobs.size >= 256) { res.status(429).json({ error: 'Render status capacity reached; try again later.' }); return; }
  const renderId = uuidv4();

  const job: RenderJob = {
    renderId,
    jobId,
    clipIndex,
    status: "queued",
    progress: 0,
    createdAt: Date.now(),
  };

  renderJobs.set(renderId, job);

  console.log(
    `[render] Queued render ${renderId} for job=${jobId} clip=${clipIndex}`
  );

  // Resolve video URL: convert frontend/backend URLs to renderer's own static server
  // The renderer serves /output/* from the shared Docker volume
  let resolvedVideoUrl = props.videoUrl;
  const videoPathMatch = props.videoUrl.match(/\/videos\/([^/]+)\/(.+)$/);
  if (videoPathMatch) {
    resolvedVideoUrl = `http://127.0.0.1:${PORT}/${desktopToken ? `desktop-media/${desktopToken}` : 'output'}/${videoPathMatch[1]}/${videoPathMatch[2]}`;
  }

  // Fire and forget - render runs in background
  executeRender({
    renderId,
    jobId,
    clipIndex,
    props: {
      videoUrl: resolvedVideoUrl,
      durationInFrames: props.durationInFrames,
      fps: props.fps,
      width: props.width,
      height: props.height,
      subtitles: props.subtitles ?? null,
      hook: props.hook ?? null,
      effects: props.effects ?? null,
      audioExpected: props.audioExpected,
    },
  }).catch((err) => {
    console.error(`[render] Unhandled error for ${renderId}:`, err);
    const existingJob = renderJobs.get(renderId);
    if (existingJob) {
      existingJob.status = "error";
      existingJob.error =
        err instanceof Error ? err.message : "Unknown error";
    }
  });

  res.status(202).json({ renderId, status: "queued" });
});

// Get render status
app.get("/render/:renderId", (req, res) => {
  const { renderId } = req.params;
  const job = renderJobs.get(renderId);

  if (!job) {
    res.status(404).json({ error: "Render not found" });
    return;
  }

  const response: Record<string, unknown> = {
    renderId: job.renderId,
    jobId: job.jobId,
    clipIndex: job.clipIndex,
    status: job.status,
  };

  if (job.progress !== undefined) {
    response.progress = job.progress;
  }
  if (job.outputUrl) {
    response.outputUrl = job.outputUrl;
  }
  if (job.error) {
    response.error = job.error;
  }
  if (job.qualityReport) response.quality_report = job.qualityReport;

  res.json(response);
});

app.post('/render/:renderId/cancel', (req, res) => {
  const job = renderJobs.get(req.params.renderId);
  if (!job) { res.status(404).json({ error: 'Render not found' }); return; }
  if (['queued', 'rendering', 'validating'].includes(job.status)) job.controller?.abort('user');
  res.json({ renderId: job.renderId, status: job.status, cancellationRequested: !!job.controller?.signal.aborted });
});

// --- Start server ---

async function main() {
  console.log("[render-service] Initializing Remotion bundle...");
  await initBundle();
  console.log("[render-service] Bundle ready.");

  app.listen(PORT, process.env.RENDER_HOST || '127.0.0.1', () => {
    console.log(`[render-service] Listening on port ${PORT}`);
  });
}

main().catch((err) => {
  console.error("[render-service] Fatal error during startup:", err);
  process.exit(1);
});
