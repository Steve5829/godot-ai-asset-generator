@tool
extends ConfirmationDialog

signal submitted(kind: String, prompt: String, context: Dictionary)

const ACTIONS := {
	"generate": {
		"title": "Generate",
		"example": "Example: a 32x32 iron sword icon, or a minecraft grass block",
		"show_settings": true,
	},
	"modify": {
		"title": "Modify",
		"example": "Example: resize the image into 16:9",
		"show_settings": false,
	},
	"automate": {
		"title": "Automate",
		"example": 'Example: rename all children starting from 0 as "child_%d"',
		"show_settings": false,
	},
}

const STYLE_FALLBACK := [
	{"value": "none", "label": "No Style Target"},
	{"value": "core_keeper", "label": "Core Keeper-like"},
	{"value": "terraria", "label": "Terraria-like"},
	{"value": "minecraft", "label": "Minecraft-like"},
	{"value": "stardew", "label": "Stardew Valley-like"},
]
const PROVIDER_FALLBACK := [
	{"value": "pixellab", "label": "PixelLab"},
	{"value": "gpt_image", "label": "GPT Image"},
]

var _summary_label: Label
var _example_label: Label
var _settings_box: VBoxContainer
var _style_select: OptionButton
var _provider_select: OptionButton
var _prompt_input: TextEdit

var _style_options: Array = STYLE_FALLBACK.duplicate(true)
var _provider_options: Array = PROVIDER_FALLBACK.duplicate(true)
var _kind := ""
var _context := {}


func _ready():
	title = "Vibe"
	min_size = Vector2(560, 320)
	confirmed.connect(_on_confirmed)

	var root := VBoxContainer.new()
	root.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	root.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.custom_minimum_size = Vector2(520, 260)
	add_child(root)

	_summary_label = _add_wrapped_label(root)
	_example_label = _add_wrapped_label(root)

	_settings_box = VBoxContainer.new()
	_settings_box.visible = false
	root.add_child(_settings_box)
	_style_select = _add_select(_settings_box, "Style Target", _style_options)
	_provider_select = _add_select(_settings_box, "Provider", _provider_options)

	_prompt_input = TextEdit.new()
	_prompt_input.custom_minimum_size = Vector2(520, 180)
	_prompt_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_prompt_input.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(_prompt_input)


func open(kind: String, summary: String, context: Dictionary):
	var meta: Dictionary = ACTIONS[kind]
	_kind = kind
	_context = context

	title = "Vibe: " + String(meta["title"])
	get_ok_button().text = String(meta["title"])
	_summary_label.text = summary
	_example_label.text = String(meta["example"])

	var show_settings: bool = meta["show_settings"]
	_settings_box.visible = show_settings
	if show_settings:
		if _style_select.item_count > 0:
			_style_select.select(0)
		if _provider_select.item_count > 0:
			_provider_select.select(0)

	_prompt_input.clear()
	popup_centered(Vector2i(560, 470) if show_settings else Vector2i(560, 320))
	_prompt_input.grab_focus()


func set_options(styles, providers):
	_style_options = _with_none(_normalize_options(styles, _style_options))
	_provider_options = _normalize_options(providers, _provider_options)
	_populate_options(_style_select, _style_options)
	_populate_options(_provider_select, _provider_options)


func _on_confirmed():
	var prompt := _prompt_input.text.strip_edges()
	if prompt.is_empty():
		print("Vibe: prompt cannot be empty")
		return
	var context := _context.duplicate()
	if ACTIONS[_kind]["show_settings"]:
		context["style"] = _selected_value(_style_select, "none")
		context["provider"] = _selected_value(_provider_select, "pixellab")
	submitted.emit(_kind, prompt, context)


func _add_wrapped_label(parent: Control) -> Label:
	var label := Label.new()
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	parent.add_child(label)
	return label


func _add_select(parent: Control, caption: String, options: Array) -> OptionButton:
	var label := Label.new()
	label.text = caption
	parent.add_child(label)
	var button := OptionButton.new()
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_populate_options(button, options)
	parent.add_child(button)
	return button


func _populate_options(button: OptionButton, options: Array):
	button.clear()
	for option in options:
		button.add_item(String(option.get("label", option.get("value", ""))))
		button.set_item_metadata(button.item_count - 1, String(option.get("value", "")))
	if button.item_count > 0:
		button.select(0)


func _selected_value(button: OptionButton, fallback: String) -> String:
	var index := button.get_selected()
	return String(button.get_item_metadata(index)) if index >= 0 else fallback


func _normalize_options(raw, fallback: Array) -> Array:
	if typeof(raw) != TYPE_ARRAY:
		return fallback
	var out: Array = []
	for entry in raw:
		if entry is String and not entry.is_empty():
			out.append({"value": entry, "label": entry})
		elif entry is Dictionary:
			var value := String(entry.get("value", ""))
			if not value.is_empty():
				out.append({"value": value, "label": String(entry.get("label", value))})
	return out if not out.is_empty() else fallback

func _with_none(styles: Array) -> Array:
	for option in styles:
		if String(option.get("value", "")) == "none":
			return styles
	var out: Array = [{"value": "none", "label": "No Style Target"}]
	out.append_array(styles)
	return out
