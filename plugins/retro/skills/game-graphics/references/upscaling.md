# Upscaling and frame generation on AMD: which path, which tool

## Decision ladder per game (RDNA 4)
1. **Native FSR 4 / 4.1 in the menu** (CoD, Forza Horizon 6, AC Black Flag Resynced, most 2025+ AAA): use it.
   - Native AA mode if there's headroom, else Quality.
2. **FSR 3.1.x DLLs present** (`amd_fidelityfx_upscaler_dx12.dll` / `amd_fidelityfx_dx12.dll`): the driver's
   FSR 4 upgrade lifts it. Adrenalin → Gaming → the game → "AMD FSR Upscaling: FSR 4". This works only for games
   on AMD's whitelist, and it is the only safe route for online games.
3. **Single-player, no anti-cheat, DLSS / XeSS / FSR 2-3.0 only**: OptiScaler (below) → FSR 4.
4. **Nothing temporal at all**: native TAA plus RIS (Radeon Image Sharpening), or RSR (driver spatial upscale,
   fullscreen only). Avoid FSR 1.

## Frame generation (single-player only, base ≥ 60, Anti-Lag 2 on)
1. **Game's FSR 3.1.4+ FG**: the driver upgrades it to ML frame gen (FSR Redstone, Adrenalin 25.12.1+, RX 9000, DX12).
2. **Game has DLSS-FG (Streamline) only**: OptiScaler, `FGInput=dlssg`, `FGOutput=fsrfg` (RDNA 4 gets FSR4-FG).
3. **Game has no FG**: OptiScaler OptiFG, `FGInput=upscaler`, `FGOutput=fsrfg`.
   - Needs the upscaler enabled through OptiScaler.
   - The HUD may smear: try HUDFix in the overlay. It's a last resort.
4. **Any DX11/12 game, no mods**: AFMF (Adrenalin → the game → AMD Fluid Motion Frames).
   - Driver-level, no anti-cheat risk.
   - Turns off during fast motion. Fullscreen-ish modes only.
5. **Anything at all** (emulators, old games, video): Lossless Scaling, paid on Steam.
   - Highest latency, most artifacts.
   - Use it when nothing above applies.
- **Never use FG in:** competitive or online shooters, or games below 60 base (FG doubles the judder and adds
  latency). Not on Moonlight streams below 60 base either.

## OptiScaler (github.com/optiscaler/OptiScaler)
Open-source proxy DLL. It intercepts a game's DLSS / XeSS / FSR 2-3 calls and feeds them to FSR 4 (or another
backend), and can add FSR FG. Releases since 0.9 bundle fakenvapi and Nukem's dlssg-to-fsr3.

- **Install:** `graphics.py optiscaler install <game dir>`. It downloads the latest stable release, checks GitHub's
  sha256 digest and copies everything next to the main exe (Unreal: the `*-Win64-Shipping.exe` folder).
  - `OptiScaler.dll` gets the first free proxy name: dxgi, winmm, version, dbghelp, d3d12, wininet, winhttp.
  - Files it overwrites (e.g. the game's own `amd_fidelityfx_*.dll`) are backed up and restored on `remove`.
  - It refuses games with anti-cheat or online-only games. `--force-offline` exists for a human who knows a game
    is offline single-player (the headless guard blocks it).
- **Overlay:** Insert (Alt+Insert if it closes at once). Page Up shows the fps overlay. Pick the upscaler, then
  "Save INI", and restart for FG changes.
- **Ini keys** (`--set Section.Key=Value`):
  - `Upscalers.Dx12Upscaler=fsr31` (fsr31 = FSR 3.1 path, upgraded to FSR 4 on RDNA 4).
    `Upscalers.Dx11Upscaler=fsr31_12` (DX11 via 11-on-12, needed for FSR 4).
    `Upscalers.VulkanUpscaler=fsr31_12` (Vulkan via VK-on-12, needed for FSR 4).
  - `FSR.Fsr4Update=true` (auto on RDNA 4). `FSR.Fsr4Preset=0` for Native AA (1 Quality, 2 Balanced, 3 Performance).
  - `FrameGen.Enabled=true`, `FrameGen.FGInput=dlssg|fsrfg|upscaler|nukems`, `FrameGen.FGOutput=fsrfg|xefg|nukems`.
  - `Sharpness.OverrideSharpness=true`, `Sharpness.Sharpness=0.3`.
  - `Spoofing.Dxgi=false` turns off GPU spoofing if a game misbehaves with it.
- **Game input:** set the game to DLSS (spoofed through fakenvapi), XeSS or FSR. OptiScaler swaps it underneath.
  The overlay shows the active backend. Unreal games with OptiFG and DLSS: `r.NGX.DLSS.DilateMotionVectors=0` in
  Engine.ini.
- **Compatibility:** wiki "Compatibility List", "FSR4 Compatibility List" and "Known Issues". Check them before
  installing into a new game.
- **Conflicts:** another proxy DLL (ReShade as dxgi.dll, crack loaders as winmm.dll, Special K). The installer never
  overwrites a proxy it didn't place. For ReShade, rename it per the wiki page "Compatibility with other mods".
- **Updates:** `graphics.py optiscaler update` moves every install to the latest stable release and keeps its ini
  overrides. Game updates can delete the files, so re-run install when `scan` shows a game as `changed`.

## Driver features (Adrenalin, per game or global)
Adrenalin keeps its profiles in a binary database, so scripts can't set them. They go in the report as one-time
clicks.
- **Global:** FreeSync on. Anti-Lag 2 on. Radeon Chill, Boost, Enhanced Sync and Image Sharpening off (games
  sharpen themselves). Wait for vertical refresh: "Off, unless application specifies". Texture filtering: standard.
- **Per game when needed:** "AMD FSR Upscaling" → FSR 4 (3.1 games); "AMD FSR Frame Generation" → ML FG (3.1.4+
  FG games); AFMF on for FG in games without it; FRTC as a cap when a game has no limiter.
- **HDR:** Windows HDR on (Win+Alt+B toggles it); run the Windows HDR Calibration app once per panel. Turn HDR off
  in games whose HDR is broken.
