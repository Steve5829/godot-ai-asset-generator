import automate.planner as planner

rule = planner.plan_actions("hide it", [{"scene_path": "Enemy"}], "rule")
assert rule == [{"action": "set_visible", "params": {"target_node_path": "Enemy", "args": [False]}}], rule

planner.chat = lambda messages, temperature=0.1, response_format=None: (
    '{"actions":[{"action":"set_position","params":{"target_node_path":"Enemy","args":[10,20]}},'
    '{"action":"delete_everything","params":{}}]}'
)
llm = planner.plan_actions("move enemy right", [{"scene_path": "Enemy"}], "llm")
assert len(llm) == 1 and llm[0]["action"] == "set_position", llm

assert "script" not in planner.AUTOMATE_STRATEGIES

print("ok automate rule:", rule)
print("ok automate llm (object parsed, invalid dropped):", llm)
