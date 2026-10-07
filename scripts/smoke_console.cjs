// Optional browser verification using a separately supplied Playwright runtime.
// Reads only the specified ignored local config; never prints its credential.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const {chromium} = require("playwright");
const [baseURL, configFile, evidenceDir] = process.argv.slice(2);
if (!baseURL || !configFile || !evidenceDir) throw new Error("URL, config and new evidence dir required");
fs.mkdirSync(evidenceDir, {recursive:false});
const config = JSON.parse(fs.readFileSync(configFile, "utf8").replace(/^\uFEFF/, ""));
const report = {status:"failed", data_origin:"SYNTHETIC", model_mode:"scripted_double", checks:{}, page_errors:[]};
const output = path.join(evidenceDir, "report.json");
function save() { fs.writeFileSync(output, JSON.stringify(report, null, 2)); }
async function main() {
  const browser = await chromium.launch({
    headless:true, ...(process.env.ANLAN_BROWSER_CHANNEL ? {channel:process.env.ANLAN_BROWSER_CHANNEL} : {}),
  });
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1100}});
    const page = await context.newPage();
    page.on("pageerror", () => report.page_errors.push("browser_script_error"));
    async function idle() { await page.locator("#submit-material:not(:disabled)").waitFor(); }
    async function connect() {
      await page.locator("#config-file").setInputFiles(configFile);
      await page.getByText("已连接", {exact:true}).waitFor(); await idle();
    }
    async function click(id) { await page.locator("#"+id).click(); await idle(); }
    await page.goto(baseURL + "/console"); await connect();
    await click("sample"); await click("submit-material");
    assert.equal(await page.locator("#issues .issue").count(), 2);
    assert.match(await page.locator("#task-status").textContent(), /待补充/);
    await page.locator("#work_location_description").fill("SYNTHETIC：area-p5-demo 台架 A");
    await click("submit-material");
    assert.equal(await page.locator("#issues .issue").count(), 1);
    await page.locator("#work_method_description").fill("SYNTHETIC：worker-p5-001 电弧焊接试件");
    await click("submit-material");
    assert.match(await page.locator("#revision").textContent(), /v3/);
    assert.equal(await page.locator("#issues .issue").count(), 0);
    report.checks.material_questions_supplements = true;
    report.task_id = await page.locator("#task-id").textContent();
    for (const [id, decision] of [["helmet-event","needs_verification"],["gas-event","disputed_event"]]) {
      await click(id); await click("run-review");
      assert.match(await page.locator("#review-result").textContent(), /核查完成/);
      assert.match(await page.locator("#review-result").textContent(), /当前有效/);
      assert.equal(await page.locator("#review-result .evidence").count(), 3);
      await page.locator("#feedback-decision").selectOption(decision);
      await click("send-feedback");
      assert.match(await page.locator("#feedback-status").textContent(), /已保存/);
    }
    assert.equal(await page.locator("#event-list .event-item").count(), 2);
    report.checks.two_events_review_feedback = true;
    await page.route("**/console/api/events/*/reviews", route => route.fulfill({
      status:503,contentType:"application/json",body:JSON.stringify({error:"synthetic_read_failure"}),
    }));
    await page.locator("#event-list .event-item").filter({hasText:"未戴安全帽"}).click();
    await page.locator("#error:not([hidden])").waitFor();
    assert.equal(await page.locator("#review-json").textContent(),"暂无核查");
    assert.equal(await page.locator("#send-feedback").isDisabled(),true);
    assert.equal(await page.locator("#run-review").isDisabled(),true);
    await page.unroute("**/console/api/events/*/reviews");
    await page.locator("#event-list .event-item").filter({hasText:"气体浓度异常"}).click(); await idle();
    report.checks.failed_selection_clears_dependent_state = true;
    const taskReadPath = "**/tasks/" + report.task_id;
    await page.route(taskReadPath, route => route.fulfill({
      status:409,contentType:"application/json",body:JSON.stringify({error:"synthetic_pending_snapshot"}),
    }));
    await page.locator("#task-list .task-item").first().click();
    await page.locator("#recover-task:not(:disabled)").waitFor();
    assert.equal(await page.locator("#event-list .event-item").count(),0);
    assert.equal(await page.locator("#task-id").textContent(),report.task_id);
    await page.unroute(taskReadPath);
    await click("recover-task");
    assert.match(await page.locator("#revision").textContent(),/v3/);
    await page.locator("#event-list .event-item").filter({hasText:"气体浓度异常"}).click(); await idle();
    report.checks.selected_id_recovery_without_snapshot = true;
    await page.screenshot({path:path.join(evidenceDir,"console-desktop.png"),fullPage:true});
    await page.screenshot({path:path.join(evidenceDir,"console-viewport.png"),fullPage:false});
    const oldReview = JSON.parse(await page.locator("#review-json").textContent());
    const externallyRevised = await context.request.post(baseURL + "/tasks/" + report.task_id + "/revise", {
      headers:{Authorization:"Bearer " + config.tokens[0].token},
      data:{request_id:"browser-external-revision-" + Date.now(),expected_revision:3,
        fields:{work_location_description:"SYNTHETIC：area-p5-demo 台架 B（条件变化）"}},
    });
    assert.equal(externallyRevised.status(),200);
    await click("recover-task");
    assert.match(await page.locator("#revision").textContent(), /v4/);
    assert.match(await page.locator("#review-result").textContent(), /材料已变化/);
    assert.equal(await page.locator("#send-feedback").isDisabled(), true);
    const refused = await context.request.post(baseURL + "/reviews/" + oldReview.review_id + "/feedback", {
      headers:{Authorization:"Bearer " + config.tokens[0].token},
      data:{request_id:"browser-stale-" + Date.now(),expected_revision:oldReview.revision,decision:"confirmed_event"},
    });
    assert.equal(refused.status(),409); report.checks.stale_feedback_rejected = true;
    report.checks.recovery_revalidates_old_review = true;
    await page.reload(); assert.equal(await page.locator("#connect-panel").isVisible(),true); await connect();
    assert.equal(await page.locator("#task-id").textContent(),report.task_id);
    assert.match(await page.locator("#revision").textContent(),/v4/);
    assert.equal(await page.locator("#event-list .event-item").count(),2);
    await page.locator("#event-list .event-item").filter({hasText:"气体浓度异常"}).click(); await idle();
    assert.match(await page.locator("#feedback-status").textContent(),/已保存/);
    report.checks.reload_from_pg = true;
    // Text-like malicious material must remain text; never become executable HTML.
    await page.locator("#work_object_description").fill('<img src=x onerror="window.injected=true">');
    await click("submit-material");
    assert.equal(await page.evaluate(() => window.injected),undefined);
    assert.equal(await page.locator("#task-list img").count(),0);
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length),0);
    assert.equal(new URL(page.url()).search,"");
    report.checks.safe_text_and_memory_only_token = true;
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(evidenceDir,"console-mobile.png"),fullPage:true});
    report.mobile_widths = await page.evaluate(() => ({
      viewport:innerWidth, page:document.documentElement.scrollWidth,
    }));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    report.checks.mobile_no_horizontal_overflow = true;
    assert.equal(report.page_errors.length,0);
    report.status="passed";
  } finally { save(); await browser.close(); }
}
main().catch(() => { report.failure="browser_acceptance_failed"; save(); process.exitCode=1; });
