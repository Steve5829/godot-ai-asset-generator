@tool
extends EditorPlugin

const IMAGE_EXTENSIONS := ["png", "jpg", "jpeg", "webp"]

const VibeClient := preload("res://addons/vibe_agent/vibe_client.gd")
const VibeDialog := preload("res://addons/vibe_agent/vibe_dialog.gd")
const VibeAutomation := preload("res://addons/vibe_agent/vibe_automation.gd")


class VibeContextMenu:
	extends EditorContextMenuPlugin

	var _items: Array

	func _init(items: Array):
		_items = items

	func _popup_menu(paths: PackedStringArray):
		for item in _items:
			var guard: Callable = item.get("guard", Callable())
			if guard.is_valid() and not guard.call(paths):
				continue
			add_context_menu_item(item["label"], item["callback"])


var _client
var _dialog
var _automation
var _menus: Array = []
var _request_builders := {}
var _response_handlers := {}


func _enter_tree():
	_client = VibeClient.new()
	add_child(_client)
	_client.succeeded.connect(_on_client_succeeded)
	_client.failed.connect(_on_client_failed)
	_client.options_loaded.connect(_on_options_loaded)

	_dialog = VibeDialog.new()
	get_editor_interface().get_base_control().add_child(_dialog)
	_dialog.submitted.connect(_on_dialog_submitted)

	_automation = VibeAutomation.new(get_editor_interface(), get_undo_redo())

	_request_builders = {
		"generate": _build_generate_request,
		"modify": _build_modify_request,
		"automate": _build_automate_request,
	}
	_response_handlers = {
		"asset": _handle_asset_response,
		"automation": _handle_automation_response,
	}

	_register_menus()
	_client.fetch_options()


func _exit_tree():
	for menu in _menus:
		remove_context_menu_plugin(menu)
	_menus.clear()
	if _dialog:
		_dialog.queue_free()
	if _client:
		_client.queue_free()


func _register_menus():
	var generate_item := {"label": "Vibe: Generate Asset", "callback": _context_generate}
	var modify_item := {"label": "Vibe: Modify Asset", "callback": _context_modify, "guard": _guard_single_image}
	var automate_item := {"label": "Vibe: Automation", "callback": _context_automate, "guard": _guard_non_empty}

	var slots := {
		EditorContextMenuPlugin.CONTEXT_SLOT_FILESYSTEM_CREATE: [generate_item],
		EditorContextMenuPlugin.CONTEXT_SLOT_FILESYSTEM: [generate_item, modify_item],
		EditorContextMenuPlugin.CONTEXT_SLOT_SCENE_TREE: [automate_item],
	}
	for slot in slots:
		var menu := VibeContextMenu.new(slots[slot])
		add_context_menu_plugin(slot, menu)
		_menus.append(menu)


func _guard_single_image(paths: PackedStringArray) -> bool:
	return paths.size() == 1 and _is_supported_image_path(paths[0])


func _guard_non_empty(paths: PackedStringArray) -> bool:
	return not paths.is_empty()


func _context_generate(selection):
	var folder := _selected_folder(_as_array(selection))
	_dialog.open("generate", "Generate a new asset in %s" % folder, {"folder_path": folder})


func _context_modify(selection):
	var asset := _first_path(_as_array(selection))
	if not asset.is_empty():
		_dialog.open("modify", "Modify image asset %s" % asset, {"asset_path": asset})


func _context_automate(selection):
	var nodes := _serialize_nodes(_as_array(selection))
	if not nodes.is_empty():
		_dialog.open("automate", "Automate the selected scene tree node(s)", {"selected_nodes": nodes})


func _on_dialog_submitted(kind: String, prompt: String, context: Dictionary):
	var request: Dictionary = _request_builders[kind].call(prompt, context)
	_client.send(request["endpoint"], request["payload"])


func _build_generate_request(prompt: String, context: Dictionary) -> Dictionary:
	return {
		"endpoint": "generate",
		"payload": {
			"prompt": prompt,
			"folder": ProjectSettings.globalize_path(String(context.get("folder_path", "res://"))),
			"style": String(context.get("style", "none")),
			"provider": String(context.get("provider", "pixellab")),
		},
	}


func _build_modify_request(prompt: String, context: Dictionary) -> Dictionary:
	return {
		"endpoint": "modify",
		"payload": {
			"prompt": prompt,
			"asset_path": ProjectSettings.globalize_path(String(context.get("asset_path", ""))),
		},
	}


func _build_automate_request(prompt: String, context: Dictionary) -> Dictionary:
	return {
		"endpoint": "automate",
		"payload": {
			"prompt": prompt,
			"selected_nodes": context.get("selected_nodes", []),
		},
	}


func _on_client_succeeded(payload: Dictionary):
	var msg_type := String(payload.get("type", ""))
	if _response_handlers.has(msg_type):
		_response_handlers[msg_type].call(payload)
	else:
		print("Vibe: unhandled response type '", msg_type, "'")


func _on_client_failed(message: String):
	print("Vibe: ", message)


func _on_options_loaded(styles, providers):
	_dialog.set_options(styles, providers)


func _handle_asset_response(payload: Dictionary):
	var file_path := String(payload.get("file_path", ""))
	print("Vibe: asset ready — ", file_path)
	get_editor_interface().get_resource_filesystem().scan()
	if not file_path.is_empty():
		get_editor_interface().select_file(ProjectSettings.localize_path(file_path))


func _handle_automation_response(payload: Dictionary):
	var actions = payload.get("actions", [])
	if typeof(actions) != TYPE_ARRAY or actions.is_empty():
		print("Vibe: automation response contained no actions")
		return
	for action in actions:
		if typeof(action) == TYPE_DICTIONARY:
			_automation.apply(action)


func _as_array(selection) -> Array:
	if selection is Array:
		return selection
	if selection == null:
		return []
	return [selection]


func _first_path(selection: Array) -> String:
	if selection.is_empty():
		return ""
	var first = selection[0]
	if (first is Array or first is PackedStringArray) and not first.is_empty():
		return str(first[0])
	return str(first)


func _is_supported_image_path(path: String) -> bool:
	return path.get_extension().to_lower() in IMAGE_EXTENSIONS


func _current_folder() -> String:
	var path := get_editor_interface().get_current_path()
	if path.is_empty():
		return "res://"
	return path.get_base_dir() if _is_supported_image_path(path) else path


func _selected_folder(selection: Array) -> String:
	var path := _first_path(selection)
	if path.is_empty():
		return _current_folder()
	if not path.get_extension().is_empty():
		return path.get_base_dir()
	return path


func _serialize_nodes(selection: Array) -> Array:
	var scene_root := get_editor_interface().get_edited_scene_root()
	var out: Array = []
	for item in selection:
		if not (item is Node):
			continue
		var node: Node = item
		var child_names: Array = []
		for child in node.get_children():
			child_names.append(String(child.name))
		out.append({
			"scene_path": _scene_relative_path(node, scene_root),
			"name": String(node.name),
			"type": node.get_class(),
			"child_count": node.get_child_count(),
			"child_names": child_names,
		})
	return out


func _scene_relative_path(node: Node, scene_root: Node) -> String:
	if scene_root == null:
		return ""
	if node == scene_root:
		return "."
	return str(scene_root.get_path_to(node))
