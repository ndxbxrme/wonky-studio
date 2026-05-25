extends Control

const DEFAULT_RUNTIME_PATH := "res://runtime/runtime.json"
const VERB_LONG_PRESS_SECONDS := 0.32
const SUBTITLE_LINGER_SECONDS := 1.0
const SEQUENTIAL_AUDIO_GAP_SECONDS := 0.35

@onready var open_button: Button = $Overlay/OverlayVBox/ButtonRow/OpenButton
@onready var reload_button: Button = $Overlay/OverlayVBox/ButtonRow/ReloadButton
@onready var status_label: Label = $Overlay/OverlayVBox/StatusPanel/StatusMargin/StatusLabel
@onready var inventory_panel: PanelContainer = $Overlay/OverlayVBox/InventoryPanel
@onready var inventory_buttons: HBoxContainer = $Overlay/OverlayVBox/InventoryPanel/InventoryMargin/InventoryVBox/InventoryButtons
@onready var scene_stage: Control = $SceneStage
@onready var file_dialog: FileDialog = $FileDialog
@onready var verb_menu_layer: Control = $VerbMenuLayer
@onready var inventory_overlay_layer: Control = $InventoryOverlayLayer
@onready var inventory_overlay_frame: PanelContainer = $InventoryOverlayLayer/InventoryOverlayMargin/InventoryOverlayAlign/InventoryOverlayFrame
@onready var inventory_overlay_stage: Control = $InventoryOverlayLayer/InventoryOverlayMargin/InventoryOverlayAlign/InventoryOverlayFrame/InventoryOverlayFrameMargin/InventoryOverlayVBox/InventoryOverlayStage
@onready var held_item_layer: Control = $HeldItemLayer
@onready var subtitle_layer: MarginContainer = $SubtitleLayer
@onready var subtitle_panel: PanelContainer = $SubtitleLayer/SubtitleAlign/SubtitlePanel
@onready var subtitle_primary: Label = $SubtitleLayer/SubtitleAlign/SubtitlePanel/SubtitleMargin/SubtitleVBox/SubtitlePrimary
@onready var subtitle_secondary: Label = $SubtitleLayer/SubtitleAlign/SubtitlePanel/SubtitleMargin/SubtitleVBox/SubtitleSecondary

var last_runtime_path: String = DEFAULT_RUNTIME_PATH
var current_runtime_root: String = ""
var current_runtime: Dictionary = {}
var current_scene_ref: Dictionary = {}
var current_scene: Dictionary = {}
var current_variables: Dictionary = {}
var current_object_states: Dictionary = {}
var current_character_states: Dictionary = {}
var current_inventory_object_ids: Array[int] = []
var current_inventory_details: Dictionary = {}
var current_held_inventory_object_id: int = -1
var scene_canvas: Node2D = null
var current_scene_scale: float = 1.0
var current_scene_offset: Vector2 = Vector2.ZERO
var scene_info_message: String = "No scene loaded yet."
var runtime_message: String = ""
var texture_cache: Dictionary = {}
var audio_stream_cache: Dictionary = {}
var scene_data_cache: Dictionary = {}
var pending_object_id: int = -1
var hovered_object_id: int = -1
var active_verb_menu: Dictionary = {}
var pressed_object_id: int = -1
var pressed_local_position: Vector2 = Vector2.ZERO
var pressed_started_at_msec: int = 0
var verb_menu_expires_at_msec: int = 0
var verb_menu_remaining_msec: int = 0
var verb_menu_hovered: bool = false
var subtitle_token: int = 0
var audio_playback_token: int = 0
var inventory_overlay_open: bool = false
var narrator_player: AudioStreamPlayer = null
var bgm_player_a: AudioStreamPlayer = null
var bgm_player_b: AudioStreamPlayer = null
var sfx_player: AudioStreamPlayer = null
var pointer_global_position: Vector2 = Vector2.ZERO
var active_bgm_player_index: int = 0
var current_bgm_asset_path: String = ""


func _ready() -> void:
	randomize()
	open_button.pressed.connect(_on_open_pressed)
	reload_button.pressed.connect(_on_reload_pressed)
	file_dialog.file_selected.connect(_on_file_selected)
	scene_stage.resized.connect(_on_scene_stage_resized)
	scene_canvas = Node2D.new()
	scene_canvas.name = "SceneCanvas"
	scene_stage.add_child(scene_canvas)
	inventory_panel.visible = false
	inventory_overlay_layer.visible = false
	held_item_layer.visible = false
	inventory_overlay_stage.resized.connect(_on_inventory_overlay_stage_resized)
	_configure_subtitle_theme()
	narrator_player = AudioStreamPlayer.new()
	narrator_player.name = "NarratorPlayer"
	add_child(narrator_player)
	bgm_player_a = AudioStreamPlayer.new()
	bgm_player_a.name = "BgmPlayerA"
	add_child(bgm_player_a)
	bgm_player_b = AudioStreamPlayer.new()
	bgm_player_b.name = "BgmPlayerB"
	add_child(bgm_player_b)
	sfx_player = AudioStreamPlayer.new()
	sfx_player.name = "SfxPlayer"
	add_child(sfx_player)
	set_process(true)
	_try_autoload_default_bundle()


func _process(_delta: float) -> void:
	if active_verb_menu.is_empty():
		return
	if verb_menu_hovered:
		return
	if verb_menu_expires_at_msec <= 0:
		return
	if Time.get_ticks_msec() < verb_menu_expires_at_msec:
		return
	_hide_verb_menu()


func _on_open_pressed() -> void:
	file_dialog.popup_centered_ratio(0.7)


func _on_reload_pressed() -> void:
	if last_runtime_path.is_empty():
		_set_runtime_message("No runtime file selected yet.")
		return
	_load_runtime_bundle(last_runtime_path)


func _on_file_selected(path: String) -> void:
	last_runtime_path = path
	_load_runtime_bundle(path)


func _input(event: InputEvent) -> void:
	if current_scene.is_empty():
		return
	if event is InputEventMouseMotion:
		_handle_mouse_motion(event.position)
		return
	if event is InputEventKey and event.pressed and not event.echo:
		await _handle_key_press(event)
		return
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_RIGHT:
		_handle_right_click(event.position)
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			_handle_left_press(event.position)
		else:
			await _handle_left_release(event.position)


func _handle_left_press(global_position: Vector2) -> void:
	pointer_global_position = global_position
	pressed_object_id = -1
	pressed_started_at_msec = 0
	if inventory_overlay_open and not _point_hits_inventory_overlay(global_position):
		close_inventory_overlay()
		_set_runtime_message("Closed inventory.")
		return
	if _click_hits_ui(global_position):
		return
	if _has_visible_characters():
		return
	var stage_rect: Rect2 = scene_stage.get_global_rect()
	if not stage_rect.has_point(global_position):
		return
	pressed_local_position = global_position - stage_rect.position
	var object_state: Dictionary = _pick_object_at(pressed_local_position)
	if object_state.is_empty():
		return
	pressed_object_id = int(object_state.get("id", 0))
	pressed_started_at_msec = Time.get_ticks_msec()


func _handle_left_release(global_position: Vector2) -> void:
	pointer_global_position = global_position
	var resolved_object_id: int = pressed_object_id
	var started_at_msec: int = pressed_started_at_msec
	var anchor_position: Vector2 = pressed_local_position
	pressed_object_id = -1
	pressed_started_at_msec = 0
	if resolved_object_id <= 0:
		return
	if _click_hits_ui(global_position):
		return
	if _has_visible_characters():
		return
	var stage_rect: Rect2 = scene_stage.get_global_rect()
	if not stage_rect.has_point(global_position):
		return
	var release_local_position: Vector2 = global_position - stage_rect.position
	var object_state: Dictionary = _pick_object_at(release_local_position)
	if object_state.is_empty():
		_hide_verb_menu()
		_set_runtime_message("Clicked empty space.")
		return
	var object_id: int = int(object_state.get("id", 0))
	if object_id != resolved_object_id:
		return
	var label: String = str(object_state.get("label", object_state.get("name", "object")))
	if current_held_inventory_object_id > 0:
		var use_interactions: Array = _resolve_inventory_use_interactions(object_id, current_held_inventory_object_id)
		_hide_verb_menu()
		if use_interactions.is_empty():
			_set_runtime_message("No use interaction for %s on %s." % [_object_name(current_held_inventory_object_id), label])
			return
		_set_runtime_message("Use %s on %s." % [_object_name(current_held_inventory_object_id), label])
		await _execute_interactions(use_interactions, {
			"objectId": object_id,
			"inventoryObjectId": current_held_inventory_object_id,
		})
		return
	var held_duration_seconds: float = float(Time.get_ticks_msec() - started_at_msec) / 1000.0
	var verbs: Array = _build_verb_menu_items(object_id)
	if held_duration_seconds >= VERB_LONG_PRESS_SECONDS and not verbs.is_empty():
		_show_verb_menu(object_state, verbs, anchor_position)
		_set_runtime_message("Choose a verb for %s." % label)
		return
	var interactions: Array = _resolve_object_click_interactions(object_id)
	_hide_verb_menu()
	if interactions.is_empty():
		_set_runtime_message("Clicked %s but found no click interaction." % label)
		return
	_set_runtime_message("Clicked %s." % label)
	await _execute_interactions(interactions, {"objectId": object_id})


func _handle_right_click(global_position: Vector2) -> void:
	pointer_global_position = global_position
	if inventory_overlay_open:
		if not _point_hits_inventory_overlay(global_position):
			close_inventory_overlay()
			_set_runtime_message("Closed inventory.")
		return
	if _click_hits_ui(global_position):
		return
	if _has_visible_characters():
		return
	if current_held_inventory_object_id > 0:
		current_held_inventory_object_id = -1
		_refresh_inventory_panel()
		_hide_verb_menu()
		_set_runtime_message("Put inventory item away.")
		return
	var stage_rect: Rect2 = scene_stage.get_global_rect()
	if not stage_rect.has_point(global_position):
		return
	var local_position: Vector2 = global_position - stage_rect.position
	var object_state: Dictionary = _pick_object_at(local_position)
	if object_state.is_empty():
		_hide_verb_menu()
		return
	var object_id: int = int(object_state.get("id", 0))
	var verbs: Array = _build_verb_menu_items(object_id)
	if verbs.is_empty():
		_hide_verb_menu()
		return
	_show_verb_menu(object_state, verbs, local_position)
	_set_runtime_message("Choose a verb for %s." % str(object_state.get("label", object_state.get("name", "object"))))


func _handle_key_press(event: InputEventKey) -> void:
	var key_code: String = _event_to_key_code(event)
	if key_code.is_empty():
		return
	if key_code == "Escape" and not active_verb_menu.is_empty():
		_hide_verb_menu()
		_set_runtime_message("Closed verb menu.")
		return
	if key_code == "Escape" and current_held_inventory_object_id > 0:
		current_held_inventory_object_id = -1
		_refresh_inventory_panel()
		_set_runtime_message("Put inventory item away.")
		return
	if key_code == "Escape" and inventory_overlay_open:
		close_inventory_overlay()
		_set_runtime_message("Closed inventory.")
		return
	if key_code == _inventory_key_code():
		if inventory_overlay_open:
			close_inventory_overlay()
			_set_runtime_message("Closed inventory.")
		else:
			open_inventory_overlay()
			_set_runtime_message("Opened inventory.")
		return
	if _has_visible_characters():
		return
	var interactions: Array = _resolve_key_press_interactions(key_code)
	if interactions.is_empty():
		return
	await _execute_interactions(interactions, {"keyCode": key_code})


func _click_hits_ui(global_position: Vector2) -> bool:
	if open_button.get_global_rect().has_point(global_position):
		return true
	if reload_button.get_global_rect().has_point(global_position):
		return true
	if _point_hits_verb_menu(global_position):
		return true
	if _point_hits_inventory_overlay(global_position):
		return true
	return false


func _try_autoload_default_bundle() -> void:
	if ResourceLoader.exists(DEFAULT_RUNTIME_PATH):
		_load_runtime_bundle(DEFAULT_RUNTIME_PATH)
	else:
		_set_runtime_message("No bundled runtime found. Export a runtime bundle from Wonky Studio and open its runtime.json file.")


