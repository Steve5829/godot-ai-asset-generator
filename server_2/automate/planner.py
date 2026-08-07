import json
from llm import chat

ACTION_CATALOG = {
    "set_position": {"params": {"target_node_path": "str", "args": "[x, y]"}, "desc": "move a node in pixels"},
    "set_modulate": {"params": {"target_node_path": "str", "args": "[r, g, b, a] each 0..1"}, "desc": "tint a node"},
    "set_scale": {"params": {"target_node_path": "str", "args": "[x, y]"}, "desc": "scale a node"},
    "set_visible": {"params": {"target_node_path": "str", "args": "[true or false]"}, "desc": "show or hide a node"},
    "rename_children": {"params": {"target_node_path": "str", "pattern": "str with %d", "start_index": "int"}, "desc": "batch-rename a node's children"},
    "create_node": {"params": {"target_node_path": "str", "node_type": "str", "count": "int", "name_pattern": "str with %d"}, "desc": "create child nodes"},
}


def _catalog_text():
    return "\n".join(
        "- %s: %s; params %s" % (name, spec["desc"], spec["params"])
        for name, spec in ACTION_CATALOG.items()
    )


def _valid(action):
    return (
        isinstance(action, dict)
        and action.get("action") in ACTION_CATALOG
        and isinstance(action.get("params"), dict)
    )


def _first_target(nodes):
    if nodes and isinstance(nodes[0], dict):
        return str(nodes[0].get("scene_path", "."))
    return "."


def plan_rule(prompt, nodes):
    text = prompt.lower()
    target = _first_target(nodes)
    actions = []
    if "rename" in text:
        actions.append({"action": "rename_children", "params": {"target_node_path": target, "pattern": "child_%d", "start_index": 0}})
    if "hide" in text:
        actions.append({"action": "set_visible", "params": {"target_node_path": target, "args": [False]}})
    if "show" in text:
        actions.append({"action": "set_visible", "params": {"target_node_path": target, "args": [True]}})
    return [a for a in actions if _valid(a)]


def plan_llm(prompt, nodes):
    messages = [
        {"role": "system", "content":
            "You convert an editor instruction into JSON.\n"
            "Use ONLY these actions:\n" + _catalog_text() + "\n"
            'Return a JSON object shaped {"actions": [{"action": <name>, "params": {...}}]}.'},
        {"role": "user", "content":
            "Instruction: %s\nSelected nodes (use scene_path as target_node_path): %s" % (prompt, nodes)},
    ]
    raw = chat(messages, response_format={"type": "json_object"})
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return []
    return [a for a in actions if _valid(a)]


AUTOMATE_STRATEGIES = {
    "rule": plan_rule,
    "llm": plan_llm,
}


def plan_actions(prompt, nodes, mode="llm"):
    planner = AUTOMATE_STRATEGIES.get(mode, plan_llm)
    return planner(prompt, nodes)
