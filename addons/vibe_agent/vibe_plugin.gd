@tool
extends EditorPlugin

const BACKEND_URL := "http://127.0.0.1:8000/vibe"
const IMAGE_EXTENSIONS := ["png", "jpg", "jpeg", "webp"]
const ALLOWED_METHODS := {
	"add_child": false,
	"queue_free": false,
	"free": false,
	"set_name": true,
	"set_position": true,
	"set_global_position": true,
	"set_rotation": true,
	"set_rotation_degrees": true,
	"set_scale": true,
	"set_visible": true,
	"set_process": true,
	"set_physics_process": true,
	"set_modulate": true,
	"set_self_modulate": true,
}


class FilesystemCreateContextMenuPlugin:
	extends EditorContextMenuPlugin

	var owner

	func _init(p_owner):
		owner = p_owner

	func _popup_menu(_paths: PackedStringArray):
		add_context_menu_item("Vibe: Generate Asset", Callable(owner, "_on_generate_context"))


class FilesystemAssetContextMenuPlugin:
	extends EditorContextMenuPlugin

	var owner

	func _init(p_owner):
		owner = p_owner

	func _popup_menu(paths: PackedStringArray):
		if paths.size() == 1 and owner._is_supported_image_path(paths[0]):
			add_context_menu_item("Vibe: Modify Asset", Callable(owner, "_on_modify_context"))


class SceneTreeContextMenuPlugin:
	extends EditorContextMenuPlugin

	var owner

	func _init(p_owner):
		owner = p_owner

	func _popup_menu(paths: PackedStringArray):
		if not paths.is_empty():
			add_context_menu_item("Vibe: Automation", Callable(owner, "_on_automation_context"))


var http_request: HTTPRequest
var prompt_dialog: ConfirmationDialog
var prompt_summary_label: Label
var prompt_example_label: Label
var prompt_input: TextEdit

var filesystem_create_menu
var filesystem_asset_menu
var scene_tree_menu
var generic_action_handlers = {}

var active_dialog_kind = ""
var active_dialog_context = {}
var pending_request_kind = ""
var pending_request_context = {}


func _enter_tree():
	http_request = HTTPRequest.new()
	add_child(http_request)
	http_request.request_completed.connect(_on_request_completed)

	_create_prompt_dialog()

	filesystem_create_menu = FilesystemCreateContextMenuPlugin.new(self)
	filesystem_asset_menu = FilesystemAssetContextMenuPlugin.new(self)
	scene_tree_menu = SceneTreeContextMenuPlugin.new(self)
	generic_action_handlers = {
		"create_node": Callable(self, "_action_create_node"),
		"rename_children": Callable(self, "_action_rename_children"),
	}

	add_context_menu_plugin(EditorContextMenuPlugin.CONTEXT_SLOT_FILESYSTEM_CREATE, filesystem_create_menu)
	add_context_menu_plugin(EditorContextMenuPlugin.CONTEXT_SLOT_FILESYSTEM, filesystem_asset_menu)
	add_context_menu_plugin(EditorContextMenuPlugin.CONTEXT_SLOT_SCENE_TREE, scene_tree_menu)


func _exit_tree():
	if filesystem_create_menu:
		remove_context_menu_plugin(filesystem_create_menu)
	if filesystem_asset_menu:
		remove_context_menu_plugin(filesystem_asset_menu)
	if scene_tree_menu:
		remove_context_menu_plugin(scene_tree_menu)

	if prompt_dialog:
		prompt_dialog.queue_free()
	if http_request:
		http_request.queue_free()


func _create_prompt_dialog():
	prompt_dialog = ConfirmationDialog.new()
	prompt_dialog.title = "Vibe"
	prompt_dialog.min_size = Vector2(560, 320)
	prompt_dialog.get_ok_button().text = "Run"
	prompt_dialog.confirmed.connect(_on_prompt_confirmed)

	var root = VBoxContainer.new()
	root.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.custom_minimum_size = Vector2(520, 260)
	prompt_dialog.add_child(root)

	prompt_summary_label = Label.new()
	prompt_summary_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(prompt_summary_label)

	prompt_example_label = Label.new()
	prompt_example_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(prompt_example_label)

	prompt_input = TextEdit.new()
	prompt_input.custom_minimum_size = Vector2(520, 180)
	prompt_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	prompt_input.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(prompt_input)

	get_editor_interface().get_base_control().add_child(prompt_dialog)


func _is_supported_image_path(path: String) -> bool:
	return path.get_extension().to_lower() in IMAGE_EXTENSIONS