func _load_runtime_bundle(path: String) -> void:
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		_set_runtime_message("Could not open runtime file: %s" % path)
		return

	var parsed: Variant = JSON.parse_string(file.get_as_text())
	file.close()

	if typeof(parsed) != TYPE_DICTIONARY:
		_set_runtime_message("Runtime file is not a valid object: %s" % path)
		return

	var runtime: Dictionary = parsed
	current_runtime = runtime
	current_runtime_root = path.get_base_dir()
	current_variables = _build_initial_variables(runtime.get("variables", []))
	current_character_states = _build_initial_character_states(runtime.get("characters", []))
	current_inventory_object_ids = []
	current_inventory_details = {}
	current_held_inventory_object_id = -1
	inventory_overlay_open = false
	texture_cache.clear()
	audio_stream_cache.clear()
	scene_data_cache.clear()
	pending_object_id = -1
	hovered_object_id = -1
	pressed_object_id = -1
	pressed_started_at_msec = 0
	verb_menu_expires_at_msec = 0
	verb_menu_remaining_msec = 0
	verb_menu_hovered = false
	_stop_media_playback()
	_clear_subtitle()
	_hide_verb_menu()
	_refresh_inventory_panel()
	_set_runtime_message("Loaded runtime bundle: %s" % path)
	_load_first_scene(runtime)


func _build_initial_variables(variable_list: Array) -> Dictionary:
	var values: Dictionary = {}
	for variable_data in variable_list:
		if typeof(variable_data) != TYPE_DICTIONARY:
			continue
		values[int(variable_data.get("id", 0))] = variable_data.get("default_value")
	return values


func _load_first_scene(runtime: Dictionary) -> void:
	var scenes: Array = runtime.get("scenes", [])
	if scenes.is_empty():
		scene_info_message = "Runtime has no scenes."
		_clear_scene_stage()
		_refresh_status_label()
		return

	var first_scene: Variant = scenes[0]
	if typeof(first_scene) != TYPE_DICTIONARY:
		scene_info_message = "First scene entry is invalid."
		_clear_scene_stage()
		_refresh_status_label()
		return

	_load_scene_from_ref(first_scene)


func _load_scene_from_ref(scene_ref: Dictionary) -> void:
	current_scene_ref = scene_ref
	var scene_path: String = _resolve_runtime_path(str(scene_ref.get("scene_path", "")))
	var parsed: Dictionary = _load_scene_data(scene_path)
	if parsed.is_empty():
		scene_info_message = "Could not load scene file: %s" % scene_path
		_clear_scene_stage()
		_refresh_status_label()
		return

	current_scene = parsed
	current_object_states = _build_initial_object_states(current_scene.get("objects", []))
	current_character_states = _build_initial_character_states(current_runtime.get("characters", []))
	inventory_overlay_open = false
	pending_object_id = -1
	hovered_object_id = -1
	pressed_object_id = -1
	pressed_started_at_msec = 0
	verb_menu_expires_at_msec = 0
	verb_menu_remaining_msec = 0
	verb_menu_hovered = false
	_stop_media_playback()
	_clear_subtitle()
	_hide_verb_menu()
	_refresh_inventory_panel()
	_warmup_assets_for_current_runtime_state()
	_update_scene_info()
	_render_current_scene()
	call_deferred("_warmup_connected_scene_refs")
	call_deferred("_run_scene_enter_interactions")


func _build_initial_object_states(objects: Array) -> Dictionary:
	var states: Dictionary = {}
	for object_data in objects:
		if typeof(object_data) != TYPE_DICTIONARY:
			continue
		var object_id: int = int(object_data.get("id", 0))
		states[object_id] = {
			"id": object_id,
			"name": str(object_data.get("name", "")),
			"label": str(object_data.get("name", "")),
			"sort_order": int(object_data.get("sort_order", 0)),
			"visible": bool(object_data.get("visible", true)),
			"enabled": bool(object_data.get("enabled", true)),
			"source": object_data,
			"current_render": object_data.get("default_render", {}),
			"screen_rect": Rect2(),
		}
	return states


func _build_initial_character_states(characters: Array) -> Dictionary:
	var states: Dictionary = {}
	for character_data in characters:
		if typeof(character_data) != TYPE_DICTIONARY:
			continue
		var character_id: int = int(character_data.get("id", 0))
		if character_id <= 0:
			continue
		states[character_id] = {
			"id": character_id,
			"visible": false,
			"x": float(character_data.get("default_x", 960.0)),
			"y": float(character_data.get("default_y", 540.0)),
			"scale": float(character_data.get("default_scale", 1.0)),
			"base_image_id": _default_character_image_id(character_data, "base"),
			"viseme_image_id": 0,
		}
	return states


func _update_scene_info() -> void:
	if current_scene.is_empty():
		scene_info_message = "No scene loaded yet."
		_refresh_status_label()
		return
	scene_info_message = "%s · %dx%d · %d object%s" % [
		str(current_scene.get("title", "")),
		int(current_scene.get("width", 0)),
		int(current_scene.get("height", 0)),
		(current_scene.get("objects", []) as Array).size(),
		"" if (current_scene.get("objects", []) as Array).size() == 1 else "s"
	]
	_refresh_status_label()


func _refresh_status_label() -> void:
	var message: String = scene_info_message
	if not runtime_message.is_empty():
		message += "\n" + runtime_message
	status_label.text = message


func _set_runtime_message(message: String) -> void:
	runtime_message = message
	_refresh_status_label()


func _on_scene_stage_resized() -> void:
	if not current_scene.is_empty():
		call_deferred("_render_current_scene")


func _render_current_scene() -> void:
	_clear_scene_stage()
	if current_scene.is_empty():
		return

	var scene_width: int = int(current_scene.get("width", 0))
	var scene_height: int = int(current_scene.get("height", 0))
	if scene_width <= 0 or scene_height <= 0:
		_set_runtime_message("Scene has invalid dimensions.")
		return

	var stage_size: Vector2 = scene_stage.size
	if stage_size.x <= 0.0 or stage_size.y <= 0.0:
		return

	current_scene_scale = min(stage_size.x / float(scene_width), stage_size.y / float(scene_height))
	var scaled_size: Vector2 = Vector2(float(scene_width) * current_scene_scale, float(scene_height) * current_scene_scale)
	current_scene_offset = (stage_size - scaled_size) * 0.5

	var background: Dictionary = _select_background_image(current_scene)
	if not background.is_empty():
		var background_texture: Texture2D = _load_texture(_resolve_runtime_path(str(background.get("asset_path", ""))))
		if background_texture != null:
			var background_sprite: Sprite2D = Sprite2D.new()
			background_sprite.name = "Background"
			background_sprite.texture = background_texture
			background_sprite.centered = false
			background_sprite.position = current_scene_offset
			background_sprite.scale = Vector2(
				scaled_size.x / float(background_texture.get_width()),
				scaled_size.y / float(background_texture.get_height())
			)
			scene_canvas.add_child(background_sprite)

	var objects: Array = current_object_states.values()
	objects.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		if int(a.get("sort_order", 0)) == int(b.get("sort_order", 0)):
			return int(a.get("id", 0)) < int(b.get("id", 0))
		return int(a.get("sort_order", 0)) < int(b.get("sort_order", 0))
	)

	for object_state in objects:
		if not bool(object_state.get("visible", true)):
			continue
		var render: Variant = object_state.get("current_render", {})
		if typeof(render) != TYPE_DICTIONARY:
			continue
		var render_data: Dictionary = render
		var texture: Texture2D = _load_texture(_resolve_runtime_path(str(render_data.get("asset_path", ""))))
		if texture == null:
			continue
		var object_sprite: Sprite2D = Sprite2D.new()
		object_sprite.name = str(object_state.get("name", "Object"))
		object_sprite.texture = texture
		object_sprite.centered = false
		var target_position: Vector2 = current_scene_offset + Vector2(float(render_data.get("left", 0)) * current_scene_scale, float(render_data.get("top", 0)) * current_scene_scale)
		var target_size: Vector2 = Vector2(float(render_data.get("width", 0)) * current_scene_scale, float(render_data.get("height", 0)) * current_scene_scale)
		object_sprite.position = target_position
		object_sprite.scale = Vector2(
			target_size.x / float(texture.get_width()),
			target_size.y / float(texture.get_height())
		)
		scene_canvas.add_child(object_sprite)
		object_state["screen_rect"] = Rect2(target_position, target_size)
		current_object_states[int(object_state.get("id", 0))] = object_state

	var visible_characters: Array = _visible_character_states()
	if not visible_characters.is_empty():
		var dimmer := Polygon2D.new()
		dimmer.color = Color(0.11, 0.11, 0.11, 0.46)
		dimmer.polygon = PackedVector2Array([
			current_scene_offset,
			current_scene_offset + Vector2(scaled_size.x, 0),
			current_scene_offset + scaled_size,
			current_scene_offset + Vector2(0, scaled_size.y),
		])
		scene_canvas.add_child(dimmer)
	for character_state in visible_characters:
		_render_character_state(character_state)


func _select_background_image(scene_data: Dictionary) -> Dictionary:
	var images: Array = scene_data.get("images", [])
	if images.is_empty():
		return {}
	var background_frame_index: int = int(scene_data.get("background_frame_index", 0))
	for image_data in images:
		if typeof(image_data) != TYPE_DICTIONARY:
			continue
		if int(image_data.get("frame_index", -1)) == background_frame_index:
			return image_data
	var first_image: Variant = images[0]
	if typeof(first_image) == TYPE_DICTIONARY:
		return first_image
	return {}


func _visible_character_states() -> Array:
	var characters: Array = current_character_states.values()
	characters = characters.filter(func(character_state: Dictionary) -> bool:
		return bool(character_state.get("visible", false))
	)
	characters.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var character_a: Dictionary = _find_character_definition(int(a.get("id", 0)))
		var character_b: Dictionary = _find_character_definition(int(b.get("id", 0)))
		if int(character_a.get("sort_order", 0)) == int(character_b.get("sort_order", 0)):
			return int(a.get("id", 0)) < int(b.get("id", 0))
		return int(character_a.get("sort_order", 0)) < int(character_b.get("sort_order", 0))
	)
	return characters


func _has_visible_characters() -> bool:
	return not _visible_character_states().is_empty()


func _render_character_state(character_state: Dictionary) -> void:
	var character_id: int = int(character_state.get("id", 0))
	var character_def: Dictionary = _find_character_definition(character_id)
	if character_def.is_empty():
		return
	var base_image: Dictionary = _find_character_image(character_def, int(character_state.get("base_image_id", 0)))
	if base_image.is_empty():
		return
	var base_texture: Texture2D = _load_texture(_resolve_runtime_path(str(base_image.get("asset_path", ""))))
	if base_texture == null:
		return
	var character_scale: float = float(character_state.get("scale", character_def.get("default_scale", 1.0)))
	var center_x: float = current_scene_offset.x + (float(character_state.get("x", character_def.get("default_x", 0.0))) * current_scene_scale)
	var center_y: float = current_scene_offset.y + (float(character_state.get("y", character_def.get("default_y", 0.0))) * current_scene_scale)
	var draw_width: float = float(base_texture.get_width()) * character_scale * current_scene_scale
	var draw_height: float = float(base_texture.get_height()) * character_scale * current_scene_scale
	var left: float = center_x - (draw_width * 0.5)
	var top: float = center_y - draw_height
	var base_sprite := Sprite2D.new()
	base_sprite.centered = false
	base_sprite.texture = base_texture
	base_sprite.position = Vector2(left, top)
	base_sprite.scale = Vector2(draw_width / float(base_texture.get_width()), draw_height / float(base_texture.get_height()))
	scene_canvas.add_child(base_sprite)
	var viseme_image_id: int = int(character_state.get("viseme_image_id", 0))
	if viseme_image_id <= 0:
		return
	var viseme_image: Dictionary = _find_character_image(character_def, viseme_image_id)
	if viseme_image.is_empty():
		return
	var viseme_texture: Texture2D = _load_texture(_resolve_runtime_path(str(viseme_image.get("asset_path", ""))))
	if viseme_texture == null:
		return
	var viseme_sprite := Sprite2D.new()
	viseme_sprite.centered = false
	viseme_sprite.texture = viseme_texture
	viseme_sprite.position = Vector2(left, top)
	viseme_sprite.scale = Vector2(draw_width / float(viseme_texture.get_width()), draw_height / float(viseme_texture.get_height()))
	scene_canvas.add_child(viseme_sprite)


