# Reference button and icon styling

The home-screen controls now follow the supplied cyan reference:

- Primary actions, logo and active navigation use bright cyan; primary-action text and glyphs use dark ink.
- New Project is 118 × 34 DIPs. Hero Import is 160 × 36; Quick Tour is 146 × 36. Sizes remain device-independent and follow Windows display scaling.
- Navigation tiles are 40 × 40 with 22 × 22 outline icons. Settings and Account have unboxed inactive icons.
- Quick Start badges are 60 × 60 with 32 × 32 icons, using blue/cyan, teal/cyan and purple/violet gradients.
- Secondary actions use dark navy fills. Sidebar controls use cyan accents and compact action heights while preserving the charcoal panel surfaces and fitted layout.
- Scissors, document, clapperboard, play-circle and processing-mode icons use native vector geometry.
- The header profile placeholder reuses the existing illustrative studio artwork. Account status and benchmark availability remain factual.

Quick Tour opens the actual native walkthrough; no prerecorded video guide is claimed. Import, project reopening, preset selection, processing mode and workspace navigation retain their existing commands.

Verification artifacts are under `build/reference-controls-verified` and `build/reference-controls-window`. The visual check validates cyan primary actions and button heights with tolerance for Windows device-pixel rounding at 125% scaling. Existing C# regressions: 37 passed. Local review uses existing media with no AI analysis calls.
