import React from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from 'remotion';
import type { HookConfig } from '../lib/types';


const LOOKS: Record<string, { box: string; color: string; outline?: boolean }> = {
  classic: { box: 'rgba(255,255,255,.94)', color: '#000' },
  dark: { box: 'rgba(18,18,20,.92)', color: '#fff' },
  yellow: { box: '#FFD600', color: '#000' },
  red: { box: '#DC2626', color: '#fff' },
  outline: { box: 'transparent', color: '#fff', outline: true },
  outline_yellow: { box: 'transparent', color: '#FFD600', outline: true },
};

export const HookOverlay: React.FC<{ config: HookConfig }> = ({ config }) => {
  const { fps } = useVideoConfig();
  return <AbsoluteFill>
    <Sequence from={Math.max(0, Math.round((config.startSec || 0) * fps))} durationInFrames={Math.max(1, Math.round(config.displayDurationSec * fps))} layout="none">
      <HookBox config={config} />
    </Sequence>
  </AbsoluteFill>;
};

const HookBox: React.FC<{ config: HookConfig }> = ({ config }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const seconds = frame / fps;
  const entrance = Math.min(.28, config.displayDurationSec / 3);
  const progress = Math.min(1, seconds / entrance);
  const fade = Math.min(.1, entrance);
  let opacity = config.entranceAnimation === 'none' ? 1 : Math.min(1, seconds / fade);
  let scale = 1;
  let dy = 0;
  if (config.entranceAnimation === 'fade') opacity = progress;
  if (config.entranceAnimation === 'scale-pop') scale = .85 + .15 * progress;
  if (config.entranceAnimation === 'spring') scale = progress < .5 ? .85 + .4 * progress : 1.1 - .1 * progress;
  if (config.entranceAnimation === 'slide-up') dy = height * .02 * (1 - progress);
  if (config.entranceAnimation !== 'none') opacity *= Math.min(1, Math.max(0, (config.displayDurationSec - seconds) / fade));
  const look = LOOKS[config.style || 'classic'] || LOOKS.classic;
  const size = { S: .8, M: 1, L: 1.3 }[config.size] || 1;
  // Approximate live text fit. The rendered preview is the libass export result.
  const fontSize = Math.min(width * .045 * size, width * 1.8 / Math.max(20, config.text.length));
  const y = config.y ?? { top: .06, center: .42, bottom: .68 }[config.position];
  return <div style={{ position: 'absolute', left: '6%', width: '88%', top: (y + .08) * height, transform: 'translateY(-50%)', textAlign: 'center' }}>
    <div style={{ display: 'inline-block', maxWidth: '100%', padding: look.outline ? 0 : width * .006, background: look.box, boxShadow: look.outline ? 'none' : '2px 2px 4px #0008',
      opacity, transform: `translateY(${dy}px) scale(${scale})`, clipPath: config.entranceAnimation === 'highlight-reveal' ? `inset(0 ${(1 - progress) * 100}% 0 0)` : undefined }}>
      <span style={{ fontFamily: 'Arial, Helvetica, sans-serif', fontSize, lineHeight: 1.4, fontWeight: 700, color: look.color, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
        WebkitTextStroke: look.outline ? `${Math.max(1, width * .006)}px #000` : undefined, paintOrder: 'stroke fill' }}>{config.text}</span>
    </div>
  </div>;
};