func _current_folder_path() -> String:
	var current_path = get_editor_interface().get_current_path()
	if current_path.is_empty():
		return "res://"
	if _is_supported_image_path(current_path):
		return current_path.get_base_dir()
	return current_path


func _selected_folder_from_context(selection: Array) -> String:
	if not selection.is_empty():
		var first = selection[0]
		if first is Array and not first.is_empty():
			return str(first[0])
		if first is PackedStringArray and not first.is_empty():
			return str(first[0])
		return str(first)
	return _current_folder_path()


func _selected_asset_from_context(selection: Array) -> String:
	if selection.is_empty():
		return ""
	var first = selection[0]
	if first is Array and not first.is_empty():
		return str(first[0])
	if first is PackedStringArray and not first.is_empty():
		return str(first[0])
	return str(first)


func _scene_relative_path(node: Node) -> String:
	var scene_root = get_editor_interface().get_edited_scene_root()
	if scene_root == null:
		return ""
	if node == scene_root:
		return "."
	return str(scene_root.get_path_to(node))


func _serialize_selected_nodes(nodes: Array) -> Array:
	var serialized: Array = []
	for item in nodes:
		if item is Node:
			var node: Node = item
			var child_names: Array = []
			for child in node.get_children():
				if child is Node:
					child_names.append(String(child.name))

			serialized.append(
				{
					"scene_path": _scene_relative_path(node),
					"name": String(node.name),
					"type": node.get_class(),
					"child_count": node.get_child_count(),
					"child_names": child_names,
				}
			)
	return serialized


func _normalize_context_items(selection) -> Array:
	if selection is Array:
		return selection
	if selection == null:
		return []
	return [selection]


func _open_prompt_dialog(kind: String, summary: String, example: String, confirm_text: String, context: Dictionary):
	active_dialog_kind = kind
	active_dialog_context = context

	prompt_dialog.title = "Vibe: " + confirm_text
	prompt_dialog.get_ok_button().text = confirm_text
	prompt_summary_label.text = summary
	prompt_example_label.text = example
	prompt_input.clear()
	prompt_dialog.popup_centered(Vector2i(560, 320))
	prompt_input.grab_focus()


func _on_generate_context(selection):
	var items = _normalize_context_items(selection)
	var folder_path = _selected_folder_from_context(items)
	_open_prompt_dialog(
		"generate",
		"Generate a new asset in %s" % folder_path,
		"Example: I want a 32x32 pixel style pickaxe icon",
		"Generate",
		{"folder_path": folder_path},
	)


func _on_modify_context(selection):
	var items = _normalize_context_items(selection)
	var asset_path = _selected_asset_from_context(items)
	if asset_path.is_empty():
		return

	_open_prompt_dialog(
		"modify",
		"Modify image asset %s" % asset_path,
		"Example: Resize the image into 16:9",
		"Modify",
		{"asset_path": asset_path},
	)


func _on_automation_context(selection):
	var items = _normalize_context_items(selection)
	var selected_nodes = _serialize_selected_nodes(items)
	if selected_nodes.is_empty():
		return

	_open_prompt_dialog(
		"automate",
		"Automate the selected scene tree node(s)",
		'Example: Rename all children start from 0 with "child_%d" format',
		"Automate",
		{"selected_nodes": selected_nodes},
	)


func _on_prompt_confirmed():
	var prompt = prompt_input.text.strip_edges()
	if prompt.is_empty():
		print("Vibe prompt cannot be empty")
		return

	match active_dialog_kind:
		"generate":
			_send_request(
				"generate",
				{
					"prompt": prompt,
					"folder_path": String(active_dialog_context.get("folder_path", "res://")),
				}
			)
		"modify":
			_send_request(
				"modify",
				{
					"prompt": prompt,
					"asset_path": String(active_dialog_context.get("asset_path", "")),
				}
			)
		"automate":
			_send_request(
				"automate",
				{
					"prompt": prompt,
					"selected_nodes": active_dialog_context.get("selected_nodes", []),
				}
			)


func _send_request(request_kind: String, payload: Dictionary):
	if http_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		print("Vibe request already in flight")
		return

	pending_request_kind = request_kind
	pending_request_context = payload

	var error = http_request.request(
		BACKEND_URL + "/" + request_kind,
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(payload)
	)
	if error != OK:
		print("Failed to send Vibe request: ", error)
		pending_request_kind = ""
		pending_request_context = {}
		return

	print("Vibe request sent: ", request_kind)


