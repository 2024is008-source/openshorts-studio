import { z } from "zod";

// --- Word-level caption ---
export interface CaptionWord {
  text: string;
  startMs: number;
  endMs: number;
  aligned?: boolean;
  emphasis?: boolean;
}

// --- Subtitle config ---
export type SubtitleAnimation = "none" | "word-highlight" | "pop" | "karaoke" | "fade" | "word-scale" | "word-reveal" | "bounce";
export type SubtitlePosition = "top" | "middle" | "bottom";

export interface SubtitleStyle {
  fontFamily: string;
  fontSize: number;
  fontColor: string;
  highlightColor: string;
  borderColor: string;
  borderWidth: number;
  bgColor: string;
  bgOpacity: number;
  animation: SubtitleAnimation;
  // Karaoke look: dim inactive words (0-1) and force uppercase.
  baseOpacity?: number;
  uppercase?: boolean;
  maxLines?: number;
  shadow?: number;
  maxWords?: number;
  minPhraseMs?: number;
  lineSpacing?: number;
}

export interface SubtitleConfig {
  captions: CaptionWord[];
  position: SubtitlePosition;
  syncOffsetMs?: number;
  splitRanges?: number[][];
  editorialRanges?: number[][];
  blurRanges?: [number, number, number][];
  faceRegions?: {start?: number;end?: number;x: number;y: number;width: number;height: number}[];
  style: SubtitleStyle;
}

// --- Hook config ---
export type HookPosition = "top" | "center" | "bottom";
export type HookSize = "S" | "M" | "L";
export type HookEntrance = "spring" | "fade" | "slide-up" | "none" | "scale-pop" | "highlight-reveal";
export type HookStyle =
  | "classic"
  | "dark"
  | "yellow"
  | "red"
  | "outline"
  | "outline_yellow";

export interface HookConfig {
  text: string;
  position: HookPosition;
  size: HookSize;
  style?: HookStyle;
  entranceAnimation: HookEntrance;
  displayDurationSec: number;
  startSec?: number;
  y?: number;
}

// --- Effects config ---
export interface EffectSegment {
  startSec: number;
  endSec: number;
  zoom: number;
  zoomCenterX: number;
  zoomCenterY: number;
  brightness: number;
  contrast: number;
  saturate: number;
}

export interface EffectsConfig {
  segments: EffectSegment[];
}

// --- Main composition props ---
export interface ShortVideoProps {
  videoUrl: string;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  subtitles: SubtitleConfig | null;
  hook: HookConfig | null;
  effects: EffectsConfig | null;
}

// --- Zod schemas for validation (used by render service) ---
export const captionWordSchema = z.object({
  text: z.string(),
  startMs: z.number(),
  endMs: z.number(),
  aligned: z.boolean().optional(),
  emphasis: z.boolean().optional(),
});

export const subtitleStyleSchema = z.object({
  fontFamily: z.string(),
  fontSize: z.number(),
  fontColor: z.string(),
  highlightColor: z.string(),
  borderColor: z.string(),
  borderWidth: z.number(),
  bgColor: z.string(),
  bgOpacity: z.number().min(0).max(1),
  animation: z.enum(["none", "word-highlight", "pop", "karaoke", "fade", "word-scale", "word-reveal", "bounce"]),
  maxLines: z.number().int().min(1).max(3).optional(),
  shadow: z.number().min(0).max(8).optional(),
  maxWords: z.number().int().min(1).max(12).optional(),
  minPhraseMs: z.number().min(150).max(1000).optional(),
  lineSpacing: z.number().min(1).max(1.6).optional(),
  baseOpacity: z.number().min(0).max(1).optional(),
  uppercase: z.boolean().optional(),
});

export const subtitleConfigSchema = z.object({
  captions: z.array(captionWordSchema),
  syncOffsetMs: z.number().min(-1000).max(1000).optional(),
  splitRanges: z.array(z.array(z.number())).optional(),
  editorialRanges: z.array(z.array(z.number())).optional(),
  blurRanges: z.array(z.tuple([z.number(),z.number(),z.number().min(.5).max(1)])).optional(),
  faceRegions: z.array(z.object({start:z.number().optional(),end:z.number().optional(),x:z.number(),y:z.number(),width:z.number(),height:z.number()})).optional(),
  position: z.enum(["top", "middle", "bottom"]),
  style: subtitleStyleSchema,
});

export const hookConfigSchema = z.object({
  text: z.string(),
  position: z.enum(["top", "center", "bottom"]),
  size: z.enum(["S", "M", "L"]),
  style: z
    .enum(["classic", "dark", "yellow", "red", "outline", "outline_yellow"])
    .default("classic"),
  entranceAnimation: z.enum(["spring", "fade", "slide-up", "none", "scale-pop", "highlight-reveal"]),
  displayDurationSec: z.number().positive(),
  startSec: z.number().nonnegative().optional(),
  y: z.number().min(.04).max(.26).optional(),
});

export const effectSegmentSchema = z.object({
  startSec: z.number().min(0),
  endSec: z.number().positive(),
  zoom: z.number().min(0.5).max(3),
  zoomCenterX: z.number().min(0).max(1),
  zoomCenterY: z.number().min(0).max(1),
  brightness: z.number().min(0).max(3),
  contrast: z.number().min(0).max(3),
  saturate: z.number().min(0).max(3),
});

export const effectsConfigSchema = z.object({
  segments: z.array(effectSegmentSchema),
});

export const shortVideoPropsSchema = z.object({
  videoUrl: z.string(),
  durationInFrames: z.number().int().positive(),
  fps: z.number().positive(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  subtitles: subtitleConfigSchema.nullable(),
  hook: hookConfigSchema.nullable(),
  effects: effectsConfigSchema.nullable(),
});
