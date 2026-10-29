# ruff: noqa: E501, I001
"""Execute the real console module against a small DOM harness for P13 cards."""

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_preflight_card_dom_preserves_drafts_and_freezes_seen_versions(tmp_path):
    harness = tmp_path / "preflight-console.mjs"
    harness.write_text(
        r'''
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
class Element {
  constructor(tag, text="") { this.tag = tag; this.textContent = text; this.children = []; this.listeners = {}; this.value = ""; this.checked = false; this.hidden = false; this.className = ""; this.dataset = {}; }
  append(...values) { for (const value of values) this.children.push(typeof value === "string" ? new Element("text", value) : value); }
  replaceChildren(...values) { this.children = []; this.append(...values); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  setAttribute() {}
  querySelectorAll(selector) { const values = []; const visit = value => { if (value?.children) for (const child of value.children) { if (selector === "input:checked" && child.tag === "input" && child.checked) values.push(child); visit(child); } }; visit(this); return values; }
}
const elements = new Map();
const get = id => { if (!elements.has(id)) elements.set(id, new Element("div")); return elements.get(id); };
const context = {AbortController, clearTimeout(){}, setTimeout(){ return 0; }, queueMicrotask(fn){ fn(); }, crypto:{getRandomValues(v){ return v; }}, document:{getElementById:get, querySelectorAll(){ return []; }, createElement:t => new Element(t), createTextNode:t => new Element("text", t)}, request:async () => ({workers:[], areas:[]}), mutate:async (_path, body) => { context.sent = body; return context.nextSnapshot; }, subscribeSnapshot(){}, ApiError:class extends Error {}};
vm.createContext(context);
const source = fs.readFileSync(process.argv[2], "utf8").replace(/^import .*\n/, "");
vm.runInContext(source + `
globalThis.subject = {state, renderPreflight, renderBinding, renderCitations, resetIdentityState};
renderSnapshot = () => {};
`, context);
const {state, renderPreflight, resetIdentityState} = context.subject;
state.info = {collaboration_role:"applicant"};
state.snapshot = {conversation_id:"conv", revision:7, task_projection:{task_id:"task-a"}};
state.preflightCatalogs.set("task-a", {workers:[{worker_id:"worker-a",label:"人员甲",qualification_types:[{qualification_type:"welding",label:"焊接"}]}],areas:[{area_id:"area-a",label:"区域甲"}]});
const task = {task_id:"task-a", revision:4};
const shared = {application:{version:9,status:"draft"}, allowed_actions:["edit_materials"], precheck:{binding_revision:null,status:"unbound",clock_mode:"fixed_replay",as_of:"2026-10-28T00:00:00Z"}};
renderPreflight(task, shared);
let selects = get("task-projection").children.flatMap(card => card.children).filter(value => value.tag === "form").flatMap(form => form.children).filter(value => value.tag === "select");
assert.equal(selects[0].children[0].value, "", "worker selection must start empty");
assert.equal(selects[2].children[0].value, "", "area selection must start empty");
state.info = {collaboration_role:"safety_manager"};
const ready = {application:{version:9,status:"under_review"}, allowed_actions:["complete_review"], precheck:{binding_revision:2,check_id:"check-a",current:true,status:"ready",clock_mode:"fixed_replay",as_of:"2026-10-28T00:00:00Z",binding:{references:{worker_id:"worker-a",qualification_type:"welding",area_id:"area-a"},labels:{worker:"人员甲",qualification:"焊接",area:"区域甲"}},evidence:{citation_ids:["citation-a"],worker:{outcome:"ok",source:{version:"facts-v1"}},area:{outcome:"ok",source:{version:"areas-v1"}},knowledge:{citations:[{chunk_id:"citation-a",quote:"合成规程摘录",source:"synthetic/policy",version:3}]}}}};
renderPreflight(task, ready);
const text = JSON.stringify(get("task-projection"));
assert.match(text, /人员甲/); assert.match(text, /合成规程摘录/); assert.match(text, /synthetic\/policy/);
assert.match(text, /有效至/); assert.match(text, /业务状态/);
const key = "task-a:4:2:check-a";
state.preflightDrafts.set(key, {citation:{citations:["citation-a"],conclusion:"人工结论"}});
get("task-projection").replaceChildren(); renderPreflight(task, ready);
let forms = get("task-projection").children.flatMap(card => card.children).filter(value => value.tag === "form");
let citationForm = forms.at(-1), checked = citationForm.querySelectorAll("input:checked");
assert.equal(checked.length, 1); assert.equal(citationForm.children.find(value => value.tag === "textarea").value, "人工结论");
context.nextSnapshot = state.snapshot;
await citationForm.listeners.submit({preventDefault(){}});
assert.equal(JSON.stringify(context.sent), JSON.stringify({expected_revision:7, expected_check_id:"check-a", expected_material_revision:4, expected_binding_revision:2, expected_application_version:9, conclusion:"人工结论", applied_knowledge_citation_ids:["citation-a"]}));
const changed = structuredClone(ready); changed.precheck.check_id = "check-b";
get("task-projection").replaceChildren(); renderPreflight(task, changed);
forms = get("task-projection").children.flatMap(card => card.children).filter(value => value.tag === "form"); citationForm = forms.at(-1);
assert.equal(citationForm.querySelectorAll("input:checked").length, 0, "new check clears citation draft");
assert.equal(citationForm.children.find(value => value.tag === "textarea").value, "", "new check clears conclusion draft");
get("task-projection").replaceChildren(); renderPreflight(task, {application:{version:1,status:"review_completed"}, allowed_actions:[], precheck:{legacy_completed:true}});
assert.match(JSON.stringify(get("task-projection")), /未执行本版作业前预核查/);
resetIdentityState(); assert.equal(state.preflightDrafts.size, 0); assert.equal(state.preflightCatalogs.size, 0);
console.log("preflight console DOM behavior passed");
''',
        encoding="utf-8",
    )
    result = subprocess.run(
        [shutil.which("node") or "node", str(harness), str(ROOT / "src/anlan/interfaces/console/assets/app.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
