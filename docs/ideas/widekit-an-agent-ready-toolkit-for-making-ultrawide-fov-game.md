# WideKit: an agent-ready toolkit for making ultrawide/FOV game fixes

## Problem & opportunity

Many PC games still ship locked to 16:9. Players on 21:9 and 32:9 monitors get black bars, a narrow vertical FOV and a HUD stretched across the screen. Every one of those games needs its own fix. Each fix involves the same steps:

1. Find the aspect-ratio check, the FOV value and the HUD transform in the game's binary.
2. Write an AOB pattern that survives game patches.
3. Hook or patch the code safely.
4. Package it all with a DLL proxy loader, an ini, hotkeys and an installer.

The people who do this well rebuild that scaffolding for every game. Lyall has published fixes for "80+ games" and has 76 repos on Codeberg. Those fixes are open source, but each one is its own C++ ASI project; there is no shared toolkit anyone can build on. Flawless Widescreen is closed and works through per-game plugins, which break when a game patches.

AI-assisted reverse engineering also became workable in 2026. GhidraMCP, ReVa and pyghidra-mcp let Claude decompile, cross-reference and rename things in Ghidra. The write-ups show the weak points:

- The setup chain is fragile.
- The servers can't patch bytes.
- Agents state wrong conclusions with confidence.

There is also no domain knowledge about what an ultrawide fix looks like. A general RE agent doesn't know that it should look for `1.777778f` (`0x3FE38E39`), clamp code around a resolution struct, or a HUD orthographic projection.

**The opportunity:** take what is shared across the developer's three shipped fixes (widereign, dh2013-ultrawide, and the game-modding skill from dh2-coop) and package it as:

1. **WideKit**, an open-source C++ framework that already contains the boring 80% of a fix.
2. **A Claude Code plugin** with a skill and pinned Ghidra MCP recipes. It turns "make this game ultrawide" into a repeatable workflow that checks every finding against the binary before it is used.

The audience is proven, new demand keeps arriving with each 16:9-locked release, and nobody is building an opinionated pipeline for this one high-demand type of fix.

## Target users

1. **The developer, first.** Turnaround on a new fix should drop from days to an evening. WideKit has to pay off on fix #4 before it matters to anyone else.
2. **Existing fix authors and hobby modders.** These are people who can write C++ and use Ghidra, and who are tired of copying loader, ini, hook and installer code between projects. They want a library, not a framework that dictates their workflow.
3. **Agent-curious modders.** These people know some C++, have a Claude Code (or Codex/Gemini CLI) subscription, own an ultrawide monitor and have a game they want fixed. They need the skill to explain each step and to stop them before they go somewhere unsafe.
4. **End players, indirectly.** They never see WideKit. They get a fix with a one-click installer and a consistent ini and log layout across fixes. That consistency is what makes "built with WideKit" fixes trustworthy and easy to support.

## Market evidence