func _find_character_definition(character_id: int) -> Dictionary:
	for character_data in current_runtime.get("characters", []):
		if typeof(character_data) != TYPE_DICTIONARY:
			continue
		if int(character_data.get("id", 0)) == character_id:
			return character_data
	return {}


func _find_character_image(character_data: Dictionary, image_id: int) -> Dictionary:
	for image_data in character_data.get("images", []):
		if typeof(image_data) != TYPE_DICTIONARY:
			continue
		if int(image_data.get("id", 0)) == image_id:
			return image_data
	return {}


func _find_character_animation(character_id: int, animation_id: int) -> Dictionary:
	var character_data: Dictionary = _find_character_definition(character_id)
	if character_data.is_empty():
		return {}
	for animation_data in character_data.get("animations", []):
		if typeof(animation_data) != TYPE_DICTIONARY:
			continue
		if int(animation_data.get("id", 0)) == animation_id:
			return animation_data
	return {}


func _resolve_character_base_image_id(character_data: Dictionary, pose_variant_key: String) -> int:
	var normalized_key: String = pose_variant_key.strip_edges().to_lower()
	if normalized_key != "":
		for image_data in character_data.get("images", []):
			if typeof(image_data) != TYPE_DICTIONARY:
				continue
			if str(image_data.get("component_key", "")) != "base":
				continue
			if str(image_data.get("variant_key", "")).strip_edges().to_lower() == normalized_key:
				return int(image_data.get("id", 0))
	return _default_character_image_id(character_data, "base")


func _resolve_character_viseme_image_id(character_id: int, viseme_key: String) -> int:
	var character_data: Dictionary = _find_character_definition(character_id)
	if character_data.is_empty():
		return 0
	var normalized_key: String = viseme_key.strip_edges().to_lower()
	if normalized_key == "":
		return 0
	for image_data in character_data.get("images", []):
		if typeof(image_data) != TYPE_DICTIONARY:
			continue
		if str(image_data.get("component_key", "")) != "viseme_mouth":
			continue
		if str(image_data.get("variant_key", "")).strip_edges().to_lower() == normalized_key:
			return int(image_data.get("id", 0))
	for image_data in character_data.get("images", []):
		if typeof(image_data) != TYPE_DICTIONARY:
			continue
		if str(image_data.get("component_key", "")) != "viseme_mouth":
			continue
		var variant_key: String = str(image_data.get("variant_key", "")).strip_edges().to_lower()
		var segments := variant_key.split("__")
		if not segments.is_empty() and str(segments[segments.size() - 1]) == normalized_key:
			return int(image_data.get("id", 0))
		var source_name: String = str(image_data.get("source_name", "")).get_basename().strip_edges().to_lower()
		if source_name == normalized_key:
			return int(image_data.get("id", 0))
	return 0


func _default_character_image_id(character_data: Dictionary, component_key: String) -> int:
	var first_image_id: int = 0
	for image_data in character_data.get("images", []):
		if typeof(image_data) != TYPE_DICTIONARY:
			continue
		if str(image_data.get("component_key", "")) != component_key:
			continue
		if first_image_id <= 0:
			first_image_id = int(image_data.get("id", 0))
		if bool(image_data.get("is_default", false)):
			return int(image_data.get("id", 0))
	return first_image_id


func _resolve_runtime_path(relative_path: String) -> String:
	if relative_path.begins_with("res://") or relative_path.begins_with("user://"):
		return relative_path
	if current_runtime_root.is_empty():
		return relative_path
	return current_runtime_root.path_join(relative_path)


func _load_scene_data(path: String) -> Dictionary:
	if path.is_empty():
		return {}
	if scene_data_cache.has(path):
		return scene_data_cache[path]
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	file.close()
	if typeof(parsed) != TYPE_DICTIONARY:
		return {}
	scene_data_cache[path] = parsed
	return parsed


func _warmup_assets_for_current_runtime_state() -> void:
	_warmup_assets_for_scene_state(current_scene, current_object_states, current_character_states)


func _warmup_assets_for_scene_state(scene_data: Dictionary, object_states: Dictionary, character_states: Dictionary) -> void:
	if scene_data.is_empty():
		return
	var background: Dictionary = _select_background_image(scene_data)
	if not background.is_empty():
		_preload_texture(_resolve_runtime_path(str(background.get("asset_path", ""))))
	for object_state in object_states.values():
		if typeof(object_state) != TYPE_DICTIONARY:
			continue
		var render: Dictionary = object_state.get("current_render", {})
		if not render.is_empty():
			_preload_texture(_resolve_runtime_path(str(render.get("asset_path", ""))))
	for object_data in scene_data.get("objects", []):
		if typeof(object_data) != TYPE_DICTIONARY:
			continue
		var default_render: Dictionary = object_data.get("default_render", {})
		if not default_render.is_empty():
			_preload_texture(_resolve_runtime_path(str(default_render.get("asset_path", ""))))
		for render_data in object_data.get("frame_renders", []):
			if typeof(render_data) == TYPE_DICTIONARY:
				_preload_texture(_resolve_runtime_path(str(render_data.get("asset_path", ""))))
		for animation_data in object_data.get("animations", []):
			if typeof(animation_data) != TYPE_DICTIONARY:
				continue
			for frame_data in animation_data.get("frames", []):
				if typeof(frame_data) != TYPE_DICTIONARY:
					continue
				var animation_render: Dictionary = frame_data.get("render", {})
				if not animation_render.is_empty():
					_preload_texture(_resolve_runtime_path(str(animation_render.get("asset_path", ""))))
	var global_settings: Dictionary = current_runtime.get("global_settings", {})
	var inventory_background_path: String = str(global_settings.get("inventory_background_asset_path", ""))
	if inventory_background_path != "":
		_preload_texture(_resolve_runtime_path(inventory_background_path))
	for item_data in current_inventory_details.values():
		if typeof(item_data) != TYPE_DICTIONARY:
			continue
		var thumbnail_path: String = str(item_data.get("inventory_image_asset_path", ""))
		if thumbnail_path != "":
			_preload_texture(_resolve_runtime_path(thumbnail_path))
	for character_state in character_states.values():
		if typeof(character_state) != TYPE_DICTIONARY:
			continue
		if not bool(character_state.get("visible", false)):
			continue
		var character_def: Dictionary = _find_character_definition(int(character_state.get("id", 0)))
		if character_def.is_empty():
			continue
		for image_data in character_def.get("images", []):
			if typeof(image_data) != TYPE_DICTIONARY:
				continue
			_preload_texture(_resolve_runtime_path(str(image_data.get("asset_path", ""))))
		for animation_data in character_def.get("animations", []):
			if typeof(animation_data) != TYPE_DICTIONARY:
				continue
			for frame_data in animation_data.get("frames", []):
				if typeof(frame_data) != TYPE_DICTIONARY:
					continue
				var image_data: Dictionary = frame_data.get("image", {})
				if not image_data.is_empty():
					_preload_texture(_resolve_runtime_path(str(image_data.get("asset_path", ""))))
	for line_data in scene_data.get("script_lines", []):
		if typeof(line_data) != TYPE_DICTIONARY:
			continue
		for candidate_data in line_data.get("audio_candidates", []):
			if typeof(candidate_data) != TYPE_DICTIONARY:
				continue
			var candidate_path: String = str(candidate_data.get("asset_path", ""))
			if candidate_path != "":
				_preload_audio_stream(_resolve_runtime_path(candidate_path), false)
	for asset_data in current_runtime.get("audio_assets", []):
		if typeof(asset_data) != TYPE_DICTIONARY:
			continue
		var asset_path: String = str(asset_data.get("asset_path", ""))
		if asset_path == "":
			continue
		var should_loop: bool = str(asset_data.get("kind", "")) == "bgm"
		_preload_audio_stream(_resolve_runtime_path(asset_path), should_loop)


func _warmup_connected_scene_refs() -> void:
	var warmed_scene_ids: Dictionary = {}
	for interaction_data in current_scene.get("interactions", []):
		if typeof(interaction_data) != TYPE_DICTIONARY:
			continue
		_collect_warmup_scene_ids_from_steps(interaction_data.get("action_tree", []), warmed_scene_ids)
	for scene_id in warmed_scene_ids.keys():
		var scene_ref: Dictionary = _find_scene_ref_by_id(int(scene_id))
		if scene_ref.is_empty():
			continue
		var scene_path: String = _resolve_runtime_path(str(scene_ref.get("scene_path", "")))
		var connected_scene: Dictionary = _load_scene_data(scene_path)
		if connected_scene.is_empty():
			continue
		_warmup_assets_for_scene_state(
			connected_scene,
			_build_initial_object_states(connected_scene.get("objects", [])),
			current_character_states
		)


func _collect_warmup_scene_ids_from_steps(steps: Array, scene_ids: Dictionary) -> void:
	for step_data in steps:
		if typeof(step_data) != TYPE_DICTIONARY:
			continue
		var step_type: String = str(step_data.get("type", ""))
		if step_type == "change_scene" or step_type == "open_overlay_scene" or step_type == "change_overlay_scene":
			var scene_id: int = int(step_data.get("scene_id", 0))
			if scene_id > 0:
				scene_ids[scene_id] = true
		_collect_warmup_scene_ids_from_steps(step_data.get("then_steps", []), scene_ids)
		_collect_warmup_scene_ids_from_steps(step_data.get("else_steps", []), scene_ids)


func _load_texture(path: String) -> Texture2D:
	if path.is_empty():
		return null
	if texture_cache.has(path):
		return texture_cache[path]
	var image: Image = Image.load_from_file(path)
	if image == null or image.is_empty():
		return null
	var texture := ImageTexture.create_from_image(image)
	texture_cache[path] = texture
	return texture


func _preload_texture(path: String) -> void:
	if path.is_empty():
		return
	_load_texture(path)


func _clear_scene_stage() -> void:
	for child in scene_canvas.get_children():
		child.queue_free()


func _pick_object_at(local_position: Vector2) -> Dictionary:
	var objects: Array = current_object_states.values()
	objects.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		if int(a.get("sort_order", 0)) == int(b.get("sort_order", 0)):
			return int(a.get("id", 0)) > int(b.get("id", 0))
		return int(a.get("sort_order", 0)) > int(b.get("sort_order", 0))
	)
	for object_state in objects:
		if not bool(object_state.get("visible", true)) or not bool(object_state.get("enabled", true)):
			continue
		var rect: Rect2 = object_state.get("screen_rect", Rect2())
		if rect.has_point(local_position):
			return object_state
	return {}


func _resolve_object_click_interactions(object_id: int) -> Array:
	var exact_matches: Array = []
	var object_default_matches: Array = []
	var scene_default_matches: Array = []
	for interaction_data in current_scene.get("interactions", []):
		if typeof(interaction_data) != TYPE_DICTIONARY:
			continue
		var trigger: Dictionary = interaction_data.get("trigger", {})
		if str(trigger.get("type", "")) != "object_click":
			continue
		var match_mode: String = str(trigger.get("match_mode", "exact"))
		match match_mode:
			"scene_default":
				scene_default_matches.append(interaction_data)
			"object_default":
				if int(trigger.get("object_id", -1)) == object_id:
					object_default_matches.append(interaction_data)
			_:
				if int(trigger.get("object_id", -1)) == object_id:
					exact_matches.append(interaction_data)
	if not exact_matches.is_empty():
		return exact_matches
	if not object_default_matches.is_empty():
		return object_default_matches
	return scene_default_matches


func _resolve_available_verbs_for_object(object_id: int) -> Array:
	var items: Array = _build_verb_menu_items(object_id)
	var verbs: Array = []
	for item in items:
		if typeof(item) != TYPE_DICTIONARY:
			continue
		if bool((item as Dictionary).get("enabled", false)):
			verbs.append(item)
	return verbs


