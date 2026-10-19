import fs from "node:fs";
import path from "node:path";
import { selectComposition, renderMedia, makeCancelSignal } from "@remotion/renderer";
import { getBundleLocation } from "./bundle.js";
import { renderJobs, renderSettings, renderGate } from "./render-jobs.js";
import { validateRenderedExport, ExportQualityFailure } from "./export-quality.js";

export interface RenderParams {
  renderId: string;
  jobId: string;
  clipIndex: number;
  props: {
    videoUrl: string;
    durationInFrames: number;
    fps: number;
    width: number;
    height: number;
    subtitles: unknown;
    hook: unknown;
    effects: unknown;
    audioExpected?: boolean;
  };
}

/**
 * Executes a Remotion render in the background.
 * Updates the in-memory render job map with progress and final status.
 */
export async function executeRender(params: RenderParams, deps = {
  selectComposition, renderMedia, getBundleLocation, validateRenderedExport,
}): Promise<void> {
  const { renderId, jobId, clipIndex, props } = params;
  const job = renderJobs.get(renderId);

  if (!job) {
    console.error(`[render-worker] Job ${renderId} not found in map`);
    return;
  }

  const controller = new AbortController(); job.controller = controller;
  const { cancelSignal, cancel } = makeCancelSignal();
  controller.signal.addEventListener('abort', cancel, { once: true });
  let release: (() => void) | undefined;
  let outputLocation: string | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const check = () => { if (controller.signal.aborted) throw new Error('Render cancelled'); };
  try {
    timer = setTimeout(() => controller.abort('timeout'), renderSettings().timeout);
    release = await renderGate.acquire(controller.signal);
    check();
    job.status = "rendering";
    job.progress = 0;

    console.log(
      `[render-worker] Starting render ${renderId} (job=${jobId}, clip=${clipIndex})`
    );

    const bundleLocation = deps.getBundleLocation();

    // Select the composition with the provided input props
    const composition = await deps.selectComposition({
      ...(process.env.REMOTION_BROWSER_EXECUTABLE ? { browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE } : {}),
      serveUrl: bundleLocation,
      id: "ShortVideo",
      inputProps: props,
      timeoutInMilliseconds: 30000,
    });
    check();

    // Determine output directory and file path
    const outputDir = process.env.OUTPUT_DIR
      ? path.resolve(process.env.OUTPUT_DIR)
      : path.resolve(import.meta.dirname, "../../output");

    const jobOutputDir = path.join(outputDir, jobId);
    fs.mkdirSync(jobOutputDir, { recursive: true });

    const timestamp = Date.now();
    const outputFileName = `remotion_${clipIndex}_${timestamp}_${renderId}.mp4`;
    const finalLocation = path.join(jobOutputDir, outputFileName);
    outputLocation = path.join(jobOutputDir, `.remotion_${renderId}.mp4`);

    console.log(`[render-worker] Output: ${outputLocation}`);

    // Render the video
    const preset = process.env.REMOTION_X264_PRESET || 'medium';
    if (!['ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow'].includes(preset)) throw new Error('Invalid REMOTION_X264_PRESET');
    await deps.renderMedia({
      ...(process.env.REMOTION_BROWSER_EXECUTABLE ? { browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE } : {}),
      composition,
      serveUrl: bundleLocation,
      inputProps: props,
      codec: "h264",
      crf: process.env.QUALITY_PRESET === 'studio' ? 16 : 22,
      x264Preset: preset as 'medium',
      hardwareAcceleration: 'disable', // Installed Remotion H.264 has no Windows NVENC path.
      pixelFormat: 'yuv420p', audioCodec: 'aac', audioBitrate: '192k',
      colorSpace: 'bt709',
      concurrency: renderSettings().concurrency,
      offthreadVideoThreads: 2, offthreadVideoCacheSizeInBytes: 128 * 1024 * 1024,
      cancelSignal, timeoutInMilliseconds: 60000,
      outputLocation,
      onProgress: ({ progress }) => {
        const percent = Math.min(90, Math.round(progress * 90));
        job.progress = percent;

        if (percent % 10 === 0) {
          console.log(`[render-worker] ${renderId} progress: ${percent}%`);
        }
      },
    });
    check();
    job.status = "validating";
    let reference: string | undefined;
    try {
      const url = new URL(props.videoUrl);
      if (url.pathname.startsWith("/output/")) {
        const candidate = path.resolve(outputDir, decodeURIComponent(url.pathname.slice(8)));
        if (candidate.startsWith(path.resolve(outputDir) + path.sep) && fs.existsSync(candidate)) reference = candidate;
      }
    } catch { /* Remote sources can declare audioExpected explicitly. */ }
    job.qualityReport = await deps.validateRenderedExport(outputLocation, `clip_${clipIndex + 1}`, {
      width: composition.width, height: composition.height,
      aspect: composition.width / composition.height, fps: composition.fps,
      duration: composition.durationInFrames / composition.fps,
      audio_expected: props.audioExpected ?? null,
      video_codec: 'h264', pixel_format: 'yuv420p', audio_codec: 'aac',
    }, reference);
    if (!job.qualityReport.accepted) throw new ExportQualityFailure(job.qualityReport);
    check();
    fs.renameSync(outputLocation, finalLocation);
    job.qualityReport.file = outputFileName;
    fs.writeFileSync(finalLocation + '.quality.json', JSON.stringify(job.qualityReport));

    // Success is published only after the shared technical gate accepts it.
    job.status = "done";
    job.progress = 100;
    job.outputUrl = finalLocation;

    console.log(`[render-worker] Render ${renderId} completed: ${outputLocation}`);
  } catch (err) {
    if (err instanceof ExportQualityFailure) job.qualityReport = err.report;
    job.status = controller.signal.aborted && controller.signal.reason !== 'timeout' ? 'cancelled' : 'error';
    job.error = controller.signal.reason === 'timeout' ? 'Render exceeded the configured timeout.' : err instanceof Error ? err.message : String(err);

    console.error(`[render-worker] Render ${renderId} failed:`, err);
  } finally {
    if (timer) clearTimeout(timer);
    controller.signal.removeEventListener('abort', cancel);
    if (outputLocation) for (const suffix of ['', '.quality.json', '.audio.json', '.audio-analysis.json', '.render.json']) {
      try { fs.rmSync(outputLocation + suffix, { force: true }); } catch { /* Only this render's owned staging files. */ }
    }
    release?.();
    delete job.controller;
  }
}