- **The audience is large and organised.** WSGF documents 2,300+ games, and community contributors have built free fixes for 600+ titles that don't support modern displays. WSGF is self-funded at about $150/month and asks for Patreon support while keeping fixes free. ([WSGF Patreon](https://www.patreon.com/wsgf/about))
- **Patreon funding for open fixes works.** Lyall offers credit on releases, behind-the-scenes posts, early-access builds and a say in what gets fixed next, while "all work stays open and free". This is the model WideKit would copy. ([Lyall on Patreon](https://patreon.com/Wintermance))
- **Top authors have no shared toolkit.** Lyall's Codeberg has 76 public repos. Each fix (FF7RemakeFix, Nioh3Fix, ACShadowsFix, DeathStranding2Fix…) is a separate C++ ASI plugin. ([codeberg.org/lyall](https://codeberg.org/lyall))
- **The incumbent is fragile.** Flawless Widescreen works through per-game plugins. Users report plugins that untick themselves after game patches, crashes on launch and partial fixes. Its own site describes it as a tool to "simplify craft fixes and patches" for UltraWide/Surround/Eyefinity. ([flawlesswidescreen.org](https://www.flawlesswidescreen.org))
- **New demand keeps arriving.** In Nightreign's "No ultrawide support?" thread (May 2025), a player says the black bars stop them buying the game, others note the game renders behind the bars, and people point to a community ultrawide fix. The same thread complains about the 60 fps cap and notes that EAC rules out modded online play. ([Steam discussion](https://steamcommunity.com/app/2622380/discussions/0/597402319036902420))
- **Agent-driven RE works, but the chain is fragile.** In Quesma's experiment the chain was Claude → GhidraMCP → Ghidra extension → Ghidra, four failure points. The MCP "don't have write access", so the patch was applied with `dd`. Claude confidently misidentified the game, and tool calls took about 30 s each. The author's verdict on setup: "you `git clone` and hope for the best". ([Quesma](https://quesma.com/blog/ghidra-mcp-unlimited-lives/))
- **The general RE tools are maturing but don't patch.** ReVa is built for Claude Code: a single `claude mcp add` command, a plugin marketplace with triage and analysis skills, and a headless mode. It needs Ghidra 12.0+, and Ghidra 12.2+ needs Java 25. Its README doesn't mention byte patching. ([ReVa README](https://cdn.jsdelivr.net/gh/cyberkaida/reverse-engineering-assistant@main/README.md))
- **pyghidra-mcp has the same gap.** It is headless-first, installs with `uvx`/Docker, analyses whole projects, and can rename, retype and comment. It lists no byte-patch tool. WideKit fills that gap with its own write-capable scripts. ([pyghidra-mcp](https://github.com/clearbluejar/pyghidra-mcp))
- **The building blocks are permissively licensed.** Ultimate ASI Loader (MIT) proxies dinput8, version, winmm, dxgi and more, and chain-loads `<name>Hooked.dll`. SafetyHook (BSL-1.0, C++23) pauses threads while it installs hooks and fixes up relocated instructions. WideKit can wrap both instead of reinventing them. ([Ultimate ASI Loader](https://github.com/ThirteenAG/Ultimate-ASI-Loader), [SafetyHook](https://github.com/cursey/safetyhook))
- **Hosting is a real risk.** PC Gamer reported that a prominent ultrawide-fix author's whole GitHub library was taken down without explanation. Lyall's work continues on Codeberg. ([PC Gamer](https://www.pcgamer.com/gaming-industry/an-mvp-of-ultrawide-patches-for-triple-a-games-just-had-their-entire-library-nuked-from-github-and-nobody-seems-to-know-why), [codeberg.org/lyall](https://codeberg.org/lyall))

## SEO & AI-agent visibility plan

**Search (people):**
- **Docs site** (GitHub Pages, mirrored on Codeberg) with a tutorial series under one hub: "How to make an ultrawide fix". Planned parts:
  - Part 1: Finding the aspect check
  - Part 2: Hor+ FOV maths
  - Part 3: HUD relayout
  - Part 4: Shipping an installer
  - Plus "Ultrawide fix with Claude and Ghidra" as a parallel agent track
- **Target queries:** `how to make an ultrawide fix`, `ultrawide fix tutorial`, `hor+ fov patch`, `aob pattern scan c++`, `dinput8 proxy dll`.
- **One page per fix:** `/fixes/<game>` with a "[Game] ultrawide fix" title, supported resolutions, a before/after screenshot pair from the test harness (21:9 and 32:9), ini docs and a download link. These pages are the long tail, and each new fix adds one.
- **Cross-posting:** every fix README and release note links "Built with WideKit", and every fix is listed on WSGF and PCGamingWiki (as the authors do today).
- **Worked case study:** one real fix (the Nightreign HUD-to-edges mode is a good candidate) written up end to end with the agent transcript. This is the shareable piece for r/ultrawidemasterrace, the WSGF forums and HN.

**AI agents:**
- **Claude Code plugin marketplace:** `claude plugin marketplace add <owner>/widekit` installs the `widekit` plugin. The repo layout follows the stash-plugin packaging.
- **Portable skill:** the skill is plain markdown with scripts, and the repo also ships an `AGENTS.md`/Gemini CLI extension manifest, so Codex and Gemini users can use the same workflow. This fits the developer's preference for tools that aren't tied to one vendor.
- **`llms.txt` and `llms-full.txt`** at the docs root:
  - the framework API: `wk::scan`, `wk::hook`, `wk::cfg`, `wk::fov`, `wk::hud`, `wk::log`
  - the fix template
  - the skill's phase checklist
- **MCP listings:** list the "WideKit Ghidra recipe" (pinned server and versions, plus WideKit's write/patch scripts) on mcpservers.org and glama. The description is specific: "Ghidra MCP setup for game ultrawide/FOV fixes."
- **Discoverable keywords:** the skill's `description` front-matter names the trigger phrases ("ultrawide fix", "remove black bars", "FOV patch", "pillarbox", "hor+"). When a user asks an assistant to "make an ultrawide fix for X", the skill is then what it picks.

## Proposed solution & scope

WideKit has three parts:

1. **`widekit` (C++ library and fix template).** A static library plus `cmake`/`build.bat` scaffolding, so a new fix is about 150 lines of game-specific code.
2. **`widekit-agent` (Claude Code plugin).** A skill, Ghidra MCP recipes, Ghidra scripts for verification and patching, and a hashing and manifest step.
3. **`widekit-shot` (test harness).** It launches a game at 16:9, 21:9 and 32:9, takes screenshots and checks them for pillarboxing, stretch and HUD placement.

Monetisation stays light and comes later. The toolkit is free and open, and "built with WideKit" links do the marketing. A Patreon for faster releases of new fixes and early access is an optional later milestone, not a launch requirement.

### In scope

- **Proxy loader:** a `dinput8.dll` / `version.dll` / `winmm.dll` / `dxgi.dll` proxy that chain-loads the original or an existing `<name>Hooked.dll`. It can coexist with Ultimate ASI Loader, so the fix also ships as a plain `.asi`.
- **Pattern scanning:**
  - AOB scanning with wildcards, section filtering (`.text`) and RIP-relative resolution.
  - Multi-candidate patterns with a "must match exactly once" mode.
  - Clear log lines when a pattern misses after a game patch.
- **Safe hooks:** a SafetyHook wrapper for inline and mid-function hooks, plus `wk::patch` byte writes with `VirtualProtect`, restored on unload.
- **Config and hotkeys:**
  - an ini schema with typed keys and defaults
  - live reload
  - hotkey bindings using virtual-key codes, polled or via a window-procedure hook
  - FOV offset persistence (the widereign F7/F8 model)
- **Aspect and FOV maths:**
  - Hor+ conversion (vertical FOV fixed, horizontal from aspect)
  - Vert- correction
  - helpers for 16:9 → N:9 scaling
  - tested against reference tables
- **HUD relayout helper:**
  - modes: centred 16:9 (default), stretch-safe, and "HUD to edges" for 21:9/32:9
  - anchor maths for left/right/centre-anchored elements
  - a per-element override list in the ini
- **Logging:** a rotating log next to the ini that records:
  - pattern hits and misses with module and offset
  - the game version and exe SHA-256
  - all settings
- **Installer kit:**
  - a PowerShell full-window terminal UI, generalised from widereign
  - finds Steam libraries via `libraryfolders.vdf` and resolves an app ID to an install path
  - copies files and records a manifest
  - a clean uninstall that removes only the files in the manifest
  - creates shortcuts
- **Fix template:** `widekit new <game>` scaffolds the repo with the ini, README, a release `package.bat` and a GitHub/Codeberg Actions build.
- **Claude Code skill:**
  - a phased workflow: triage → find aspect check → find FOV → find HUD transform → write patterns → implement → screenshot-verify → package
  - per-phase checklists, known code shapes, and "stop and ask" gates
- **Ghidra MCP recipe:**
  - pinned Ghidra, Java and MCP server versions (pyghidra-mcp headless as the default, ReVa as the GUI alternative)
  - a one-command setup script with a self-test
  - WideKit Ghidra scripts for byte patching, uniqueness checks for AOB patterns, and float-constant search
- **Grounding and hashing:**
  - every finding is stored in a `findings.json` with its address, the bytes, the exe SHA-256 and the tool call that produced it
  - the skill refuses to write a pattern that hasn't been re-verified against the binary
- **Screenshot harness:**
  - sets the resolution through the game's config or a borderless window size
  - takes captures, then runs simple checks (black-bar detection on the edge columns, the aspect of the main content)
  - writes a contact sheet for the README
- **Docs and visibility:** docs site, `llms.txt`, three ported reference fixes and one tutorial series.

### Out of scope

- Anything that bypasses or disables anti-cheat for online play. The skill refuses when it detects EAC, BattlEye or Vanguard unless the game has an official offline mode (the widereign approach: launch offline only, leave Steam's Play button untouched).
- DRM circumvention, and redistributing game files or patched executables.
- A GUI app like Flawless Widescreen. WideKit is a library plus a terminal installer.
- Unity/IL2CPP and Unreal-specific frameworks in v1. They get their own guides later (BepInEx, UE4SS cover these). v1 targets native C++ engines.
- Multi-monitor Surround/Eyefinity beyond 32:9 single-display, and VR.
- Linux/Proton-native builds. Proton should work through the DLL override, but it isn't tested in v1.
- Patreon infrastructure, paywalled builds and licence keys.

## User stories

1. As the developer, I run `widekit new grimwood` and get a building `.asi`/`dinput8.dll` with ini, logging, hotkeys and installer already wired up, so I only write the game-specific patches.
2. As the developer, I tell Claude "make Grimwood ultrawide". The skill walks the agent through triage and proposes candidates for the aspect check, each with its address, decompiled context and exe hash. I approve one before it writes any code.
3. As a modder, I run `widekit-agent setup` once and get a working, pinned Ghidra and MCP stack. A self-test decompiles a sample binary, so I know the chain works before I start.
4. As a modder, when the agent claims "this is the FOV", it has to show the bytes it read and a uniqueness check for its pattern. A wrong claim is caught before it becomes code.
5. As a fix author, after a game update my log says `pattern 'aspect_clamp' 0 hits (exe sha 3f2a…)`. `widekit-agent repattern` then finds the new site, using the old findings as a guide.
6. As a fix author, `widekit-shot` produces 21:9 and 32:9 screenshots and fails if black bars remain, so I can test a release without my own 32:9 monitor (borderless at the target size).
7. As a player, I double-click `Install.bat`. It finds my Steam install, installs the fix and an uninstaller, and leaves the game's files and saves untouched.
8. As a player, I press F7/F8 to change the FOV, and the setting persists. The keys and ini layout are the same in every WideKit fix.
9. As a Codex or Gemini CLI user, I can follow the same skill through `AGENTS.md`, without Claude-specific features.
10. As a reader of the tutorial, I can reproduce a fix end to end from the published transcript and findings file.

## Technical approach

**Stack**
- **C++23, MSVC (VS 2022+ toolset), CMake**, with `build.bat` for people who don't want to use CMake. x64 first; x86 is a build option.
- **Dependencies, vendored or fetched by CMake:**
  - SafetyHook with Zydis (BSL-1.0 / MIT)
  - spdlog (MIT), or a small built-in logger to keep the DLL small; decide in M1
  - a small ini parser (inipp-style, header-only)
  - no Ultimate ASI Loader code compiled in: WideKit has its own proxy and stays compatible with ASI Loader
- **Installer:** PowerShell 5.1 (ships with Windows), generalised from widereign's `kit/` and `tools/`, so there's no runtime to install.
- **Agent side:**
  - a Claude Code plugin (skill markdown, slash commands, hooks)
  - Python 3.12+ scripts run with `uv`
  - Ghidra 12.x with a pinned Java 21/25
  - pyghidra-mcp (headless, default) or ReVa (GUI)
  - WideKit's own Ghidra/pyghidra scripts for the write and verification operations the MCP servers lack
- **Screenshot harness:**
  - Python with `dxcam`/Windows Graphics Capture for captures
  - Pillow/numpy for bar detection
  - per-game config shims to set the resolution

**Architecture**

```
widekit/
  core/      proxy (dinput8/version/winmm/dxgi exports + chain-load), init thread, module info, exe hash
  scan/      AOB parser, section scan, RIP resolve, unique-match assert
  hook/      SafetyHook wrapper, mid-hook register access, byte patch with restore
  cfg/       typed ini schema, hotkeys, live reload
  view/      aspect + Hor+/Vert- FOV maths, HUD anchor/relayout helpers
  log/       rotating log, pattern hit/miss report
  template/  new-fix scaffold, package.bat, CI workflow
  kit/       PowerShell installer TUI, Steam discovery, manifest uninstall
agent/  (Claude Code plugin)
  .claude-plugin/plugin.json, marketplace.json
  skills/ultrawide-fix/SKILL.md + phases/*.md + known-shapes.md
  commands/ widekit-setup, widekit-find, widekit-repattern, widekit-verify
  recipes/ ghidra-pinned.toml, setup.ps1/.sh, selftest
  ghidra_scripts/ patch_bytes, pattern_unique, find_float_consts, export_findings
  AGENTS.md, gemini-extension.json
shot/   widekit-shot harness
docs/   site, llms.txt, tutorials, /fixes/<game>
```

A fix is a single `fix.cpp` that declares its patterns and patches through a small API:

```cpp
WK_FIX("Grimwood", { .proxy = wk::Proxy::Dinput8 }) {
  auto clamp = wk::scan::unique("F3 0F 10 05 ?? ?? ?? ?? 0F 2F C1 76 ??");
  wk::patch::nop(clamp + 11, 2);                        // remove 16:9 clamp
  wk::hook::mid(wk::scan::unique("..."), [](auto& r){   // FOV
    r.xmm0.f32[0] = wk::view::horplus(r.xmm0.f32[0], wk::aspect());
  });
  wk::hud::center16x9_or_edges(cfg.hud_mode, /*matrix site*/ ...);
}
```

**How grounding works.** Weak context and made-up claims are the main reported problems, so the skill is built around a findings ledger. Every MCP read that supports a claim is recorded in `findings.json` with the exe SHA-256, the address, the raw bytes and the decompiled snippet. A Claude Code `PreToolUse`/`Stop` hook blocks writes to `fix.cpp` that use a pattern without a verified entry. `pattern_unique` must report exactly one match in `.text`. The game is identified from the Steam app ID and the exe's version resource, never guessed. The phase files encode domain knowledge:
- search float constants such as 1.777…, 0.5625 and 16/9 doubles
- `GetSystemMetrics`/`DXGI_MODE_DESC` and resolution-struct xrefs
- orthographic projection setups for the HUD
- common engine shapes

The skill also tells the agent to stop and ask the human at each phase gate.

**Reuse from existing repos**
- **widereign:**
  - proxy and launcher structure, the FOV hotkey and persistence system, and the ini layout (`fov_offset`/`fov_step`/`fov_min`/`fov_max`, VK codes)
  - the PowerShell full-window installer with Steam discovery and manifest-only uninstall
  - `build.bat`/`package.bat` and logging conventions
  - the offline-only/EAC-safe launch policy
  - the HUD-to-edges work becomes `wk::hud`
- **dh2013-ultrawide:** pattern-based patching and the FixUI HUD approach. These become `scan/` and `view/hud`, after reconciling the two repos' differences.
- **dh2-coop:** the existing game-modding skill and RE docs are the seed for `SKILL.md`, the phases and the known shapes. Its lessons are kept, and the ultrawide content is made the first-class path.
- **stash-plugin:** Claude Code plugin packaging (`plugin.json`, marketplace manifest, release flow).
- *Note:* only widereign's README was in the digest I had. The extraction plan for dh2013-ultrawide and dh2-coop is based on the card's description and should be confirmed in M0.

## Milestones / task breakdown

**M0: Extraction audit (2–3 days)**
- Diff widereign and dh2013-ultrawide module by module, and list what is shared, what diverges, and what is game-specific.
- Choose the licence. MIT is recommended, to match ASI Loader and the authors' minimal licences.
- Choose the repo layout. Set up a GitHub repo with a Codeberg mirror from day one.

**M1: Core library (1.5 weeks)**
- Proxy with chain-loading for dinput8/version/winmm/dxgi, tested alongside Ultimate ASI Loader.
- `scan`, `hook`, `patch` and `log` modules, with unit tests on synthetic PE buffers.
- `cfg` with typed schema, hotkeys and live reload; `view` maths with Hor+/Vert- tests against tables.
- **Exit:** widereign rebuilt on WideKit, with identical behaviour and ini compatibility.

**M2: HUD helper and installer kit (1 week)**
- `wk::hud` modes (centred 16:9, edges), generalised from widereign's HUD-to-edges mode.
- PowerShell kit: Steam library discovery by app ID, manifest install/uninstall, shortcuts, update-keeps-settings.
- `widekit new <game>` scaffold and CI build workflow.
- **Exit:** dh2013-ultrawide ported to WideKit.

**M3: Agent plugin and Ghidra recipe (2 weeks)**
- Pinned version matrix plus a `setup` script for Windows (primary) and Linux/WSL, with a self-test.
- Ghidra scripts: `patch_bytes`, `pattern_unique`, `find_float_consts`, `export_findings`.
- `SKILL.md` and phase files, ported from the dh2-coop skill; findings ledger and blocking hook.
- Slash commands: `/widekit-find`, `/widekit-repattern`, `/widekit-verify`.
- `AGENTS.md` and Gemini extension manifest.
- **Exit:** the agent re-derives widereign's aspect and FOV sites from scratch on a clean machine, with every claim in the ledger.

**M4: Screenshot harness (1 week)**
- Capture at 16:9/21:9/32:9 (borderless sizing for authors without the monitor); bar detection and content-aspect check; contact-sheet output.
- **Exit:** `widekit-shot` passes on both ported fixes and fails on the unpatched games.

**M5: First new fix and launch (1.5 weeks)**
- One new fix built with the agent workflow, timed and transcribed.
- Docs site, `llms.txt`, fix pages, tutorial parts 1–2 and the case study.
- Plugin marketplace release; MCP directory listings; WSGF, PCGamingWiki and Reddit posts.

**M6: Cadence (ongoing, optional)**
- Tutorial parts 3–4, a `repattern` workflow after game updates, x86 support.
- Patreon for early-access fixes and voting on which games come next, only if M5 shows demand.

## Success metrics

- **Speed:** a new native-engine fix goes from first look to a working 21:9 build in ≤ 1 evening (4 h) with the agent workflow. The developer's baseline is days.
- **Template size:** game-specific code in a WideKit fix is ≤ 200 lines; ported fixes lose ≥ 60% of their lines.
- **Grounding:** 0 patterns shipped without a verified ledger entry; < 10% of the agent's proposed candidates are rejected as wrong in the M3/M5 runs.
- **Setup:** `widekit-agent setup` plus the self-test succeeds on a clean Windows VM in ≤ 15 min, on ≥ 3 of 3 tries.
- **Repatch:** after a game update, `repattern` restores a broken fix in ≤ 30 min.
- **Adoption (6 months):**
  - ≥ 5 fixes by the developer and ≥ 3 by other authors with "built with WideKit"
  - 200+ GitHub stars
  - plugin installs tracked from marketplace and clone counts
- **Search:** the tutorial hub ranks on page 1 for "how to make an ultrawide fix"; fix pages bring in traffic from "[game] ultrawide fix" queries.
- **Agent visibility:** asking Claude Code, Codex and Gemini CLI "make an ultrawide fix for X" picks the skill when it's installed, and the `llms.txt` docs are cited by web-search assistants.
- **Optional:** if a Patreon launches, it covers hosting and tools within 3 months.

## Risks & open questions

- **Anti-cheat and ToS.** Fixes for online games with anti-cheat can lead to bans, and a toolkit that makes injection easy invites misuse. *Mitigation:*
  - the skill and the scaffold check for EAC/BattlEye/Vanguard and refuse
  - the docs require an offline launch path and no Steam Play-button changes
  - no anti-cheat bypass content, ever
- **Hosting takedowns.** An ultrawide-fix author's GitHub library was removed without warning. *Mitigation:* Codeberg mirror, release assets also on Nexus, and a docs site separate from GitHub.
- **Version drift in the RE stack.** Ghidra 12.2 needs Java 25, and MCP servers change fast. Pinning helps but goes stale. *Open question:* should the recipe ship a Docker image (pyghidra-mcp has one) as the reproducible default, given that most fix authors work on Windows?
- **Agent accuracy.** The ledger stops unverified patterns, but it can't stop a wrong *interpretation* of a verified address. The phase gates keep a human approving each finding; we need to measure how often the agent is wrong.
- **Engine diversity.** Native engines differ a lot. HUD fixes in particular are often per-element and hard to generalise. `wk::hud` may stay a set of helpers rather than a solution.
- **The harness needs the game running.** It requires an owned copy, a GPU and time per resolution, so it can't run in CI. Borderless capture at sizes above the monitor's may not be possible on every setup.
- **Overlap with ReVa skills.** ReVa already ships Claude Code RE skills. *Open question:* should WideKit be a ReVa-compatible skill pack rather than its own recipe? That would mean less maintenance but less control over write operations.
- **Legal.** EULA clauses against reverse engineering and modification vary by game. Distribute only original code, never game bytes beyond short AOB signatures. Should the signatures themselves live in each fix repo rather than in WideKit?
- **Scope creep.** "Mostly-agent" can grow into a general game-RE platform. Keep v1 to aspect, FOV and HUD for native x64 games.
- **Monetisation is untested.** The profile shows no revenue signal, and the Patreon model depends on a steady flow of releases. Treat it as optional (M6) and judge it by how fast fixes ship after launch.
- **Confirm in M0:** how much of dh2013-ultrawide and dh2-coop matches the card's description. Their source wasn't in the context for this spec.

---

## Appendix: original Cinder card

**WideKit: an agent-ready toolkit for making ultrawide/FOV game fixes** (New project, effort L)

An open-source C++ ASI framework plus a Claude Code skill and Ghidra MCP recipes that turn 'make this game ultrawide' into a repeatable, mostly-agent workflow.

- Ultrawide modders like Lyall and Rose are funded by Patreon, and WSGF tracks 600+ community fixes, so the audience is proven
- Ghidra MCP servers now let Claude do real RE, but write-up authors say setup is fragile and context is weak
- You've shipped three such fixes and already wrote a game-modding skill from dh2-coop's lessons

**Summary:** Extract what widereign and dh2013-ultrawide share: a dinput8/version.dll proxy loader with chain-loading, AOB pattern scanning, safe hooks, an ini/hotkey/FOV system, a HUD relayout helper, an installer that finds Steam games, and logging. Package it as WideKit. Alongside it, ship a Claude Code plugin: a skill that walks the agent through finding the aspect check, the FOV and the HUD transform, with Ghidra MCP setup that actually works (pinned versions, write-capable scripts, hashing). Add a test harness that screenshots at 21:9 and 32:9. Monetise like the top fix authors do: a free, open toolkit, with a Patreon for a steady release of new fixes made faster with the toolkit, plus early access. The toolkit also markets you: every fix carries a 'built with WideKit' link.
**Why now:** In 2026 AI-assisted reverse engineering became real (GhidraMCP, ReVa, pyghidra-mcp), but people report fragile chains and agents making things up. A niche, opinionated pipeline for one high-demand fix type gives those general tools a concrete use. Games still ship 16:9-locked (Nightreign), so new demand keeps arriving.
**SEO:** 'how to make an ultrawide fix', 'ultrawide fix tutorial', 'game hor+ fov patch', '[game] ultrawide fix'. Each new fix page is SEO in its own right, and a tutorial series ('ultrawide fix with Claude and Ghidra') is very shareable.
**AI-agent visibility:** Ship it as a Claude Code plugin and skill, list the MCP recipes on mcpservers.org, and add an llms.txt for the framework API. When someone asks an assistant to 'make an ultrawide fix for X', the skill is what it reaches for.
**Competitors:** Flawless Widescreen (closed plugin-based fixer); Lyall's open-source fixes (per-game, no general toolkit); Ultimate ASI Loader / safetyhook (building blocks); GhidraMCP / ReVa (general-purpose RE agents)
**Fit:** widereign, dh2013-ultrawide (pattern-based patching, FixUI, installers), dh2-coop (the game-modding skill, RE docs). Plugin packaging from stash-plugin.
**Evidence:**
- In the River Raid experiment Claude used Ghidra MCP to find a one-byte patch, but the MCP couldn't write binaries, misidentified the game, and the four-part setup chain was fragile and slow. (https://quesma.com/blog/ghidra-mcp-unlimited-lives/)
- WSGF has documented 2,300+ games and community fixes for 600+ titles. It is Patreon-funded and the fixes stay free. (https://www.patreon.com/wsgf/about)
- Nightreign players complain about forced black bars and 60 fps caps and point to community fixes. (https://steamcommunity.com/app/2622380/discussions/0/597402319036902420)

**Note from the owner:** _(none)_
