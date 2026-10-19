import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { initBundle } from './bundle.js';
import { RenderGate, renderJobs, renderSettings } from './render-jobs.js';
import { executeRender } from './render-worker.js';

test('FIFO rendering slots are bounded and queued work can be cancelled', async () => {
  const gate = new RenderGate(1);
  const first = await gate.acquire(new AbortController().signal);
  const cancelled = new AbortController();
  const queued = gate.acquire(cancelled.signal);
  const rejection = assert.rejects(queued, /cancelled/);
  cancelled.abort(); await rejection;
  let started = false;
  const next = gate.acquire(new AbortController().signal).then(release => { started = true; return release; });
  await new Promise(resolve => setTimeout(resolve, 5)); assert.equal(started, false);
  first(); const release = await next; assert.equal(gate.active, 1);
  release(); release(); assert.equal(gate.active, 0);
});

test('resource settings reject malformed values and clamp concurrency', () => {
  const previous = process.env.REMOTION_CONCURRENCY;
  try {
    process.env.REMOTION_CONCURRENCY = '999'; assert.equal(renderSettings().concurrency, 4);
    process.env.REMOTION_CONCURRENCY = 'bad'; assert.equal(renderSettings().concurrency, 2);
  } finally {
    if (previous === undefined) delete process.env.REMOTION_CONCURRENCY;
    else process.env.REMOTION_CONCURRENCY = previous;
  }
});