func _resolve_object_verb_interactions(object_id: int, verb_id: int) -> Array:
	var exact_matches: Array = []
	var object_default_matches: Array = []
	var scene_default_matches: Array = []
	for interaction_data in current_scene.get("interactions", []):
		if typeof(interaction_data) != TYPE_DICTIONARY:
			continue
		var trigger: Dictionary = interaction_data.get("trigger", {})
		if str(trigger.get("type", "")) != "object_verb":
			continue
		if int(trigger.get("verb_id", -1)) != verb_id:
			continue
		var match_mode: String = str(trigger.get("match_mode", "exact"))
		match match_mode:
			"scene_default":
				scene_default_matches.append(interaction_data)
			"object_default":
				if int(trigger.get("object_id", -1)) == object_id:
					object_default_matches.append(interaction_data)
			_:
				if int(trigger.get("object_id", -1)) == object_id:
					exact_matches.append(interaction_data)
	if not exact_matches.is_empty():
		return exact_matches
	if not object_default_matches.is_empty():
		return object_default_matches
	return scene_default_matches


func _resolve_inventory_use_interactions(object_id: int, inventory_object_id: int) -> Array:
	var exact_matches: Array = []
	var object_default_matches: Array = []
	var scene_default_matches: Array = []
	for interaction_data in current_scene.get("interactions", []):
		if typeof(interaction_data) != TYPE_DICTIONARY:
			continue
		var trigger: Dictionary = interaction_data.get("trigger", {})
		if str(trigger.get("type", "")) != "inventory_use":
			continue
		var match_mode: String = str(trigger.get("match_mode", "exact"))
		match match_mode:
			"scene_default":
				scene_default_matches.append(interaction_data)
			"object_default":
				if int(trigger.get("object_id", -1)) == object_id:
					object_default_matches.append(interaction_data)
			_:
				if int(trigger.get("object_id", -1)) == object_id and int(trigger.get("inventory_object_id", -1)) == inventory_object_id:
					exact_matches.append(interaction_data)
	if not exact_matches.is_empty():
		return exact_matches
	if not object_default_matches.is_empty():
		return object_default_matches
	return scene_default_matches


func _resolve_object_mouseover_interactions(object_id: int) -> Array:
	var interactions: Array = []
	for interaction_data in current_scene.get("interactions", []):
		if typeof(interaction_data) != TYPE_DICTIONARY:
			continue
		var trigger: Dictionary = interaction_data.get("trigger", {})
		if str(trigger.get("type", "")) == "object_mouseover" and int(trigger.get("object_id", -1)) == object_id:
			interactions.append(interaction_data)
	return interactions


func _resolve_object_mouseout_interactions(object_id: int) -> Array:
	var interactions: Array = []
	for interaction_data in current_scene.get("interactions", []):
		if typeof(interaction_data) != TYPE_DICTIONARY:
			continue
		var trigger: Dictionary = interaction_data.get("trigger", {})
		if str(trigger.get("type", "")) == "object_mouseout" and int(trigger.get("object_id", -1)) == object_id:
			interactions.append(interaction_data)
	return interactions


func _resolve_key_press_interactions(key_code: String) -> Array:
	var interactions: Array = []
	for interaction_data in current_scene.get("interactions", []):
		if typeof(interaction_data) != TYPE_DICTIONARY:
			continue
		var trigger: Dictionary = interaction_data.get("trigger", {})
		if str(trigger.get("type", "")) == "key_press" and str(trigger.get("key_code", "")) == key_code:
			interactions.append(interaction_data)
	return interactions


func _inventory_key_code() -> String:
	var global_settings: Dictionary = current_runtime.get("global_settings", {})
	var key_code: String = str(global_settings.get("inventory_key_code", "KeyI"))
	return key_code if key_code != "" else "KeyI"


func _run_scene_enter_interactions() -> void:
	var interactions: Array = []
	for interaction_data in current_scene.get("interactions", []):
		if typeof(interaction_data) != TYPE_DICTIONARY:
			continue
		var trigger: Dictionary = interaction_data.get("trigger", {})
		if str(trigger.get("type", "")) == "scene_enter":
			interactions.append(interaction_data)
	await _execute_interactions(interactions, {})


func _execute_interactions(interactions: Array, metadata: Dictionary = {}) -> void:
	for interaction_data in interactions:
		await _execute_action_tree(interaction_data.get("action_tree", []), metadata)


func _execute_action_tree(steps: Array, metadata: Dictionary = {}) -> void:
	for step_data in steps:
		if typeof(step_data) != TYPE_DICTIONARY:
			continue
		await _execute_step(step_data, metadata)


func _execute_step(step_data: Dictionary, metadata: Dictionary = {}) -> void:
	var step_type: String = str(step_data.get("type", ""))
	match step_type:
		"set_object_property":
			_apply_set_object_property(step_data, metadata)
		"go_to_frame":
			_apply_go_to_frame(step_data, metadata)
		"show_character":
			await _apply_show_character(step_data)
		"hide_character":
			_apply_hide_character(step_data)
		"set_character_transform":
			_apply_set_character_transform(step_data)
		"play_character_animation":
			await _play_character_animation(step_data)
		"add_inventory_item":
			_apply_add_inventory_item(step_data, metadata)
		"remove_inventory_item":
			_apply_remove_inventory_item(step_data, metadata)
		"clear_held_inventory_item":
			current_held_inventory_object_id = -1
			_refresh_inventory_panel()
			_set_runtime_message("Cleared held inventory item.")
		"increment_variable":
			_apply_increment_variable(step_data)
		"set_variable":
			current_variables[int(step_data.get("variable_id", 0))] = step_data.get("value")
		"toggle_variable":
			var variable_id: int = int(step_data.get("variable_id", 0))
			current_variables[variable_id] = not bool(current_variables.get(variable_id, false))
		"if_variable":
			if _evaluate_variable_condition(step_data):
				await _execute_action_tree(step_data.get("then_steps", []), metadata)
			else:
				await _execute_action_tree(step_data.get("else_steps", []), metadata)
		"delay":
			await get_tree().create_timer(float(step_data.get("duration_seconds", 0.0))).timeout
		"change_scene":
			var target_scene_id: int = int(step_data.get("scene_id", 0))
			var target_scene_ref: Dictionary = _find_scene_ref_by_id(target_scene_id)
			if not target_scene_ref.is_empty():
				_load_scene_from_ref(target_scene_ref)
				return
		"play_audio":
			var line_for_audio: Dictionary = _pick_script_line(step_data.get("script_line_ids", []))
			if line_for_audio.is_empty():
				return
			var speaker_character_id: int = int(step_data.get("speaker_character_id", 0))
			if str(step_data.get("wait", "continue")) == "continue":
				_play_audio_for_line(line_for_audio, speaker_character_id)
			else:
				await _play_audio_for_line(line_for_audio, speaker_character_id)
			return
		"show_subtitle":
			var line_for_subtitle: Dictionary = _pick_script_line(step_data.get("script_line_ids", []))
			if line_for_subtitle.is_empty():
				return
			var subtitle_payload: Dictionary = _build_subtitle_payload(line_for_subtitle)
			if subtitle_payload.is_empty():
				return
			var subtitle_duration: float = float(step_data.get("duration_seconds", 2.5))
			if str(step_data.get("wait", "continue")) == "continue":
				_show_subtitle(subtitle_payload, subtitle_duration)
			else:
				await _show_subtitle(subtitle_payload, subtitle_duration)
			return
		"crossfade_bgm":
			await _crossfade_bgm(int(step_data.get("audio_asset_id", 0)), float(step_data.get("duration_seconds", 0.35)))
			return
		"play_sfx":
			await _play_sfx(int(step_data.get("audio_asset_id", 0)))
			return
		"play_animation":
			await _play_animation(step_data, metadata)
		_:
			_set_runtime_message("Unsupported step type: %s" % step_type)

	if str(step_data.get("wait", "continue")) == "wait":
		await get_tree().process_frame


func _apply_set_object_property(step_data: Dictionary, metadata: Dictionary = {}) -> void:
	var object_state: Dictionary = _resolve_target_object_state(step_data, metadata)
	if object_state.is_empty():
		return
	var property_name: String = str(step_data.get("property", ""))
	object_state[property_name] = step_data.get("value")
	current_object_states[int(object_state.get("id", 0))] = object_state
	_render_current_scene()


func _apply_go_to_frame(step_data: Dictionary, metadata: Dictionary = {}) -> void:
	var target_scope: String = str(step_data.get("target_scope", "object"))
	if target_scope == "background":
		current_scene["background_frame_index"] = int(step_data.get("frame_index", 0))
		_render_current_scene()
		return
	var object_state: Dictionary = _resolve_target_object_state(step_data, metadata)
	if object_state.is_empty():
		return
	var source: Dictionary = object_state.get("source", {})
	var next_render: Dictionary = {}
	if target_scope == "pickup_background":
		var pickup_uploaded_file_id: int = int(source.get("pickup_uploaded_file_id", 0))
		for render_data in source.get("frame_renders", []):
			if typeof(render_data) == TYPE_DICTIONARY and int(render_data.get("uploaded_file_id", -1)) == pickup_uploaded_file_id:
				next_render = render_data
				break
	else:
		var frame_index: int = int(step_data.get("frame_index", -1))
		for render_data in source.get("frame_renders", []):
			if typeof(render_data) == TYPE_DICTIONARY and int(render_data.get("frame_index", -1)) == frame_index:
				next_render = render_data
				break
	if next_render.is_empty():
		return
	object_state["current_render"] = next_render
	current_object_states[int(object_state.get("id", 0))] = object_state
	_render_current_scene()


func _apply_show_character(step_data: Dictionary) -> void:
	var character_id: int = int(step_data.get("character_id", 0))
	var character_state: Dictionary = current_character_states.get(character_id, {})
	var character_def: Dictionary = _find_character_definition(character_id)
	if character_state.is_empty() or character_def.is_empty():
		return
	character_state["visible"] = true
	character_state["x"] = float(step_data.get("x", character_def.get("default_x", 960.0)))
	character_state["y"] = float(step_data.get("y", character_def.get("default_y", 540.0)))
	character_state["scale"] = float(step_data.get("scale", character_def.get("default_scale", 1.0)))
	character_state["base_image_id"] = _resolve_character_base_image_id(character_def, str(step_data.get("pose_variant_key", "")))
	character_state["viseme_image_id"] = 0
	current_character_states[character_id] = character_state
	_render_current_scene()
	var animation_id: int = int(step_data.get("animation_id", 0))
	if animation_id > 0:
		await _play_character_animation({
			"character_id": character_id,
			"animation_id": animation_id,
		})


func _apply_hide_character(step_data: Dictionary) -> void:
	var character_id: int = int(step_data.get("character_id", 0))
	var character_state: Dictionary = current_character_states.get(character_id, {})
	if character_state.is_empty():
		return
	character_state["visible"] = false
	character_state["viseme_image_id"] = 0
	current_character_states[character_id] = character_state
	_render_current_scene()


func _apply_set_character_transform(step_data: Dictionary) -> void:
	var character_id: int = int(step_data.get("character_id", 0))
	var character_state: Dictionary = current_character_states.get(character_id, {})
	if character_state.is_empty():
		return
	character_state["x"] = float(step_data.get("x", character_state.get("x", 960.0)))
	character_state["y"] = float(step_data.get("y", character_state.get("y", 540.0)))
	character_state["scale"] = float(step_data.get("scale", character_state.get("scale", 1.0)))
	current_character_states[character_id] = character_state
	_render_current_scene()


func _play_character_animation(step_data: Dictionary) -> void:
	var character_id: int = int(step_data.get("character_id", 0))
	var animation_id: int = int(step_data.get("animation_id", 0))
	var character_state: Dictionary = current_character_states.get(character_id, {})
	var animation_data: Dictionary = _find_character_animation(character_id, animation_id)
	if character_state.is_empty() or animation_data.is_empty():
		return
	for frame_data in animation_data.get("frames", []):
		if typeof(frame_data) != TYPE_DICTIONARY:
			continue
		character_state["base_image_id"] = int(frame_data.get("character_image_id", 0))
		current_character_states[character_id] = character_state
		_render_current_scene()
		await get_tree().create_timer(float(frame_data.get("duration_seconds", 0.066))).timeout


func _apply_add_inventory_item(step_data: Dictionary, metadata: Dictionary = {}) -> void:
	var source: Dictionary = _resolve_scene_object_source(step_data, metadata)
	if source.is_empty():
		return
	var object_id: int = int(source.get("id", 0))
	if not current_inventory_object_ids.has(object_id):
		current_inventory_object_ids.append(object_id)
	current_inventory_details[object_id] = {
		"id": object_id,
		"name": str(source.get("name", "item")),
		"inventory_image_asset_path": str(source.get("inventory_image_asset_path", "")),
	}
	_refresh_inventory_panel()
	_set_runtime_message("Added %s to inventory." % str(source.get("name", "item")))


