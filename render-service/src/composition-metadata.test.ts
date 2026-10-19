import { before, test } from "node:test";
import assert from "node:assert/strict";
import { selectComposition, renderMedia } from "@remotion/renderer";
import { initBundle, getBundleLocation } from "./bundle.js";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { execFileSync } from "node:child_process";
import { validateRenderedExport, ExportQualityFailure } from "./export-quality.js";

/**
 * Contract test for the render pipeline's composition metadata.
 *
 * render-worker.ts passes durationInFrames/fps/width/height via inputProps and
 * renders whatever selectComposition() reports. Without calculateMetadata on
 * the ShortVideo Composition, Remotion ignores those inputProps and always
 * reports the static DEFAULT_PROPS metadata (900 frames / 30fps / 1080x1920),
 * so every clip renders at 30s regardless of its real length.
 */

const BUNDLE_TIMEOUT_MS = 5 * 60 * 1000;

before(async () => {
  await initBundle();
}, { timeout: BUNDLE_TIMEOUT_MS });

test(
  "selectComposition honors per-render duration/fps/dimensions from inputProps",
  { timeout: BUNDLE_TIMEOUT_MS },
  async () => {
    const composition = await selectComposition({
      serveUrl: getBundleLocation(),
      id: "ShortVideo",
      inputProps: {
        videoUrl: "",
        durationInFrames: 300,
        fps: 25,
        width: 720,
        height: 1280,
      },
      logLevel: "error",
    });

    assert.equal(composition.durationInFrames, 300);
    assert.equal(composition.fps, 25);
    assert.equal(composition.width, 720);
    assert.equal(composition.height, 1280);
  }
);

test(
  "selectComposition falls back to DEFAULT_PROPS metadata when inputProps omit it",
  { timeout: BUNDLE_TIMEOUT_MS },
  async () => {
    const composition = await selectComposition({
      serveUrl: getBundleLocation(),
      id: "ShortVideo",
      inputProps: { videoUrl: "" },
      logLevel: "error",
    });

    assert.equal(composition.durationInFrames, 900);
    assert.equal(composition.fps, 30);
    assert.equal(composition.width, 1080);
    assert.equal(composition.height, 1920);
  }
);

test("a real Remotion export passes the shared gate and a mismatched preset fails", { timeout: 120000 }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "openshorts-render-quality-"));
  const source = path.join(dir, "source.mp4");
  const output = path.join(dir, "output.mp4");
  execFileSync("ffmpeg", ["-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
    "color=c=green:s=64x36:r=12:d=1", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", source], { timeout: 30000, windowsHide: true });
  const bytes = fs.readFileSync(source);
  const server = createServer((req, res) => {
    const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range || "");
    const start = range ? Number(range[1]) : 0;
    const end = range?.[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1;
    res.writeHead(range ? 206 : 200, { "Content-Type": "video/mp4", "Accept-Ranges": "bytes",
      "Access-Control-Allow-Origin": "*", "Content-Length": end - start + 1,
      ...(range ? { "Content-Range": `bytes ${start}-${end}/${bytes.length}` } : {}) });
    res.end(bytes.subarray(start, end + 1));
  });
  try {
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const props = { videoUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}/source.mp4`,
      durationInFrames: 12, fps: 12, width: 64, height: 36,
      subtitles: {captions:[{text:'Hello',startMs:50,endMs:450},{text:'world!',startMs:500,endMs:900}],
        position:'bottom' as const,style:{fontFamily:'Arial',fontSize:52,fontColor:'#FFFFFF',
          highlightColor:'#FFE500',borderColor:'#000000',borderWidth:2,bgColor:'#000000',
          bgOpacity:0,animation:'pop' as const,maxLines:2,shadow:1}}, hook: null, effects: null };
    const composition = await selectComposition({ serveUrl: getBundleLocation(), id: "ShortVideo", inputProps: props });
    await renderMedia({ composition, serveUrl: getBundleLocation(), inputProps: props,
      codec: "h264", outputLocation: output, concurrency: 1, logLevel: "error", timeoutInMilliseconds: 30000 });
    const expected = { width: 64, height: 36, aspect: 64 / 36, fps: 12, duration: 1, audio_expected: true };
    assert.equal((await validateRenderedExport(output, "clip_1", expected, source)).status, "PASS");
    await assert.rejects(validateRenderedExport(output, "clip_1", { ...expected, width: 1080 }, source),
      (error: unknown) => error instanceof ExportQualityFailure);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    assert.ok(path.resolve(dir).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(dir, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  }
});
