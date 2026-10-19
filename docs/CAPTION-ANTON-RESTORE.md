# Restore the large classic caption look

The current Challenge job selected Classic captions, but the template supplied Arial at 64px in a 1080x1920 canvas. The previous automatic style uses bundled Anton, uppercase white text, yellow emphasis and a heavy black outline. The newer renderer also estimated every character at 1.05 em, unnecessarily shrinking condensed Anton text.

## Changes

- Bold Creator / Creator Bold now use bundled Anton, uppercase white text, yellow active words, a 220px full-HD base size, 14px outline and short groups. Font size scales with output resolution and still fits the available safe width/height. Other caption styles remain available.
- The Challenge starter uses those font/outline values. Font size customization supports 24–240px and templates accept bundled Anton; user-saved/custom snapshots remain intact.
- Anton ASCII text uses cached Pillow metrics from the existing font file for wrapping/fitting. Other scripts retain conservative fallback-font sizing. Timing, punctuation, source text and word synchronization are retained; uppercase is a display treatment.
- Classic is the generation dashboard default again. The editing director maps an explicit Classic choice to the restored bold style rather than silently substituting a small modern font.
- Saved timeline caption rendering includes the existing bundled fonts directory. Caption renderer versioning invalidates old overlay caches while retaining clean video caches. No Gemini or ASR rerun is needed for a caption-only export.

## Verification

- Final caption/style/template checks: **113 passed**, `logs/caption-anton-styles-final.xml`.
- Director/timeline/cache checks: **74 passed**, `logs/caption-anton-final.xml`. Counts overlap; they are not a combined total.
- Dashboard helper tests: **28 passed**. ESLint for the two changed components and production build passed; existing optional OpenPanel, Browserslist and chunk-size warnings remain.
- Real center-crop and blurred-background 1080x1920 samples passed technical validation and were visually inspected. No live Gemini call or retranscription was needed.
- The initial broad run had 178 passes and two outdated assertions expecting mixed-case Cyrillic in the now-uppercase bold presets; those expectations were updated and the final 113-test style group passed.

A real retained-speech 1080x1920 sample was rendered and visually inspected, with the source interval 737.3–739.6s and existing transcript timing. The sample passed technical validation. Center-crop and blurred-background samples demonstrate the lettering and are not replacements for the existing shot decisions; this change concerns caption appearance. No existing project or delivered clip was overwritten.

![Restored caption sample](../output/caption-anton-restore/restored-blur.png)

Sample videos: `output/caption-anton-restore/restored.mp4` and `restored-blur.mp4`. Frames with matching names are in that directory.

## Using the restored look

Let any active generation finish before restarting OpenShorts. New Challenge exports use the restored defaults. For existing saved editor projects, reselect the Challenge starter to replace its previous Arial settings, then preview/export. For caption-only editing without a template, choose Bold Creator or Creator Bold. Saved custom templates intentionally keep their explicit font/size until edited. Source analysis and transcription can be reused.

Existing exports are already burned in and cannot change just because a default changed; rerender from the clean clip using the existing editor. Check the preview on a phone, particularly two-line captions and faces near the caption band. Live browser clicking was not performed; backend render/API tests, frontend helper tests, lint and build provide the verification listed above.

## Changed files

`caption_renderer.py`, `video_templates.py`, `assets/video_templates.json`, `editing_director.py`, `timeline_render.py`, `dashboard/src/components/MediaInput.jsx`, `dashboard/src/components/VideoTemplateControls.jsx`, `tests/test_professional_captions.py`, `tests/test_video_templates.py`, `tests/test_editing_director.py`, `tests/test_bold_caption_restore.py`, `LOCAL_README.md`, and this report.

Suggested commit: `fix(captions): restore large Anton captions and classic generation defaults`