func _apply_remove_inventory_item(step_data: Dictionary, metadata: Dictionary = {}) -> void:
	var source: Dictionary = _resolve_scene_object_source(step_data, metadata)
	if source.is_empty():
		return
	var object_id: int = int(source.get("id", 0))
	current_inventory_object_ids.erase(object_id)
	current_inventory_details.erase(object_id)
	if current_held_inventory_object_id == object_id:
		current_held_inventory_object_id = -1
	_refresh_inventory_panel()
	_set_runtime_message("Removed %s from inventory." % str(source.get("name", "item")))


func _apply_increment_variable(step_data: Dictionary) -> void:
	var variable_id: int = int(step_data.get("variable_id", 0))
	var current_value: float = float(current_variables.get(variable_id, 0.0))
	current_variables[variable_id] = current_value + float(step_data.get("amount", 0.0))


func _evaluate_variable_condition(step_data: Dictionary) -> bool:
	var variable_id: int = int(step_data.get("variable_id", 0))
	var left: Variant = current_variables.get(variable_id)
	var right: Variant = step_data.get("value")
	var operator_name: String = str(step_data.get("operator", "equals"))
	match operator_name:
		"equals":
			return left == right
		"not_equals":
			return left != right
		"greater_than":
			return float(left) > float(right)
		"less_than":
			return float(left) < float(right)
		"greater_or_equal":
			return float(left) >= float(right)
		"less_or_equal":
			return float(left) <= float(right)
	return false


func _play_animation(step_data: Dictionary, metadata: Dictionary = {}) -> void:
	var object_state: Dictionary = _resolve_target_object_state(step_data, metadata)
	if object_state.is_empty():
		return
	var source: Dictionary = object_state.get("source", {})
	var target_animation_name: String = str(step_data.get("animation_name", ""))
	var target_animation_id: int = 0 if str(step_data.get("target_object_mode", "static")) != "static" else int(step_data.get("animation_id", 0))
	var animation_data: Dictionary = {}
	for candidate in source.get("animations", []):
		if typeof(candidate) != TYPE_DICTIONARY:
			continue
		if target_animation_id != 0 and int(candidate.get("id", -1)) == target_animation_id:
			animation_data = candidate
			break
		if not target_animation_name.is_empty() and str(candidate.get("name", "")) == target_animation_name:
			animation_data = candidate
			break
	if animation_data.is_empty():
		_set_runtime_message("Animation not found for %s." % str(source.get("name", "object")))
		return
	for frame_data in animation_data.get("frames", []):
		if typeof(frame_data) != TYPE_DICTIONARY:
			continue
		var render: Variant = frame_data.get("render")
		if typeof(render) == TYPE_DICTIONARY:
			object_state["current_render"] = render
			current_object_states[int(object_state.get("id", 0))] = object_state
			_render_current_scene()
		await get_tree().create_timer(float(frame_data.get("duration_seconds", 0.066))).timeout


func _resolve_target_object_state(step_data: Dictionary, metadata: Dictionary = {}) -> Dictionary:
	var object_id: int = _resolve_step_target_object_id(step_data, metadata)
	return current_object_states.get(object_id, {})


func _resolve_scene_object_source(step_data: Dictionary, metadata: Dictionary = {}) -> Dictionary:
	var scene_object_id: int = _resolve_step_scene_object_id(step_data, metadata)
	if scene_object_id <= 0:
		return {}
	if current_inventory_details.has(scene_object_id):
		return current_inventory_details[scene_object_id]
	var object_state: Dictionary = current_object_states.get(scene_object_id, {})
	return object_state.get("source", {})


func _resolve_step_target_object_id(step_data: Dictionary, metadata: Dictionary = {}) -> int:
	var mode: String = str(step_data.get("target_object_mode", "static"))
	if mode == "trigger_object":
		return int(metadata.get("objectId", 0))
	if mode == "trigger_inventory_object":
		return int(metadata.get("inventoryObjectId", 0))
	return int(step_data.get("target_object_id", 0))


func _resolve_step_scene_object_id(step_data: Dictionary, metadata: Dictionary = {}) -> int:
	var mode: String = str(step_data.get("scene_object_mode", "static"))
	if mode == "trigger_object":
		return int(metadata.get("objectId", 0))
	if mode == "trigger_inventory_object":
		return int(metadata.get("inventoryObjectId", 0))
	return int(step_data.get("scene_object_id", 0))


func _report_script_line(line_ids: Array, prefix: String) -> void:
	if line_ids.is_empty():
		return
	var line_id: int = int(line_ids[0])
	var label: String = _script_line_text(line_id)
	_set_runtime_message("%s %s: %s" % [prefix, str(line_id), label])


func _script_line_text(line_id: int) -> String:
	for line_data in current_runtime.get("script_lines", []):
		if typeof(line_data) != TYPE_DICTIONARY:
			continue
		if int(line_data.get("id", -1)) == line_id:
			return str(line_data.get("source_text", line_data.get("path", "")))
	return ""


func _find_scene_ref_by_id(scene_id: int) -> Dictionary:
	for scene_ref in current_runtime.get("scenes", []):
		if typeof(scene_ref) != TYPE_DICTIONARY:
			continue
		if int(scene_ref.get("scene_id", -1)) == scene_id:
			return scene_ref
	return {}


func _find_verb_by_id(verb_id: int) -> Dictionary:
	for verb_data in current_runtime.get("verbs", []):
		if typeof(verb_data) != TYPE_DICTIONARY:
			continue
		if int(verb_data.get("id", -1)) == verb_id:
			return verb_data
	return {}


func _show_verb_menu(object_state: Dictionary, verbs: Array, anchor_position: Vector2) -> void:
	pending_object_id = int(object_state.get("id", -1))
	active_verb_menu = {
		"object_id": pending_object_id,
		"anchor": anchor_position,
	}
	verb_menu_hovered = false
	verb_menu_remaining_msec = int(round(_verb_menu_timeout_seconds() * 1000.0))
	verb_menu_expires_at_msec = Time.get_ticks_msec() + verb_menu_remaining_msec
	_clear_verb_menu_nodes()
	var layout: Dictionary = _compute_verb_menu_layout(scene_stage.size, anchor_position, verbs.size())
	var anchor: Vector2 = layout.get("anchor", anchor_position)
	var offsets: Array = layout.get("offsets", [])
	for index in range(verbs.size()):
		var item: Dictionary = verbs[index]
		var offset: Vector2 = Vector2.ZERO
		if index < offsets.size():
			offset = offsets[index]
		var tag: Control = _create_verb_tag(item, anchor + offset)
		verb_menu_layer.add_child(tag)
	_active_verb_menu_visible(true)
	hovered_object_id = pending_object_id


func _hide_verb_menu() -> void:
	pending_object_id = -1
	active_verb_menu = {}
	verb_menu_expires_at_msec = 0
	verb_menu_remaining_msec = 0
	verb_menu_hovered = false
	_clear_verb_menu_nodes()
	_active_verb_menu_visible(false)


func _on_verb_pressed(verb_id: int, tag: Control) -> void:
	if pending_object_id < 0:
		return
	var resolved_object_id: int = pending_object_id
	var object_state: Dictionary = current_object_states.get(resolved_object_id, {})
	var object_label: String = str(object_state.get("label", object_state.get("name", "object")))
	var interactions: Array = _resolve_object_verb_interactions(resolved_object_id, verb_id)
	await _animate_verb_selection(tag)
	_hide_verb_menu()
	if interactions.is_empty():
		_set_runtime_message("No verb interaction for %s." % object_label)
		return
	_set_runtime_message("%s on %s." % [_verb_label(_find_verb_by_id(verb_id)), object_label])
	await _execute_interactions(interactions, {"objectId": resolved_object_id})


func _refresh_inventory_panel() -> void:
	inventory_panel.visible = false
	_sync_inventory_overlay()
	_sync_held_inventory_item()


func open_inventory_overlay() -> void:
	if not active_verb_menu.is_empty():
		_hide_verb_menu()
	inventory_overlay_open = true
	_sync_inventory_overlay()


func close_inventory_overlay() -> void:
	inventory_overlay_open = false
	_sync_inventory_overlay()


func _on_inventory_overlay_stage_resized() -> void:
	if inventory_overlay_open:
		call_deferred("_sync_inventory_overlay")


func _sync_inventory_overlay() -> void:
	inventory_overlay_layer.visible = inventory_overlay_open
	for child in inventory_overlay_stage.get_children():
		child.queue_free()
	if not inventory_overlay_open:
		return
	var config: Dictionary = _inventory_config()
	var background_asset_path: String = str(config.get("background_asset_path", ""))
	var slots: Array = config.get("slots", [])
	var surface_metrics: Dictionary = {}
	if not background_asset_path.is_empty():
		var background_texture: Texture2D = _load_texture(_resolve_runtime_path(background_asset_path))
		if background_texture != null:
			var background_rect := TextureRect.new()
			background_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			background_rect.stretch_mode = TextureRect.STRETCH_SCALE
			background_rect.texture = background_texture
			background_rect.position = Vector2.ZERO
			background_rect.size = inventory_overlay_stage.size
			inventory_overlay_stage.add_child(background_rect)
			surface_metrics = _compute_contained_surface_layout(
				inventory_overlay_stage.size,
				Vector2(background_texture.get_width(), background_texture.get_height())
			)
	var surface := Control.new()
	surface.name = "InventorySurface"
	if surface_metrics.is_empty():
		surface.position = Vector2.ZERO
		surface.size = inventory_overlay_stage.size
		surface.scale = Vector2.ONE
	else:
		surface.position = Vector2(float(surface_metrics.get("left", 0.0)), float(surface_metrics.get("top", 0.0)))
		surface.size = Vector2(float(surface_metrics.get("width", 0.0)), float(surface_metrics.get("height", 0.0)))
		surface.scale = Vector2.ONE * float(surface_metrics.get("scale", 1.0))
	inventory_overlay_stage.add_child(surface)
	for index in range(slots.size()):
		var slot: Dictionary = slots[index]
		var item_object_id: int = current_inventory_object_ids[index] if index < current_inventory_object_ids.size() else -1
		var slot_button := _build_inventory_overlay_slot(slot, item_object_id)
		surface.add_child(slot_button)


func _build_inventory_overlay_slot(slot: Dictionary, item_object_id: int) -> Control:
	var x: float = float(slot.get("x", 0.0))
	var y: float = float(slot.get("y", 0.0))
	var size: float = float(slot.get("size", 96.0))
	var origin: String = str(slot.get("origin", "center"))
	var wrapper := Control.new()
	wrapper.custom_minimum_size = Vector2(size, size)
	wrapper.size = Vector2(size, size)
	wrapper.position = Vector2(x, y)
	if origin == "center":
		wrapper.position -= wrapper.size * 0.5
	var button := Button.new()
	button.flat = true
	button.focus_mode = Control.FOCUS_NONE
	button.position = Vector2.ZERO
	button.size = wrapper.size
	button.disabled = item_object_id <= 0
	button.modulate = Color(1, 1, 1, 0.02)
	if item_object_id > 0:
		button.pressed.connect(func() -> void:
			_on_inventory_button_pressed(item_object_id)
		)
	if item_object_id > 0 and current_inventory_details.has(item_object_id):
		var item_data: Dictionary = current_inventory_details[item_object_id]
		var thumbnail_path: String = str(item_data.get("inventory_image_asset_path", ""))
		var thumbnail_texture: Texture2D = _load_texture(_resolve_runtime_path(thumbnail_path))
		if thumbnail_texture != null:
			var thumb := TextureRect.new()
			thumb.mouse_filter = Control.MOUSE_FILTER_IGNORE
			thumb.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			thumb.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
			thumb.texture = thumbnail_texture
			thumb.position = Vector2(8, 8)
			thumb.size = wrapper.size - Vector2(16, 16)
			wrapper.add_child(thumb)
		if current_held_inventory_object_id == item_object_id:
			var selected_frame := Panel.new()
			selected_frame.mouse_filter = Control.MOUSE_FILTER_IGNORE
			selected_frame.position = Vector2.ZERO
			selected_frame.size = wrapper.size
			var selected_style := StyleBoxFlat.new()
			selected_style.bg_color = Color(0, 0, 0, 0)
			selected_style.border_color = Color(1, 0.92, 0.55, 0.95)
			selected_style.border_width_left = 3
			selected_style.border_width_top = 3
			selected_style.border_width_right = 3
			selected_style.border_width_bottom = 3
			selected_style.corner_radius_top_left = 10
			selected_style.corner_radius_top_right = 10
			selected_style.corner_radius_bottom_right = 10
			selected_style.corner_radius_bottom_left = 10
			selected_frame.add_theme_stylebox_override("panel", selected_style)
			wrapper.add_child(selected_frame)
	wrapper.add_child(button)
	return wrapper


