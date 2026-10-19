import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import fs from 'node:fs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(root, 'render-service/package.json'));
const { bundle } = require('@remotion/bundler');
const { ensureBrowser } = require('@remotion/renderer');
await bundle({ entryPoint: path.join(root, 'remotion/src/index.ts'),
    webpackOverride: (config) => ({ ...config, cache: false }),
    outDir: path.join(root, 'build/desktop-resources/remotion-bundle') });
process.chdir(path.join(root, 'render-service'));
const browser = path.join(root, 'render-service/node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
await ensureBrowser({ chromeMode: 'headless-shell', ...(fs.existsSync(browser) ? {browserExecutable: browser} : {}) });
