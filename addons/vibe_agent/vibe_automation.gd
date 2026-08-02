@tool
extends RefCounted

const ALLOWED_METHODS := {
	"set_name": true, "set_position": true, "set_global_position": true,
	"set_rotation": true, "set_rotation_degrees": true, "set_scale": true,
	"set_visible": true, "set_process": true, "set_physics_process": true,
	"set_modulate": true, "set_self_modulate": true,
}

var _editor: EditorInterface
var _undo: EditorUndoRedoManager
var _handlers := {}


func _init(editor: EditorInterface, undo: EditorUndoRedoManager):
	_editor = editor
	_undo = undo
	_handlers = {
		"create_node": _action_create_node,
		"rename_children": _action_rename_children,
	}


func apply(action: Dictionary):
	var name := String(action.get("action", ""))
	if name.is_empty():
		print("Vibe: automation action missing a name")
		return
	var params = action.get("params", {})
	if typeof(params) != TYPE_DICTIONARY:
		params = {}

	if _handlers.has(name):
		_handlers[name].call(params)
	elif ALLOWED_METHODS.get(name, false):
		_dispatch_method(name, params)
	else:
		print("Vibe: automation action not allowed: ", name)


func _resolve_node(scene_path: String) -> Node:
	var root := _editor.get_edited_scene_root()
	if root == null:
		return null
	if scene_path.is_empty() or scene_path == ".":
		return root
	return root.get_node_or_null(NodePath(scene_path))


func _dispatch_method(method: String, params: Dictionary):
	var node := _resolve_node(String(params.get("target_node_path", params.get("node_path", "."))))
	if node == null:
		print("Vibe: automation target not found")
		return
	if not node.has_method(method):
		print("Vibe: target does not implement ", method)
		return
	node.callv(method, _coerce_args(params.get("args", [])))
	print("Vibe: applied ", method, " on ", node.name)


func _action_create_node(params: Dictionary):
	var target := _resolve_node(String(params.get("target_node_path", ".")))
	if target == null:
		print("Vibe: automation target not found")
		return
	var node_type := _canonical_type(String(params.get("node_type", "Node")))
	if not ClassDB.class_exists(node_type) or not ClassDB.is_parent_class(node_type, "Node"):
		print("Vibe: unsupported node type: ", node_type)
		return

	var count := int(params.get("count", 1))
	var pattern := String(params.get("name_pattern", "child_%d"))
	var owner := target.owner if target.owner != null else _editor.get_edited_scene_root()
	for index in range(count):
		var child: Node = ClassDB.instantiate(node_type)
		child.name = _format_name(pattern, index)
		target.add_child(child, true)
		child.owner = owner
	print("Vibe: created ", count, " ", node_type, " under ", target.name)


func _action_rename_children(params: Dictionary):
	var target := _resolve_node(String(params.get("target_node_path", ".")))
	if target == null:
		print("Vibe: automation target not found")
		return
	var pattern := String(params.get("pattern", "child_%d"))
	if not pattern.contains("%d"):
		print("Vibe: rename pattern must contain %d")
		return
	var count := target.get_child_count()
	if count == 0:
		print("Vibe: target has no children to rename")
		return

	var start := int(params.get("start_index", 0))
	_undo.create_action("Vibe Rename Children")
	for index in range(count):
		var child := target.get_child(index)
		_undo.add_do_property(child, "name", pattern % [start + index])
		_undo.add_undo_property(child, "name", String(child.name))
	_undo.commit_action()
	print("Vibe: renamed ", count, " children on ", target.name)


func _format_name(pattern: String, index: int) -> String:
	return pattern % [index] if pattern.contains("%d") else "%s_%d" % [pattern, index]


func _canonical_type(node_type: String) -> String:
	for known in ClassDB.get_class_list():
		if String(known).to_lower() == node_type.to_lower():
			return String(known)
	return node_type


func _coerce_args(args) -> Array:
	if args is Array:
		var vector = _numeric_vector(args)
		return [vector] if vector != null else args.map(_coerce_value)
	return [_coerce_value(args)]


func _coerce_value(value):
	if value is Array:
		var vector = _numeric_vector(value)
		return vector if vector != null else value.map(_coerce_value)
	return value


func _numeric_vector(values: Array):
	for item in values:
		if typeof(item) != TYPE_INT and typeof(item) != TYPE_FLOAT:
			return null
	match values.size():
		2:
			return Vector2(float(values[0]), float(values[1]))
		3:
			return Vector3(float(values[0]), float(values[1]), float(values[2]))
		4:
			for item in values:
				if float(item) < 0.0 or float(item) > 1.0:
					return null
			return Color(float(values[0]), float(values[1]), float(values[2]), float(values[3]))
	return null