func _on_inventory_button_pressed(object_id: int) -> void:
	if current_held_inventory_object_id == object_id:
		current_held_inventory_object_id = -1
		_set_runtime_message("Put %s away." % _object_name(object_id))
	else:
		current_held_inventory_object_id = object_id
		_hide_verb_menu()
		_set_runtime_message("Selected %s from inventory." % _object_name(object_id))
	close_inventory_overlay()
	_refresh_inventory_panel()


func _object_name(object_id: int) -> String:
	if current_inventory_details.has(object_id):
		return str(current_inventory_details[object_id].get("name", "item"))
	if current_object_states.has(object_id):
		var object_state: Dictionary = current_object_states[object_id]
		return str(object_state.get("label", object_state.get("name", "object")))
	return "item %d" % object_id


func _inventory_config() -> Dictionary:
	var global_settings: Dictionary = current_runtime.get("global_settings", {})
	return {
		"background_asset_path": str(global_settings.get("inventory_background_asset_path", "")),
		"slots": global_settings.get("inventory_slots", []),
	}


func _compute_contained_surface_layout(stage_size: Vector2, source_size: Vector2) -> Dictionary:
	var available_width: float = maxf(0.0, stage_size.x)
	var available_height: float = maxf(0.0, stage_size.y)
	var natural_width: float = maxf(1.0, source_size.x)
	var natural_height: float = maxf(1.0, source_size.y)
	if available_width <= 0.0 or available_height <= 0.0:
		return {
			"left": 0.0,
			"top": 0.0,
			"width": natural_width,
			"height": natural_height,
			"scale": 1.0,
		}
	var scale: float = minf(available_width / natural_width, available_height / natural_height)
	var rendered_width: float = natural_width * scale
	var rendered_height: float = natural_height * scale
	return {
		"left": (available_width - rendered_width) * 0.5,
		"top": (available_height - rendered_height) * 0.5,
		"width": natural_width,
		"height": natural_height,
		"scale": scale,
	}


func _handle_mouse_motion(global_position: Vector2) -> void:
	pointer_global_position = global_position
	_sync_held_inventory_item()
	if _has_visible_characters():
		if hovered_object_id > 0:
			var character_blocked_hover_id: int = hovered_object_id
			hovered_object_id = -1
			call_deferred("_run_object_mouseout_interactions", character_blocked_hover_id)
		return
	if _click_hits_ui(global_position):
		if hovered_object_id > 0:
			var previous_hovered_id: int = hovered_object_id
			hovered_object_id = -1
			call_deferred("_run_object_mouseout_interactions", previous_hovered_id)
		return
	var stage_rect: Rect2 = scene_stage.get_global_rect()
	if not stage_rect.has_point(global_position):
		if hovered_object_id > 0:
			var exited_object_id: int = hovered_object_id
			hovered_object_id = -1
			call_deferred("_run_object_mouseout_interactions", exited_object_id)
		return
	var local_position: Vector2 = global_position - stage_rect.position
	var object_state: Dictionary = _pick_object_at(local_position)
	var next_object_id: int = int(object_state.get("id", 0))
	if next_object_id == hovered_object_id:
		return
	if hovered_object_id > 0:
		var previous_id: int = hovered_object_id
		hovered_object_id = -1
		call_deferred("_run_object_mouseout_interactions", previous_id)
	if next_object_id > 0:
		hovered_object_id = next_object_id
		call_deferred("_run_object_mouseover_interactions", next_object_id)


func _run_object_mouseover_interactions(object_id: int) -> void:
	var interactions: Array = _resolve_object_mouseover_interactions(object_id)
	if interactions.is_empty():
		return
	await _execute_interactions(interactions, {"objectId": object_id})


func _run_object_mouseout_interactions(object_id: int) -> void:
	var interactions: Array = _resolve_object_mouseout_interactions(object_id)
	if interactions.is_empty():
		return
	await _execute_interactions(interactions, {"objectId": object_id})


func _sync_held_inventory_item() -> void:
	for child in held_item_layer.get_children():
		child.queue_free()
	if current_held_inventory_object_id <= 0:
		held_item_layer.visible = false
		return
	var item_data: Dictionary = current_inventory_details.get(current_held_inventory_object_id, {})
	if item_data.is_empty():
		held_item_layer.visible = false
		return
	var thumbnail_path: String = str(item_data.get("inventory_image_asset_path", ""))
	var thumbnail_texture: Texture2D = _load_texture(_resolve_runtime_path(thumbnail_path))
	if thumbnail_texture == null:
		held_item_layer.visible = false
		return
	var max_size: float = 88.0
	var source_width: float = maxf(1.0, float(thumbnail_texture.get_width()))
	var source_height: float = maxf(1.0, float(thumbnail_texture.get_height()))
	var scale_factor: float = minf(max_size / source_width, max_size / source_height)
	var render_size := Vector2(source_width * scale_factor, source_height * scale_factor)
	var wrapper := Control.new()
	wrapper.mouse_filter = Control.MOUSE_FILTER_IGNORE
	wrapper.size = render_size
	wrapper.position = pointer_global_position + Vector2(18, 18)
	var shadow := TextureRect.new()
	shadow.mouse_filter = Control.MOUSE_FILTER_IGNORE
	shadow.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	shadow.stretch_mode = TextureRect.STRETCH_SCALE
	shadow.texture = thumbnail_texture
	shadow.position = Vector2(6, 6)
	shadow.size = render_size
	shadow.modulate = Color(0, 0, 0, 0.28)
	wrapper.add_child(shadow)
	var texture_rect := TextureRect.new()
	texture_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	texture_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	texture_rect.stretch_mode = TextureRect.STRETCH_SCALE
	texture_rect.texture = thumbnail_texture
	texture_rect.position = Vector2.ZERO
	texture_rect.size = render_size
	wrapper.add_child(texture_rect)
	held_item_layer.add_child(wrapper)
	held_item_layer.visible = true


func _build_verb_menu_items(object_id: int) -> Array:
	var show_disabled: bool = bool((current_runtime.get("global_settings", {}) as Dictionary).get("verb_menu_show_disabled", true))
	var verbs: Array = []
	for verb_data in current_runtime.get("verbs", []):
		if typeof(verb_data) != TYPE_DICTIONARY:
			continue
		if verb_data.get("enabled", true) == false:
			continue
		var item: Dictionary = {
			"id": int(verb_data.get("id", 0)),
			"key": str(verb_data.get("key", "")),
			"label": _verb_label(verb_data),
			"enabled": not _resolve_object_verb_interactions(object_id, int(verb_data.get("id", 0))).is_empty(),
			"background_asset_path": str((current_runtime.get("global_settings", {}) as Dictionary).get("verb_tag_background_asset_path", "")),
		}
		if show_disabled or bool(item.get("enabled", false)):
			verbs.append(item)
	return verbs


func _compute_verb_menu_layout(stage_size: Vector2, anchor_point: Vector2, count: int) -> Dictionary:
	var tag_width: float = 132.0
	var tag_height: float = 88.0
	var tag_padding: float = 10.0
	var radius: float = 82.0 if count <= 2 else 92.0
	var min_x: float = (tag_width * 0.5) + tag_padding
	var max_x: float = max(min_x, stage_size.x - (tag_width * 0.5) - tag_padding)
	var min_y: float = (tag_height * 0.5) + tag_padding
	var max_y: float = max(min_y, stage_size.y - (tag_height * 0.5) - tag_padding)
	var anchor_x: float = clampf(anchor_point.x, min_x, max_x)
	var anchor_y: float = clampf(anchor_point.y, min_y, max_y)
	var center_x: float = stage_size.x * 0.5
	var center_y: float = stage_size.y * 0.5
	var dx: float = center_x - anchor_x
	var dy: float = center_y - anchor_y
	var preferred_angle: float = deg_to_rad(-90.0) if absf(dx) < 2.0 and absf(dy) < 2.0 else atan2(dy, dx)
	var spread_degrees: float = 0.0
	if count <= 1:
		spread_degrees = 0.0
	elif count == 2:
		spread_degrees = 90.0
	elif count == 3:
		spread_degrees = 128.0
	else:
		spread_degrees = min(210.0, 108.0 + ((count - 3) * 24.0))
	var spread_radians: float = deg_to_rad(spread_degrees)
	var offsets: Array = []
	for index in range(max(1, count)):
		var angle: float = preferred_angle
		if count > 1:
			angle = preferred_angle - (spread_radians * 0.5) + ((spread_radians * index) / float(count - 1))
		var target_x: float = anchor_x + (cos(angle) * radius)
		var target_y: float = anchor_y + (sin(angle) * radius)
		var clamped_x: float = clampf(target_x, min_x, max_x)
		var clamped_y: float = clampf(target_y, min_y, max_y)
		offsets.append(Vector2(clamped_x - anchor_x, clamped_y - anchor_y))
	return {
		"anchor": Vector2(anchor_x, anchor_y),
		"offsets": offsets,
	}


func _create_verb_tag(item: Dictionary, center_position: Vector2) -> Control:
	var tag_size := Vector2(132.0, 88.0)
	var top_left := center_position - (tag_size * 0.5)
	var wrapper := Control.new()
	wrapper.custom_minimum_size = tag_size
	wrapper.size = tag_size
	wrapper.position = top_left
	wrapper.pivot_offset = tag_size * 0.5
	wrapper.mouse_filter = Control.MOUSE_FILTER_IGNORE
	wrapper.set_meta("base_position", top_left)
	wrapper.set_meta("base_scale", Vector2.ONE)

	var background_texture_path: String = str(item.get("background_asset_path", ""))
	if not background_texture_path.is_empty():
		var background_texture := _load_texture(_resolve_runtime_path(background_texture_path))
		if background_texture != null:
			var texture_rect := TextureRect.new()
			texture_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
			texture_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			texture_rect.stretch_mode = TextureRect.STRETCH_SCALE
			texture_rect.texture = background_texture
			texture_rect.position = Vector2.ZERO
			texture_rect.size = tag_size
			wrapper.add_child(texture_rect)
	else:
		var background := Panel.new()
		background.mouse_filter = Control.MOUSE_FILTER_IGNORE
		background.position = Vector2.ZERO
		background.size = tag_size
		var style := StyleBoxFlat.new()
		style.bg_color = Color(0.14, 0.15, 0.2, 0.94)
		style.corner_radius_top_left = 18
		style.corner_radius_top_right = 18
		style.corner_radius_bottom_right = 18
		style.corner_radius_bottom_left = 18
		style.border_width_left = 1
		style.border_width_top = 1
		style.border_width_right = 1
		style.border_width_bottom = 1
		style.border_color = Color(1, 1, 1, 0.18)
		background.add_theme_stylebox_override("panel", style)
		wrapper.add_child(background)

	var label := Label.new()
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.text = str(item.get("label", item.get("key", "Verb")))
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.position = Vector2(16, 18)
	label.size = tag_size - Vector2(32, 36)
	label.add_theme_font_size_override("font_size", 20)
	var default_verb_color := Color(0.2039, 0.149, 0.1059, 1.0)
	var configured_verb_color := Color.from_string(
		str((current_runtime.get("global_settings", {}) as Dictionary).get("verb_text_color", "#34261b")),
		default_verb_color
	)
	label.add_theme_color_override("font_color", configured_verb_color)
	wrapper.add_child(label)

	var button := Button.new()
	button.flat = true
	button.focus_mode = Control.FOCUS_NONE
	button.disabled = not bool(item.get("enabled", false))
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND if not button.disabled else Control.CURSOR_ARROW
	button.text = ""
	button.position = Vector2.ZERO
	button.size = tag_size
	button.modulate = Color(1, 1, 1, 0.02)
	button.mouse_entered.connect(func() -> void:
		_on_verb_button_hover_state(true)
		_on_verb_button_hover(wrapper, true, button.disabled)
	)
	button.mouse_exited.connect(func() -> void:
		_on_verb_button_hover_state(false)
		_on_verb_button_hover(wrapper, false, button.disabled)
	)
	if not button.disabled:
		var verb_id: int = int(item.get("id", 0))
		button.pressed.connect(func() -> void:
			_on_verb_pressed(verb_id, wrapper)
		)
	wrapper.add_child(button)

	var resting_alpha: float = 1.0 if bool(item.get("enabled", false)) else 0.55
	wrapper.modulate = Color(1, 1, 1, 0.0)
	wrapper.scale = Vector2(0.84, 0.84)
	var menu_anchor: Vector2 = center_position
	if active_verb_menu.has("anchor"):
		menu_anchor = active_verb_menu["anchor"]
	wrapper.position = menu_anchor - (tag_size * 0.5)
	var tween := create_tween()
	tween.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	tween.parallel().tween_property(wrapper, "position", top_left, 0.22)
	tween.parallel().tween_property(wrapper, "scale", Vector2.ONE, 0.22)
	tween.parallel().tween_property(wrapper, "modulate:a", resting_alpha, 0.22)
	return wrapper


