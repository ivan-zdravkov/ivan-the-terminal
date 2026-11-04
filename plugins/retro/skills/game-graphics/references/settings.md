# Graphics settings: what they do, what they cost, what to do with them

These are typical costs for one step down from the top setting, at 1440p, on a GPU-bound mid/high-range card.
They are pooled from Digital Foundry, TechSpot/Hardware Unboxed and TechPowerUp optimised-settings work, and they
vary per game. A game's own reference (`games.md`, or research) wins over this table.
- **Value** says how much you'd notice the drop in normal play.
- **Rule** is the default the planner applies before the player's profile adjusts it.

## Resolution, AA and upscaling (biggest levers)
| Setting | What it does | Cost | Value | Rule |
|---|---|---|---|---|
| Render resolution / scale | internal pixel count; everything scales with it | 100%→67% ≈ +40-70% fps | high | keep 100% unless an ML upscaler replaces it; never below 75% without one |
| Anti-aliasing: TAA / FSR AA / DLAA / XeSS AA | temporal AA; resolves the dithered hair, foliage, fire and smoke modern engines rely on | TAA ~2%, ML AA 5-10% | very high | always use a temporal AA. On RDNA 4, FSR 4 Native AA is the best one when there is headroom |
| SMAA / FXAA / CMAA (spatial) | edge-only AA, no temporal resolve | ~1% | low | avoid in modern games: dithered effects stay grainy and shimmer ("1998 hair next to sharp textures") |
| MSAA 2-8x | geometric AA (forward renderers, older or MMO engines) | 20-40% at 8x | medium | 2x at most, plus CMAA2 if offered |
| Upscaler: FSR 4 / 4.1 (ML) | ML upscaler, RDNA 4 (FP8) | Quality ≈ +35-45% vs native | high | the first trade on RDNA 4: Quality, then Balanced. Often looks better than native+TAA |
| FSR 3.1 / 2 (analytic) | non-ML upscaler | same gain as FSR 4 | low-medium | lift it to FSR 4 (driver override or OptiScaler); use native FSR 3.1 only below RDNA 4 |
| XeSS (DP4a) / DLSS | vendor upscalers | — | — | on AMD, feed them to OptiScaler → FSR 4 instead of using them directly |
| Dynamic resolution | resolution follows a frame-time target | — | medium | off when a fixed FSR 4 mode holds the target, on as a safety net for CPU-spiky games |
| Sharpening (CAS/RCAS/game slider) | counters temporal softness | ~0 | taste | 0.2-0.4 for "crisp but natural"; 0 with FSR 4 Native AA if it already looks sharp |
| VRS (variable rate shading) | shades parts of the screen at reduced rate | +3-8% | negative | OFF: blocky, smeary shading on particles and hair, worst on OLED contrast |

