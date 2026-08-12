@tool
extends Node

signal succeeded(payload: Dictionary)
signal failed(message: String)
signal options_loaded(styles, providers)

const SETTING_URL := "vibe_agent/server_url"
const DEFAULT_URL := "http://127.0.0.1:8000/vibe"

var _base_url := DEFAULT_URL
var _http: HTTPRequest
var _options_http: HTTPRequest


func _ready():
	_base_url = _resolve_base_url()
	_http = HTTPRequest.new()
	_http.timeout = 180.0
	add_child(_http)
	_http.request_completed.connect(_on_completed)

	_options_http = HTTPRequest.new()
	_options_http.timeout = 15.0
	add_child(_options_http)
	_options_http.request_completed.connect(_on_options_completed)


func _resolve_base_url() -> String:
	if not ProjectSettings.has_setting(SETTING_URL):
		ProjectSettings.set_setting(SETTING_URL, DEFAULT_URL)
		ProjectSettings.set_initial_value(SETTING_URL, DEFAULT_URL)
		ProjectSettings.add_property_info({"name": SETTING_URL, "type": TYPE_STRING})
		ProjectSettings.save()
	var value := String(ProjectSettings.get_setting(SETTING_URL, DEFAULT_URL)).strip_edges()
	return value if not value.is_empty() else DEFAULT_URL


func send(endpoint: String, payload: Dictionary):
	if _http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		failed.emit("a request is already in flight")
		return
	var error := _http.request(
		_base_url + "/" + endpoint,
		PackedStringArray(["Content-Type: application/json"]),
		HTTPClient.METHOD_POST,
		JSON.stringify(payload)
	)
	if error != OK:
		failed.emit("could not send request (%d)" % error)


func fetch_options():
	if _options_http.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED:
		_options_http.request(_base_url + "/options")


func _on_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray):
	if result != HTTPRequest.RESULT_SUCCESS:
		failed.emit("HTTP request failed (%d)" % result)
		return
	var payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(payload) != TYPE_DICTIONARY:
		failed.emit("could not parse backend response")
		return
	if String(payload.get("status", "")) != "success":
		failed.emit(String(payload.get("message", "backend error %d" % response_code)))
		return
	succeeded.emit(payload)


func _on_options_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray):
	if result != HTTPRequest.RESULT_SUCCESS or response_code >= 400:
		return
	var payload = JSON.parse_string(body.get_string_from_utf8())
	if typeof(payload) == TYPE_DICTIONARY:
		options_loaded.emit(payload.get("styles"), payload.get("providers"))