func _on_verb_button_hover(wrapper: Control, hovering: bool, disabled: bool) -> void:
	if disabled:
		return
	var base_position: Vector2 = wrapper.get_meta("base_position", wrapper.position)
	var target_position: Vector2 = base_position + (Vector2(0, -4) if hovering else Vector2.ZERO)
	var target_scale: Vector2 = Vector2.ONE * (1.04 if hovering else 1.0)
	var tween := create_tween()
	tween.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
	tween.parallel().tween_property(wrapper, "position", target_position, 0.12)
	tween.parallel().tween_property(wrapper, "scale", target_scale, 0.12)


func _animate_verb_selection(tag: Control) -> void:
	if tag == null:
		await get_tree().create_timer(0.14).timeout
		return
	for child in verb_menu_layer.get_children():
		if child == tag:
			continue
		if child is Control:
			var dismiss_tween := create_tween()
			dismiss_tween.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN)
			dismiss_tween.parallel().tween_property(child, "scale", Vector2(0.92, 0.92), 0.14)
			dismiss_tween.parallel().tween_property(child, "modulate:a", 0.0, 0.14)
	var confirm_tween := create_tween()
	confirm_tween.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	confirm_tween.parallel().tween_property(tag, "scale", Vector2(1.12, 1.12), 0.08)
	confirm_tween.parallel().tween_property(tag, "modulate:a", 1.0, 0.08)
	await confirm_tween.finished
	var settle_tween := create_tween()
	settle_tween.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN)
	settle_tween.parallel().tween_property(tag, "scale", Vector2(0.96, 0.96), 0.06)
	settle_tween.parallel().tween_property(tag, "modulate:a", 0.0, 0.06)
	await settle_tween.finished


func _clear_verb_menu_nodes() -> void:
	for child in verb_menu_layer.get_children():
		child.queue_free()


func _active_verb_menu_visible(visible: bool) -> void:
	verb_menu_layer.visible = visible


func _point_hits_verb_menu(global_position: Vector2) -> bool:
	if not verb_menu_layer.visible:
		return false
	for child in verb_menu_layer.get_children():
		if child is Control and (child as Control).get_global_rect().has_point(global_position):
			return true
	return false


func _point_hits_inventory_overlay(global_position: Vector2) -> bool:
	if not inventory_overlay_layer.visible:
		return false
	return inventory_overlay_frame.get_global_rect().has_point(global_position)


func _event_to_key_code(event: InputEventKey) -> String:
	match event.keycode:
		KEY_ESCAPE:
			return "Escape"
		KEY_ENTER, KEY_KP_ENTER:
			return "Enter"
		KEY_SPACE:
			return "Space"
		KEY_TAB:
			return "Tab"
		KEY_UP:
			return "ArrowUp"
		KEY_DOWN:
			return "ArrowDown"
		KEY_LEFT:
			return "ArrowLeft"
		KEY_RIGHT:
			return "ArrowRight"
	for letter_offset in range(26):
		if event.keycode == KEY_A + letter_offset:
			return "Key%s" % char(65 + letter_offset)
	for digit in range(10):
		if event.keycode == KEY_0 + digit:
			return "Digit%d" % digit
	return ""


func _configure_subtitle_theme() -> void:
	subtitle_primary.add_theme_font_size_override("font_size", 28)
	subtitle_secondary.add_theme_font_size_override("font_size", 20)
	subtitle_primary.add_theme_color_override("font_color", Color(1, 1, 1, 1))
	subtitle_secondary.add_theme_color_override("font_color", Color(0.784, 0.886, 1.0, 1.0))
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.05, 0.05, 0.06, 0.86)
	style.corner_radius_top_left = 12
	style.corner_radius_top_right = 12
	style.corner_radius_bottom_right = 12
	style.corner_radius_bottom_left = 12
	style.border_width_left = 1
	style.border_width_top = 1
	style.border_width_right = 1
	style.border_width_bottom = 1
	style.border_color = Color(1, 1, 1, 0.08)
	subtitle_panel.add_theme_stylebox_override("panel", style)
	subtitle_layer.visible = false


func _pick_script_line(line_ids: Array) -> Dictionary:
	var valid_ids: Array[int] = []
	for value in line_ids:
		var numeric_id: int = int(value)
		if numeric_id > 0:
			valid_ids.append(numeric_id)
	if valid_ids.is_empty():
		return {}
	var chosen_id: int = valid_ids[randi() % valid_ids.size()]
	for line_data in current_runtime.get("script_lines", []):
		if typeof(line_data) != TYPE_DICTIONARY:
			continue
		if int(line_data.get("line_id", 0)) == chosen_id:
			return line_data
	return {}


func _build_subtitle_payload(line: Dictionary) -> Dictionary:
	var primary_language: String = _normalized_language_value(_variable_value_by_name("primary_language", "en"), "en")
	var secondary_language: String = _normalized_language_value(_variable_value_by_name("secondary_language", "fr"), "fr")
	var primary_text: String = _resolve_line_text(line, primary_language)
	var secondary_text: String = _resolve_line_text(line, secondary_language)
	if primary_text.is_empty() and secondary_text.is_empty():
		return {}
	var max_length: int = maxi(primary_text.length(), secondary_text.length())
	return {
		"primary_text": primary_text,
		"secondary_text": secondary_text,
		"size_class": _subtitle_size_class(max_length),
	}


func _resolve_line_text(line: Dictionary, language: String) -> String:
	if line.is_empty() or language.is_empty():
		return ""
	for translation_data in line.get("translations", []):
		if typeof(translation_data) != TYPE_DICTIONARY:
			continue
		if str(translation_data.get("language", "")).strip_edges().to_lower() == language and str(translation_data.get("text", "")).strip_edges() != "":
			return str(translation_data.get("text", "")).strip_edges()
	if language == "en" and str(line.get("source_text", "")).strip_edges() != "":
		return str(line.get("source_text", "")).strip_edges()
	return ""


func _subtitle_size_class(max_length: int) -> String:
	if max_length <= 42:
		return "large"
	if max_length <= 72:
		return "medium"
	if max_length <= 108:
		return "small"
	return "xsmall"


func _apply_subtitle_size(size_class: String) -> void:
	match size_class:
		"large":
			subtitle_primary.add_theme_font_size_override("font_size", 30)
			subtitle_secondary.add_theme_font_size_override("font_size", 22)
		"medium":
			subtitle_primary.add_theme_font_size_override("font_size", 28)
			subtitle_secondary.add_theme_font_size_override("font_size", 20)
		"small":
			subtitle_primary.add_theme_font_size_override("font_size", 24)
			subtitle_secondary.add_theme_font_size_override("font_size", 18)
		_:
			subtitle_primary.add_theme_font_size_override("font_size", 21)
			subtitle_secondary.add_theme_font_size_override("font_size", 16)


func _apply_subtitle_payload(payload: Dictionary) -> void:
	_apply_subtitle_size(str(payload.get("size_class", "medium")))
	subtitle_primary.text = str(payload.get("primary_text", ""))
	subtitle_secondary.text = str(payload.get("secondary_text", ""))
	subtitle_secondary.visible = subtitle_secondary.text.strip_edges() != ""
	subtitle_panel.custom_minimum_size = Vector2(_subtitle_panel_width(), 0)


func _subtitle_panel_width() -> float:
	var max_width: float = maxf(320.0, scene_stage.size.x * 0.82)
	var primary_size: float = float(subtitle_primary.get_theme_font_size("font_size"))
	var secondary_size: float = float(subtitle_secondary.get_theme_font_size("font_size"))
	var primary_width: float = _measure_subtitle_text_width(subtitle_primary.text, primary_size)
	var secondary_width: float = _measure_subtitle_text_width(subtitle_secondary.text, secondary_size)
	return clampf(maxf(primary_width, secondary_width) + 64.0, 320.0, max_width)


func _measure_subtitle_text_width(text: String, font_size: float) -> float:
	var content: String = text.strip_edges()
	if content == "":
		return 0.0
	var font: Font = subtitle_primary.get_theme_font("font")
	if font == null:
		return maxf(120.0, content.length() * font_size * 0.58)
	return font.get_string_size(content, HORIZONTAL_ALIGNMENT_LEFT, -1.0, int(font_size)).x


func _show_subtitle(payload: Dictionary, duration_seconds: float) -> void:
	var token: int = subtitle_token + 1
	subtitle_token = token
	_apply_subtitle_payload(payload)
	subtitle_layer.modulate = Color(1, 1, 1, 0)
	subtitle_layer.visible = true
	var fade_in := create_tween()
	fade_in.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
	fade_in.tween_property(subtitle_layer, "modulate:a", 1.0, 0.16)
	await fade_in.finished
	await get_tree().create_timer(maxf(0.01, duration_seconds)).timeout
	await get_tree().create_timer(SUBTITLE_LINGER_SECONDS).timeout
	if token != subtitle_token:
		return
	var fade_out := create_tween()
	fade_out.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN)
	fade_out.tween_property(subtitle_layer, "modulate:a", 0.0, 0.14)
	await fade_out.finished
	if token == subtitle_token:
		_clear_subtitle()


func _clear_subtitle() -> void:
	subtitle_token += 1
	subtitle_layer.visible = false
	subtitle_layer.modulate = Color(1, 1, 1, 1)
	subtitle_primary.text = ""
	subtitle_secondary.text = ""
	subtitle_secondary.visible = false


func _play_audio_for_line(line: Dictionary, explicit_speaker_character_id: int = 0) -> void:
	var playback_token: int = audio_playback_token + 1
	audio_playback_token = playback_token
	narrator_player.stop()
	_clear_all_character_visemes()
	var subtitle_payload: Dictionary = _build_subtitle_payload(line)
	var sequence: Array = _build_audio_sequence(line)
	var speaker_character_id: int = _resolve_speaker_character_id(explicit_speaker_character_id)
	if not subtitle_payload.is_empty():
		_apply_subtitle_payload(subtitle_payload)
		subtitle_layer.visible = true
		subtitle_layer.modulate = Color(1, 1, 1, 1)
	for index in range(sequence.size()):
		if playback_token != audio_playback_token:
			return
		var item: Dictionary = sequence[index]
		await _play_audio_clip(
			narrator_player,
			str(item.get("asset_path", "")),
			_volume_for_channel("master_volume", "narrator_volume"),
			speaker_character_id,
			item
		)
		if index < sequence.size() - 1:
			await get_tree().create_timer(SEQUENTIAL_AUDIO_GAP_SECONDS).timeout
	if speaker_character_id > 0:
		_set_character_viseme_image(speaker_character_id, 0)
	if playback_token == audio_playback_token and subtitle_layer.visible:
		await get_tree().create_timer(SUBTITLE_LINGER_SECONDS).timeout
		if playback_token == audio_playback_token:
			_clear_subtitle()