func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray):
	pending_request_kind = ""
	pending_request_context = {}

	if result != HTTPRequest.RESULT_SUCCESS:
		print("HTTP request failed: ", result)
		return

	var body_text = body.get_string_from_utf8()
	var payload = JSON.parse_string(body_text)
	if payload == null or typeof(payload) != TYPE_DICTIONARY:
		print("Failed to parse backend JSON: ", body_text)
		return

	if response_code >= 400:
		print("Backend returned HTTP error: ", response_code, " body: ", payload)

	var status = String(payload.get("status", ""))
	if status != "success":
		print("Backend processing failed: ", payload.get("message", "unknown error"))
		return

	var msg_type = String(payload.get("type", ""))
	if msg_type == "asset":
		_handle_asset_response(payload)
	elif msg_type == "automation":
		_handle_automation_response(payload)
	else:
		print("Unknown backend response: ", payload)


func _handle_asset_response(payload: Dictionary):
	var file_path = String(payload.get("file_path", ""))
	print("Asset ready: ", file_path)
	get_editor_interface().get_resource_filesystem().scan()
	if not file_path.is_empty():
		get_editor_interface().select_file(file_path)


func _handle_automation_response(payload: Dictionary):
	var actions = payload.get("actions", [])
	if typeof(actions) != TYPE_ARRAY:
		var legacy_action = payload.get("action", {})
		if typeof(legacy_action) == TYPE_DICTIONARY:
			actions = [legacy_action]
		else:
			print("Automation response missing action payload")
			return

	if actions.is_empty():
		print("Automation response contained no actions")
		return

	for action in actions:
		if typeof(action) == TYPE_DICTIONARY:
			_apply_automation_action(action)


func _canonical_node_type_name(node_type: String) -> String:
	var lowered = node_type.to_lower()
	var aliases = {
		"node": "Node",
		"node2d": "Node2D",
		"node3d": "Node3D",
		"sprite2d": "Sprite2D",
		"sprite3d": "Sprite3D",
		"area2d": "Area2D",
		"area3d": "Area3D",
		"marker2d": "Marker2D",
		"marker3d": "Marker3D",
		"meshinstance3d": "MeshInstance3D",
		"staticbody2d": "StaticBody2D",
		"staticbody3d": "StaticBody3D",
	}
	if aliases.has(lowered):
		return String(aliases[lowered])
	return node_type


func _is_numeric_array(values: Array) -> bool:
	for item in values:
		if typeof(item) != TYPE_INT and typeof(item) != TYPE_FLOAT:
			return false
	return true


func _coerce_dynamic_value(value):
	if typeof(value) == TYPE_ARRAY:
		if _is_numeric_array(value):
			if value.size() == 2:
				return Vector2(float(value[0]), float(value[1]))
			if value.size() == 3:
				return Vector3(float(value[0]), float(value[1]), float(value[2]))
			if value.size() == 4:
				var looks_like_color = true
				for item in value:
					var f = float(item)
					if f < 0.0 or f > 1.0:
						looks_like_color = false
						break
				if looks_like_color:
					return Color(float(value[0]), float(value[1]), float(value[2]), float(value[3]))

		var converted: Array = []
		for item in value:
			converted.append(_coerce_dynamic_value(item))
		return converted

	if typeof(value) == TYPE_DICTIONARY:
		if value.has("type") and value.has("value"):
			var type_name = String(value.get("type", ""))
			var inner_value = value.get("value")
			if type_name == "NodePath":
				return NodePath(String(inner_value))
			if type_name == "Vector2" and typeof(inner_value) == TYPE_ARRAY and inner_value.size() >= 2:
				return Vector2(float(inner_value[0]), float(inner_value[1]))
			if type_name == "Vector3" and typeof(inner_value) == TYPE_ARRAY and inner_value.size() >= 3:
				return Vector3(float(inner_value[0]), float(inner_value[1]), float(inner_value[2]))
			if type_name == "Color" and typeof(inner_value) == TYPE_ARRAY and inner_value.size() >= 3:
				return Color(
					float(inner_value[0]),
					float(inner_value[1]),
					float(inner_value[2]),
					float(inner_value[3]) if inner_value.size() >= 4 else 1.0
				)
		if value.has("node_path"):
			return NodePath(String(value.get("node_path", ".")))
		if value.has("x") and value.has("y") and value.has("z"):
			return Vector3(float(value["x"]), float(value["y"]), float(value["z"]))
		if value.has("x") and value.has("y"):
			return Vector2(float(value["x"]), float(value["y"]))
		if value.has("r") and value.has("g") and value.has("b"):
			return Color(
				float(value["r"]),
				float(value["g"]),
				float(value["b"]),
				float(value.get("a", 1.0))
			)
	return value


