# Per-game notes: config files, encodings, costs

These are hardware-agnostic. Add a game here when its config encoding or a costly setting is worth remembering.
Mark an encoding **verified** only after `graphics.py diff <slug>` confirmed it against the in-game menu.

## World of Warcraft (retail, Classic, Forever)
- **Config:** `<install>\_<flavour>_\WTF\Config.wtf`, format `wtf` (`SET name "value"`). Close the game first: it
  rewrites the file on exit. Never touch addons, `SavedVariables` or game-pad settings.
- **Upscalers:** none modern. Only render scale plus old FSR 1. OptiScaler: never (Warden, online).
- **Costs (WoW Forever, Bellular Warcraft and community tests at 1440p):**
  - Secondary Lighting High→Ultra: up to 50 fps. It's the RT-based local lighting.
  - Compute Effects (volumetric fog and light shafts) High→Ultra High: 40-50 fps.
  - Ray-traced shadows: about 30 fps.
  - 8x MSAA: about 35 fps.
  - Shadows Ultra High vs Good: 15-25 fps. SSAO: about 10 fps.
  - Liquid detail and texture resolution: near free. View distance: small, because the new fog hides distance.
  - Render scale is the biggest lever, but 75% is blurry.
- **Recommended:** Secondary Lighting Good/High (never below Fair). Compute Effects High. Shadows Good/High. SSAO
  High. RT shadows off. AA CMAA2 (+2x MSAA with Multisample Alpha Test if there's headroom). Render scale 100%.
  View distance, environment detail and texture resolution at max. Liquid High. Bloom lowered.
- **CVars (verified names):**
  - `graphicsViewDistance`, `graphicsEnvironmentDetail`, `graphicsGroundClutter` (1-10 sliders).
  - `groundEffectDensity` (48 default; 64 per Bellular, 256 max). `groundEffectDist` (200, max 500).
  - `weatherDensity` (0-3). `ResampleAlwaysSharpen` (1 sharpens at 100% scale). `vsync` (0/1).
  - `maxFPS`, `maxFPSBk` (foreground/background caps). `GxApi` (`D3D12`; D3D11 only as a crash fallback).
  - `raid*` twins (e.g. `raidGraphicsViewDistance`) apply in raids and battlegrounds. Keep them one step lower
    for CPU headroom.
- **Unverified encodings:** `graphicsComputeEffects`, `graphicsSSAO`, `graphicsShadowQuality` and `giQuality` /
  `graphicsLightMode` are menu indices. Set them in the menu, then run `diff` to learn the mapping.
- **Known issue:** a beta "thermal state" bug capped fps at 60 (`Logs\gx.log`: "Imposing FPS cap of 60 FPS"). Fix
  by switching to D3D11.

## Call of Duty (2024+ IW/Treyarch engine: BO6, BO7, MW4)
- **Config:** `%LOCALAPPDATA%\Activision\Call of Duty\players\s.1.0.cod<NN>.txt`, format `cod`.
  - Entries look like `Name@N;h1;h2 = value // one of ...`. The script validates values against the listed
    choices. Entries can't be added.
  - Per-profile gameplay file: `players\<id>\g.cod<NN>.1.0.l.txt`.
- **Grainy hair, fire and smoke next to sharp textures** = spatial AA (`AATechniquePreferredMP = SMAA`) and/or
  `VRS@0 = true`. Fix with `AATechniquePreferredMP = FSR AA`, `AMDFidelityFX@1 = FSR 4`, `VRS@0 = false`.
- **Upscaling:** `AMDSuperResolution2Quality` is one of Ultra Performance, Maximum Performance, Balanced,
  Maximum Quality (= Quality), Native Resolution (= FSR 4 Native AA). `ResolutionMultiplier` stays 100.
- **Latency/caps:** `AmdAntilag2@0 = true`. `CapFps@0 = true`, `MaxFpsInGame@0 = <cap>`. `VSync@0 = disabled`.
- **Kill list:** `MotionBlur@0 = Off`, `WeaponMotionBlur@0 = false`, `EnableVelocityBasedBlur@0 = false`,
  `DofEnable@0 = Off`.
- **Costs:** shadow map resolution, volumetrics Very High, RT (`DxrMode`) and SSR High are the main levers.
  Textures are free on 16 GB.
- **Anti-cheat:** Ricochet (`randgrid.sys`, secure attestation). OptiScaler: never. The driver FSR 4 / ML FG
  override is fine.

## Forza Horizon 6
- **Config:** `%LOCALAPPDATA%\ForzaHorizon6\LocalStorage_Shared\ForzaUserConfigSelections\UserConfigSelections`,
  format `forza` (`<option id="X" value="N"/>` menu indices, plus low-level elements).
- **Verified:** `MotionBlurAmount` (0 = off). `EnableHDR` (0/1).
- **Unverified indices:** ShadowQuality (menu: Off, Low, High, Ultra, Extreme), LensEffects, FrameRate,
  FSR3Mode, VolumetricFogQuality, CarLOD, GeometryQuality, SSRQuality, SSGIQuality and RTGIQuality. Set them in
  the menu, then `diff`.
- **TechSpot/Wccftech optimised (non-RT):**
  - FSR 4 AA or FSR 4 Quality. Car LOD High. Environment geometry Ultra (>8 GB). Car reflections Ultra.
  - SSR High. Shadows Ultra. Night shadows Ultra. SSGI Medium. Shader Extreme. Particles Ultra. Volumetric fog High.
  - About +15% over Extreme. RTGI High→Medium is +33%. RT adds 2 GB+ VRAM.
- **CPU:** at 120+ fps the bottleneck is the CPU memory subsystem. Shader compilation stutter fades after about
  30 min. AMD stutter fixes: lower environment textures, toggle ReBAR, reset the shader cache.
- **Upscalers:** FSR 4/4.1 native, no FSR FG at launch (OptiScaler `dlssg→fsrfg` possible offline, but Forza has
  online features: skip).

## Assassin's Creed Black Flag Resynced (Anvil, 2026)
- **Config:** `%USERPROFILE%\Documents\Assassin's Creed Black Flag Resynced\ACBlackFlag.ini`, format `ini`.
  - `[Display]`: HDREnabled, VSyncMode, DisplayIndex (the add-game display-index trick).
  - `[Feature]`: frame_generation_type, framerate_limiter (0/1), framerate_target, sharpness_factor (0-1),
    upscaler_mode, upscaler_type.
  - `[Scalability] Profile=pc_<preset>`, `[Scalability_Custom]` per-setting indices.
- **Verified:** `framerate_limiter`, `framerate_target`, `sharpness_factor`, `HDREnabled`.
- **Unverified:** the `upscaler_type` numbers (9 seen in one install, meaning unknown) and the `[Scalability_Custom]` indices.
- **Wccftech optimised:**
  - RT Extended, RT quality Medium, BVH Ultra High. Character Very High. Hair strands "All characters High".
    Post effects Very Low. Particles Very High. Water High.
  - Loading distance Medium. Geometry High. Screen-space effects Medium. Light Medium. Shadows High.
    Clouds Ultra High. Fog High. Terrain Ultra High.
  - Non-RT gains about 47% over Ultra High+RT. Optimised RT gains about 24%. RTGI costs 8-10%, RT reflections 7-8%.
- **Upscalers:** FSR 4.1 and FSR FG native. HDR is good. FG needs a stable 50-60 base first.