## Lighting and shadows
| Setting | What it does | Cost | Value | Rule |
|---|---|---|---|---|
| Shadow quality / resolution | shadow-map resolution and filtering | Ultra→High 5-15% | low | High. Ultra only with spare headroom |
| Shadow distance / cascades | how far dynamic shadows reach | 3-10%, partly CPU | medium | High; costs CPU in open worlds |
| Contact / screen-space shadows | small-scale shadowing | 2-4% | medium | On/High |
| Ambient occlusion (SSAO/HBAO/GTAO) | darkens creases for depth | 3-8% | high | High; drop to medium before off |
| Global illumination (SSGI / software Lumen) | bounced light | 10-25% | high | High; Medium is often near-identical |
| RT global illumination | traced bounce light | 25-50% | high (transformative in some games) | only when transformative and the tier target still holds |
| RT reflections | traced reflections | 15-35% | medium | off in shooters/MMOs; on in showcase games |
| RT shadows / RT AO | traced shadows / AO | 10-30% | low | off |
| Path tracing | full RT | 50-75% | very high | not on mid-range RDNA 4 except at 60 fps with FG in slow games |
| Ray regeneration / reconstruction (FSR RR, DLSS RR) | ML denoiser for RT | — | high | use FSR Ray Regeneration whenever RT is on and the game offers it |
| Volumetric fog / lighting / clouds | light shafts, fog, clouds | Ultra→High 5-20% | medium | High. One of the most over-priced Ultra settings |
| Light quality / secondary lights | count/quality of local lights | 5-25% | medium-high | High; check per game (WoW's Secondary Lighting is a known hog) |
| Bloom | glow around bright areas | ~1% | taste | on, lowered if blinding |

## Geometry, textures and world
| Setting | What it does | Cost | Value | Rule |
|---|---|---|---|---|
| Texture quality | texture resolution (VRAM, not fps) | ~0% if VRAM fits | high | max on 16 GB cards; drop one step on 8 GB at 1440p |
| Texture filtering (anisotropic) | sharp textures at angles | ~0-1% | high | 16x |
| View / draw distance, LOD | how far objects render, pop-in | 3-15%, mostly CPU | high | High-Ultra. Players notice pop-in more than shadow sharpness |
| Foliage / vegetation density | grass and trees | 5-15% GPU+CPU | medium | High |
| Geometry / mesh detail (Nanite, micropolygon) | model complexity | 3-10% | medium | High; Ultra in games built around it |
| Tessellation | adds surface detail | 2-6% | low | Near/High |
| Terrain / deformation (snow, mud) | ground detail | 2-5% | low | Medium-High |
| Crowd / NPC density | number of people/cars | CPU | medium | Medium-High on 6-core CPUs |
| Physics / destruction / cloth | simulated detail | CPU | low | Medium |

## Effects
| Setting | What it does | Cost | Value | Rule |
|---|---|---|---|---|
| Particles quality / resolution | fire, smoke, sparks; low = half/quarter-res buffers | 3-10% | high (low looks pixelated) | High. Never low-res particles |
| Hair quality / strands | strand hair vs cards | 3-10% (strands 10%+) | high for close-ups | High; strands on for main characters |
| Screen-space reflections | cheap reflections | 3-10% | medium | Medium-High (High on water-heavy games) |
| Water / ocean quality | waves, reflections, refraction | 2-10% | medium | High, Medium in water-light games |
| Subsurface scattering | skin translucency | 1-3% | medium | On |
| Decals / persistent damage | bullet holes, marks | ~1-2% | low | On |
| Shader quality / material detail | material complexity | 3-8% | medium | High |
| Reflection probes / cubemaps | baked reflections resolution | 1-3% | low | Medium-High |

## Post-processing (taste; the profile's kill list wins)
| Setting | What it does | Cost | Value | Rule |
|---|---|---|---|---|
| Motion blur (camera, per-object, radial/velocity) | blur in motion | 1-3% | negative for most | OFF, every variant |
| Depth of field | background/foreground blur | 1-4% | negative for most | OFF (gameplay and cutscenes when separable) |
| Film grain | noise overlay; fights upscalers | ~0 | negative | OFF |
| Chromatic aberration | colour fringing at edges | ~0 | negative | OFF |
| Vignette | darkened corners | ~0 | negative | OFF |
| Lens flare / dirt / distortion | camera-lens effects | ~0-1% | negative | OFF |
| Head bob / camera shake | comfort | 0 | negative | OFF or minimum |

## Display and latency
| Setting | Rule |
|---|---|
| Window mode | borderless/fullscreen-windowed (Windows flip model); exclusive only if a game misbehaves |
| VSync | off with FreeSync/VRR plus a frame cap below refresh; on only if a game tears or for menus |
| Frame cap | the profile's tier cap, using the in-game limiter (better pacing), else Adrenalin FRTC. With FG, cap the output and keep the base ≥ 60 |
| Anti-Lag 2 / Reflex | on whenever offered (Anti-Lag 2 on AMD); always with frame gen |
| Frame generation | single-player only and base ≥ 60: FSR 3.1.4+ FG → ML FG via the driver (Redstone) > OptiScaler FSR FG > AFMF (driver, any DX11/12) > Lossless Scaling |
| HDR | on if the game's HDR is good (peak brightness set to the panel, paper white ~200 nits). SDR if it's washed out or crushes black. RenoDX/Special K can fix bad HDR in single-player games |
| Field of view | wider for first-person (90-105 horizontal); costs some CPU/GPU |

## Order of cuts when below target
1. Ultra → High on volumetrics, shadows, light quality and GI. That's 20-35% for almost nothing visible.
2. Upscaler to FSR 4 Quality (if still native).
3. RT off (if it's not the game's showcase).
4. Single-player only: frame gen (if base ≥ 60).
5. Reflections, foliage density, crowd density (CPU-bound cases).
6. FSR 4 Balanced.

Never cut: texture quality (VRAM permitting), anisotropic filtering, temporal AA, particle resolution.
Never add: motion blur, VRS, a spatial-only AA in a game built for TAA.

## CPU-bound signs (6-core, non-X3D CPUs)
- GPU usage under ~90% at the target.
- fps doesn't change when the resolution drops.
- Dips in cities, raids, crowds and fast traversal.

Lower view distance, crowd and physics settings, use frame gen (single-player), and accept the tier's lower bound.
Upscaling doesn't help CPU-bound games.
