# Reference banner background

The home banner now uses deep navy gradients, a soft teal glow and diagonal translucent light beams matching the supplied reference. Cyan accents apply to the headline highlight, import button, arrow, portrait outline and waveform inside this banner. The surrounding application's charcoal theme is retained.

`HeroBackdrop.cs` draws the background with native WPF gradients and geometry at the current control size. The rounded boundary clips the effect. Decorative drawing does not intercept clicks; headline, import, quick tour and artwork remain native controls. The studio photograph is the existing embedded generated asset.

Build: Final Release build succeeded with zero warnings or errors. Local dashboard review and captures are in `build/hero-background-final-soft`, including `hero-banner.png` and `result.json`. The review uses existing local media and makes no AI analysis requests.