func _build_audio_sequence(line: Dictionary) -> Array:
	var mode: String = _normalized_translation_mode(_variable_value_by_name("translation_mode", "sequential"), "sequential")
	var primary_language: String = _normalized_language_value(_variable_value_by_name("primary_language", "en"), "en")
	var secondary_language: String = _normalized_language_value(_variable_value_by_name("secondary_language", "fr"), "fr")
	if mode == "none":
		return []
	if mode == "primary_only":
		return _pick_audio_candidate(line, primary_language)
	if mode == "secondary_only":
		return _pick_audio_candidate(line, secondary_language)
	var result: Array = []
	result.append_array(_pick_audio_candidate(line, primary_language))
	result.append_array(_pick_audio_candidate(line, secondary_language))
	return result


func _pick_audio_candidate(line: Dictionary, language: String) -> Array:
	var candidates: Array = []
	for candidate_data in line.get("audio_candidates", []):
		if typeof(candidate_data) != TYPE_DICTIONARY:
			continue
		if str(candidate_data.get("language", "")).strip_edges().to_lower() != language:
			continue
		if str(candidate_data.get("asset_path", "")).strip_edges() == "":
			continue
		candidates.append(candidate_data)
	if candidates.is_empty():
		return []
	var selected: Array = []
	for candidate_data in candidates:
		if bool(candidate_data.get("selected", false)):
			selected.append(candidate_data)
	var choice_pool: Array = selected if not selected.is_empty() else [candidates[0]]
	var choice: Dictionary = choice_pool[randi() % choice_pool.size()]
	return [choice]


func _play_audio_clip(
	player: AudioStreamPlayer,
	asset_path: String,
	volume_linear: float,
	speaker_character_id: int = 0,
	candidate_data: Dictionary = {}
) -> void:
	if player == null:
		return
	var stream: AudioStream = _load_audio_stream(_resolve_runtime_path(asset_path))
	if stream == null:
		return
	player.stop()
	player.stream = stream
	player.volume_db = linear_to_db(clampf(volume_linear, 0.0001, 1.0))
	player.play()
	var timeout_seconds: float = maxf(0.1, stream.get_length() if stream.has_method("get_length") else 0.1)
	while player.playing:
		if speaker_character_id > 0:
			_update_character_viseme_from_audio(speaker_character_id, candidate_data, player.get_playback_position())
		await get_tree().process_frame
		if not player.playing:
			break
		timeout_seconds -= get_process_delta_time()
		if timeout_seconds <= 0:
			break
	player.stop()
	if speaker_character_id > 0:
		_set_character_viseme_image(speaker_character_id, 0)


func _crossfade_bgm(audio_asset_id: int, duration_seconds: float) -> void:
	var asset: Dictionary = _find_audio_asset(audio_asset_id, "bgm")
	if asset.is_empty():
		return
	var asset_path: String = str(asset.get("asset_path", ""))
	var stream: AudioStream = _load_audio_stream(_resolve_runtime_path(asset_path), true)
	if stream == null:
		return
	var target_volume_db: float = linear_to_db(clampf(_volume_for_channel("master_volume", "music_volume"), 0.0001, 1.0))
	var active_player: AudioStreamPlayer = _active_bgm_player()
	if current_bgm_asset_path == asset_path and active_player != null and active_player.playing:
		var settle_tween := create_tween()
		settle_tween.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
		settle_tween.tween_property(active_player, "volume_db", target_volume_db, maxf(0.05, duration_seconds * 0.35))
		await settle_tween.finished
		return
	var next_player: AudioStreamPlayer = _inactive_bgm_player()
	if next_player == null:
		return
	next_player.stop()
	next_player.stream = stream
	next_player.volume_db = -40.0
	next_player.play()
	var fade_duration: float = maxf(0.05, duration_seconds)
	var fade_tween := create_tween()
	fade_tween.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
	fade_tween.parallel().tween_property(next_player, "volume_db", target_volume_db, fade_duration)
	if active_player != null and active_player.playing:
		fade_tween.parallel().tween_property(active_player, "volume_db", -40.0, fade_duration)
	await fade_tween.finished
	if active_player != null:
		active_player.stop()
		active_player.stream = null
	active_bgm_player_index = 1 - active_bgm_player_index
	current_bgm_asset_path = asset_path


func _play_sfx(audio_asset_id: int) -> void:
	var asset: Dictionary = _find_audio_asset(audio_asset_id, "sfx")
	if asset.is_empty():
		return
	var stream: AudioStream = _load_audio_stream(_resolve_runtime_path(str(asset.get("asset_path", ""))))
	if stream == null:
		return
	sfx_player.stop()
	sfx_player.stream = stream
	sfx_player.volume_db = linear_to_db(clampf(_volume_for_channel("master_volume", "sfx_volume"), 0.0001, 1.0))
	sfx_player.play()


func _find_audio_asset(audio_asset_id: int, expected_kind: String = "") -> Dictionary:
	for asset_data in current_runtime.get("audio_assets", []):
		if typeof(asset_data) != TYPE_DICTIONARY:
			continue
		if int(asset_data.get("id", 0)) != audio_asset_id:
			continue
		if expected_kind != "" and str(asset_data.get("kind", "")) != expected_kind:
			continue
		return asset_data
	return {}


func _load_audio_stream(path: String, loop: bool = false) -> AudioStream:
	if path.is_empty():
		return null
	var cache_key: String = "%s|%s" % [path, "loop" if loop else "once"]
	if audio_stream_cache.has(cache_key):
		return audio_stream_cache[cache_key]
	var extension: String = path.get_extension().to_lower()
	if extension == "ogg":
		var ogg_stream := AudioStreamOggVorbis.load_from_file(path)
		if ogg_stream != null:
			ogg_stream.loop = loop
			audio_stream_cache[cache_key] = ogg_stream
		return ogg_stream
	if extension == "mp3":
		var mp3_stream := AudioStreamMP3.load_from_file(path)
		if mp3_stream != null:
			mp3_stream.loop = loop
			audio_stream_cache[cache_key] = mp3_stream
		return mp3_stream
	if extension == "wav":
		var wav_stream := AudioStreamWAV.load_from_file(path)
		if wav_stream != null and loop:
			wav_stream.loop_mode = AudioStreamWAV.LOOP_FORWARD
		if wav_stream != null:
			audio_stream_cache[cache_key] = wav_stream
		return wav_stream
	var resource: Resource = load(path)
	var stream := resource as AudioStream
	if loop and stream != null:
		if stream is AudioStreamOggVorbis:
			(stream as AudioStreamOggVorbis).loop = true
		elif stream is AudioStreamMP3:
			(stream as AudioStreamMP3).loop = true
		elif stream is AudioStreamWAV:
			(stream as AudioStreamWAV).loop_mode = AudioStreamWAV.LOOP_FORWARD
	if stream != null:
		audio_stream_cache[cache_key] = stream
	return stream


func _preload_audio_stream(path: String, loop: bool = false) -> void:
	if path.is_empty():
		return
	_load_audio_stream(path, loop)


func _resolve_speaker_character_id(explicit_character_id: int) -> int:
	if explicit_character_id > 0:
		var explicit_state: Dictionary = current_character_states.get(explicit_character_id, {})
		if not explicit_state.is_empty() and bool(explicit_state.get("visible", false)):
			return explicit_character_id
	var visible_characters: Array = _visible_character_states()
	if visible_characters.size() == 1:
		return int((visible_characters[0] as Dictionary).get("id", 0))
	return 0


func _update_character_viseme_from_audio(character_id: int, candidate_data: Dictionary, playback_position: float) -> void:
	var next_image_id: int = 0
	for event_data in candidate_data.get("viseme_events", []):
		if typeof(event_data) != TYPE_DICTIONARY:
			continue
		var start_seconds: float = float(event_data.get("start_seconds", 0.0))
		var end_seconds: float = float(event_data.get("end_seconds", 0.0))
		if playback_position >= start_seconds and playback_position < end_seconds:
			next_image_id = _resolve_character_viseme_image_id(character_id, str(event_data.get("viseme_key", "")))
			break
	_set_character_viseme_image(character_id, next_image_id)


func _set_character_viseme_image(character_id: int, image_id: int) -> void:
	var character_state: Dictionary = current_character_states.get(character_id, {})
	if character_state.is_empty():
		return
	if int(character_state.get("viseme_image_id", 0)) == image_id:
		return
	character_state["viseme_image_id"] = image_id
	current_character_states[character_id] = character_state
	_render_current_scene()


func _clear_all_character_visemes() -> void:
	var changed: bool = false
	for character_id in current_character_states.keys():
		var state: Dictionary = current_character_states[character_id]
		if int(state.get("viseme_image_id", 0)) == 0:
			continue
		state["viseme_image_id"] = 0
		current_character_states[character_id] = state
		changed = true
	if changed:
		_render_current_scene()


func _normalized_language_value(value: Variant, fallback: String) -> String:
	var trimmed: String = str(value).strip_edges().to_lower()
	return trimmed if trimmed != "" else fallback


func _normalized_translation_mode(value: Variant, fallback: String) -> String:
	var trimmed: String = str(value).strip_edges().to_lower()
	if trimmed in ["none", "primary_only", "secondary_only", "sequential"]:
		return trimmed
	return fallback


func _volume_for_channel(master_variable_name: String, channel_variable_name: String) -> float:
	var master_volume: float = _normalized_volume_value(_variable_value_by_name(master_variable_name, 5), 5)
	var channel_volume: float = _normalized_volume_value(_variable_value_by_name(channel_variable_name, 5), 5)
	return (master_volume / 10.0) * (channel_volume / 10.0)


func _normalized_volume_value(value: Variant, fallback: float) -> float:
	var numeric: float = float(value)
	if not is_finite(numeric):
		return fallback
	return clampf(numeric, 0.0, 10.0)


func _stop_media_playback() -> void:
	audio_playback_token += 1
	narrator_player.stop()
	_clear_all_character_visemes()
	if bgm_player_a != null:
		bgm_player_a.stop()
		bgm_player_a.stream = null
		bgm_player_a.volume_db = 0.0
	if bgm_player_b != null:
		bgm_player_b.stop()
		bgm_player_b.stream = null
		bgm_player_b.volume_db = 0.0
	active_bgm_player_index = 0
	current_bgm_asset_path = ""
	sfx_player.stop()


func _active_bgm_player() -> AudioStreamPlayer:
	return bgm_player_a if active_bgm_player_index == 0 else bgm_player_b


func _inactive_bgm_player() -> AudioStreamPlayer:
	return bgm_player_b if active_bgm_player_index == 0 else bgm_player_a


func _on_verb_button_hover_state(hovering: bool) -> void:
	if active_verb_menu.is_empty():
		return
	if hovering:
		if not verb_menu_hovered and verb_menu_expires_at_msec > 0:
			verb_menu_remaining_msec = max(0, verb_menu_expires_at_msec - Time.get_ticks_msec())
		verb_menu_hovered = true
		verb_menu_expires_at_msec = 0
		return
	verb_menu_hovered = false
	var remaining_msec: int = verb_menu_remaining_msec
	if remaining_msec <= 0:
		remaining_msec = int(round(_verb_menu_timeout_seconds() * 1000.0))
	verb_menu_expires_at_msec = Time.get_ticks_msec() + remaining_msec


func _verb_menu_timeout_seconds() -> float:
	var global_settings: Dictionary = current_runtime.get("global_settings", {})
	return float(global_settings.get("verb_menu_timeout_seconds", 4.0))


func _verb_label(verb_data: Dictionary) -> String:
	var primary_language: String = str(_variable_value_by_name("primary_language", "en"))
	var labels: Dictionary = verb_data.get("labels", {})
	var primary_base: String = primary_language.split("-")[0].split("_")[0]
	if labels.has(primary_language):
		return str(labels[primary_language])
	if labels.has(primary_base):
		return str(labels[primary_base])
	if labels.has("en"):
		return str(labels["en"])
	for key in labels.keys():
		return str(labels[key])
	return str(verb_data.get("key", "Verb"))


func _variable_value_by_name(variable_name: String, fallback: Variant) -> Variant:
	for variable_data in current_runtime.get("variables", []):
		if typeof(variable_data) != TYPE_DICTIONARY:
			continue
		if str(variable_data.get("name", "")) != variable_name:
			continue
		var variable_id: int = int(variable_data.get("id", 0))
		return current_variables.get(variable_id, variable_data.get("default_value", fallback))
	return fallback