func _coerce_args(args_value) -> Array:
	if typeof(args_value) == TYPE_ARRAY:
		if _is_numeric_array(args_value):
			if args_value.size() == 2:
				return [Vector2(float(args_value[0]), float(args_value[1]))]
			if args_value.size() == 3:
				return [Vector3(float(args_value[0]), float(args_value[1]), float(args_value[2]))]
			if args_value.size() == 4:
				var looks_like_color = true
				for item in args_value:
					var f = float(item)
					if f < 0.0 or f > 1.0:
						looks_like_color = false
						break
				if looks_like_color:
					return [Color(float(args_value[0]), float(args_value[1]), float(args_value[2]), float(args_value[3]))]

		var converted: Array = []
		for item in args_value:
			converted.append(_coerce_dynamic_value(item))
		return converted
	return [_coerce_dynamic_value(args_value)]


func _format_name_pattern(pattern: String, index: int) -> String:
	if pattern.contains("%d"):
		return pattern % [index]
	return "%s_%d" % [pattern, index]


func _owner_for_new_node(target_node: Node) -> Node:
	var scene_root = get_tree().edited_scene_root
	if scene_root == null:
		scene_root = get_editor_interface().get_edited_scene_root()
	if target_node.owner != null:
		return target_node.owner
	return scene_root


func _extract_action_params(action: Dictionary) -> Dictionary:
	var params = action.get("params", {})
	if typeof(params) == TYPE_DICTIONARY:
		return params
	return {}


func _action_create_node(params: Dictionary):
	var target_path = String(params.get("target_node_path", "."))
	var target_node = _resolve_scene_node(target_path)
	if target_node == null:
		print("Automation target node not found: ", target_path)
		return

	var node_type = _canonical_node_type_name(String(params.get("node_type", "Node")))
	if not ClassDB.class_exists(node_type):
		print("Unsupported node type for creation: ", node_type)
		return

	var count = int(params.get("count", 1))
	var pattern = String(params.get("name_pattern", "child_%d"))
	var owner = _owner_for_new_node(target_node)

	for index in range(count):
		var instance = ClassDB.instantiate(node_type)
		if not (instance is Node):
			print("Class is not a Node: ", node_type)
			return
		var child: Node = instance
		child.name = _format_name_pattern(pattern, index)
		target_node.add_child(child, true)
		child.owner = owner

	print("Automation applied: created ", count, " ", node_type, " children on ", target_node.name)


func _action_rename_children(params: Dictionary):
	var target_path = String(params.get("target_node_path", "."))
	var target_node = _resolve_scene_node(target_path)
	if target_node == null:
		print("Automation target node not found: ", target_path)
		return

	var pattern = String(params.get("pattern", "child_%d"))
	if not pattern.contains("%d"):
		print("Automation pattern must contain %d")
		return

	var start_index = int(params.get("start_index", 0))
	var child_count = target_node.get_child_count()
	if child_count == 0:
		print("Target node has no children to rename")
		return

	var undo_redo = get_undo_redo()
	undo_redo.create_action("Vibe Rename Children")
	for index in range(child_count):
		var child = target_node.get_child(index)
		if not (child is Node):
			continue
		var new_name = pattern % [start_index + index]
		undo_redo.add_do_property(child, "name", new_name)
		undo_redo.add_undo_property(child, "name", String(child.name))
	undo_redo.commit_action()

	print("Automation applied: renamed ", child_count, " children on ", target_node.name)


func _resolve_scene_node(scene_path: String):
	var scene_root = get_editor_interface().get_edited_scene_root()
	if scene_root == null:
		return null
	if scene_path.is_empty() or scene_path == ".":
		return scene_root
	return scene_root.get_node_or_null(NodePath(scene_path))


func _dispatch_node_method(action_name: String, params: Dictionary):
	var target_path = String(params.get("target_node_path", params.get("node_path", ".")))
	var target_node = _resolve_scene_node(target_path)
	if target_node == null:
		print("Automation target node not found: ", target_path)
		return

	if not target_node.has_method(action_name):
		print("Automation target does not implement method: ", action_name)
		return

	var args = _coerce_args(params.get("args", []))
	target_node.callv(action_name, args)
	print("Automation applied: called ", action_name, " on ", target_node.name)


func _apply_automation_action(action: Dictionary):
	var action_type = String(action.get("action", ""))
	var params = _extract_action_params(action)
	if action_type.is_empty():
		print("Automation action is missing a name")
		return

	if generic_action_handlers.has(action_type):
		generic_action_handlers[action_type].call(params)
		return

	if not ALLOWED_METHODS.get(action_type, false):
		print("Automation action is not allowed: ", action_type)
		return

	_dispatch_node_method(action_type, params)
