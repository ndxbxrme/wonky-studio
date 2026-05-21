# Wonky Studio Godot Runtime

This folder is the Godot runtime shell for Wonky Studio projects.

## Current scope

This is no longer just a bundle-reader proof of concept. The shell now drives a playable runtime from exported Wonky Studio data.

Right now this Godot project can:

- autoload `res://runtime/runtime.json`
- load per-scene payloads from `runtime/scenes/<id>.json`
- render background plates and object renders
- run object animations and `go_to_frame`
- resolve authored interactions:
  - `scene_enter`
  - `object_click`
  - `object_verb`
  - `inventory_use`
  - `object_mouseover`
  - `object_mouseout`
  - `key_press`
- apply default trigger precedence:
  - `exact`
  - `object_default`
  - `scene_default`
- show the inventory overlay and held inventory items
- render a radial verb menu
- play narration audio, looping BGM with crossfades, and SFX
- show bilingual subtitles

## Runtime bundle flow

1. In Wonky Studio, use `Export runtime bundle`.
2. It will write a ready-to-open Godot project folder on disk.
3. Optionally use `Build Godot zip` to package that folder for download/share.
4. Open the exported folder in Godot, or unzip the packaged build and open that.

The exported project contains:

- this Godot shell project
- `runtime/runtime.json` for global runtime metadata
- `runtime/scenes/<id>.json` for per-scene runtime payloads
- `runtime/assets/` with only the files referenced by that runtime bundle

The exported project auto-detects `res://runtime/runtime.json` on startup.

For local iteration there is also an `Export Godot code files` action, which copies only the shell files into the exported runtime folder without rebuilding the runtime assets.

## Intended architecture

- `frontend/` remains the authoring UI
- `backend/` remains the source of truth and export pipeline
- `godot/` becomes an alternate runtime consuming the exported bundle

The long-term goal is for both the web preview and the Godot runtime to consume the same exported runtime model.