test('render worker reserves completion for validation and atomically publishes exact output', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'openshorts-worker-'));
  const previous = process.env.OUTPUT_DIR; process.env.OUTPUT_DIR = folder;
  const renderId = 'test-render';
  renderJobs.set(renderId, { renderId, jobId: 'job', clipIndex: 0, status: 'queued', progress: 0 });
  let staged = '';
  type Dependencies = NonNullable<Parameters<typeof executeRender>[1]>;
  const deps = {
    getBundleLocation: () => 'local-bundle',
    selectComposition: async () => ({ id: 'ShortVideo', width: 1080, height: 1920, fps: 30, durationInFrames: 30 }),
    renderMedia: async (options: { outputLocation: string; onProgress: (p: { progress: number }) => void; concurrency: number; pixelFormat: string }) => {
      staged = options.outputLocation;
      assert.ok(path.basename(staged).startsWith('.remotion_'));
      assert.ok(options.concurrency <= 4); assert.equal(options.pixelFormat, 'yuv420p');
      fs.writeFileSync(staged, 'rendered-video');
      options.onProgress({ progress: 1 });
      assert.equal(renderJobs.get(renderId)?.progress, 90);
      assert.equal(renderJobs.get(renderId)?.status, 'rendering');
    },
    validateRenderedExport: async (file: string) => {
      assert.equal(file, staged); assert.equal(renderJobs.get(renderId)?.status, 'validating');
      return { status: 'PASS', accepted: true };
    },
  } as unknown as Dependencies;
  try {
    await executeRender({ renderId, jobId: 'job', clipIndex: 0, props: {
      videoUrl: 'http://localhost/source.mp4', width: 1080, height: 1920, fps: 30, durationInFrames: 30,
      subtitles: null, hook: null, effects: null,
    } }, deps);
    const job = renderJobs.get(renderId)!;
    assert.equal(job.status, 'done'); assert.equal(job.progress, 100);
    assert.equal(fs.readFileSync(job.outputUrl!, 'utf8'), 'rendered-video');
    assert.equal(fs.existsSync(staged), false); assert.equal(job.controller, undefined);
    assert.equal(JSON.parse(fs.readFileSync(job.outputUrl! + '.quality.json', 'utf8')).accepted, true);
  } finally {
    renderJobs.delete(renderId);
    if (previous === undefined) delete process.env.OUTPUT_DIR; else process.env.OUTPUT_DIR = previous;
    assert.ok(path.resolve(folder).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test('cancel during rendering cleans only owned staging and never publishes completion', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'openshorts-cancel-'));
  const previous = process.env.OUTPUT_DIR; process.env.OUTPUT_DIR = folder;
  const renderId = 'cancel-render';
  renderJobs.set(renderId, { renderId, jobId: 'job', clipIndex: 0, status: 'queued', progress: 0 });
  type Dependencies = NonNullable<Parameters<typeof executeRender>[1]>;
  const deps = {
    getBundleLocation: () => 'bundle', selectComposition: async () => ({ width: 1080, height: 1920, fps: 30, durationInFrames: 30 }),
    renderMedia: async (options: { outputLocation: string; cancelSignal: (cb: () => void) => void }) => {
      fs.writeFileSync(options.outputLocation, 'partial');
      await new Promise((_resolve, reject) => {
        options.cancelSignal(() => reject(new Error('User cancelled')));
        renderJobs.get(renderId)!.controller!.abort('user');
      });
    },
    validateRenderedExport: async () => assert.fail('Cancelled output must not validate or publish'),
  } as unknown as Dependencies;
  try {
    await executeRender({ renderId, jobId: 'job', clipIndex: 0, props: { videoUrl: 'http://localhost/source', width: 1080, height: 1920,
      fps: 30, durationInFrames: 30, subtitles: null, hook: null, effects: null } }, deps);
    assert.equal(renderJobs.get(renderId)!.status, 'cancelled');
    assert.equal(renderJobs.get(renderId)!.outputUrl, undefined);
    assert.deepEqual(fs.readdirSync(path.join(folder, 'job')), []);
  } finally {
    renderJobs.delete(renderId);
    if (previous === undefined) delete process.env.OUTPUT_DIR; else process.env.OUTPUT_DIR = previous;
    assert.ok(path.resolve(folder).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test('real worker exports validated full-HD H.264/AAC through staging', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'openshorts-worker-real-'));
  const previous = process.env.OUTPUT_DIR; process.env.OUTPUT_DIR = folder;
  const source = path.join(folder, 'source.mp4'); const renderId = 'real-worker';
  execFileSync('ffmpeg', ['-v','error','-y','-f','lavfi','-i','color=c=0x304050:s=270x480:r=24:d=1',
    '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','1',
    '-pix_fmt','yuv420p','-c:a','aac',source], { timeout: 15000, windowsHide: true });
  const bytes = fs.readFileSync(source);
  const server = createServer((req, res) => {
    const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range || '');
    const start = range ? Number(range[1]) : 0;
    const end = range?.[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1;
    res.writeHead(range ? 206 : 200, { 'Content-Type':'video/mp4','Accept-Ranges':'bytes','Access-Control-Allow-Origin':'*',
      'Content-Length':end-start+1,...(range ? { 'Content-Range':`bytes ${start}-${end}/${bytes.length}` } : {}) });
    res.end(bytes.subarray(start, end + 1));
  });
  try {
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
    await initBundle();
    renderJobs.set(renderId, { renderId, jobId:'job', clipIndex:0, status:'queued', progress:0 });
    await executeRender({ renderId, jobId:'job', clipIndex:0, props: {
      videoUrl:`http://127.0.0.1:${(server.address() as AddressInfo).port}/source.mp4`,
      width:1080,height:1920,fps:24,durationInFrames:24,audioExpected:true,
      subtitles:{ captions:[{ text:'Measured',startMs:100,endMs:450 },{ text:'export.',startMs:500,endMs:900 }],
        position:'bottom',style:{fontFamily:'Arial',fontSize:52,fontColor:'#FFFFFF',highlightColor:'#00FFFF',
          borderColor:'#000000',borderWidth:2,bgColor:'#000000',bgOpacity:0,animation:'pop',maxLines:2,shadow:1} },
      hook:null,effects:null,
    } });
    const job = renderJobs.get(renderId)!;
    assert.equal(job.status, 'done', job.error || 'The staged worker did not complete');
    assert.equal(job.progress, 100); assert.equal(job.qualityReport?.accepted, true);
    const media = JSON.parse(execFileSync('ffprobe', ['-v','error','-show_streams','-of','json',job.outputUrl!],
      { timeout:10000,windowsHide:true,encoding:'utf8' }));
    assert.equal(media.streams[0].width, 1080); assert.equal(media.streams[0].height, 1920);
    assert.equal(media.streams[0].codec_name, 'h264'); assert.equal(media.streams[0].pix_fmt, 'yuv420p');
    assert.equal(media.streams.find((s: {codec_type:string}) => s.codec_type === 'audio').codec_name, 'aac');
    const exported = fs.readFileSync(job.outputUrl!);
    assert.ok(exported.indexOf(Buffer.from('moov')) < exported.indexOf(Buffer.from('mdat')));
    assert.ok(!fs.readdirSync(path.join(folder, 'job')).some(file => file.startsWith('.remotion_')));
  } finally {
    await new Promise<void>(resolve => server.close(() => resolve())); renderJobs.delete(renderId);
    if (previous === undefined) delete process.env.OUTPUT_DIR; else process.env.OUTPUT_DIR = previous;
    assert.ok(path.resolve(folder).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(folder, {recursive:true,force:true});
  }
});
