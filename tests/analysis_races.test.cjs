"use strict";
// Deterministic delayed-fetch DOM tests: every response is released by the test, never by a timer.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../static/analysis.js"),"utf8");
class Element {
  constructor(tag="div"){this.tag=tag;this.children=[];this.options=[];this.hidden=false;this.textContent="";this.listeners={};this.disabled=false;this.value="";this.checked=false;this.href="";}
  append(...items){this.children.push(...items);if(this.tag==="select")this.options.push(...items);}
  replaceChildren(...items){this.children=items;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  scrollIntoView(){this.scrolled=(this.scrolled||0)+1;}
  click(){return this.listeners.click();}
}
const texts=el=>[el.textContent,...el.children.flatMap(texts)].join(" ");
const findButtons=(el,text)=>[...(el.tag==="button"&&el.textContent===text?[el]:[]),...el.children.flatMap(child=>findButtons(child,text))];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const job=(id,status,extra={})=>({job_id:id,status,question:"overview",run_id:status==="DRAFT"?null:"run-"+id,mode:"offline",profile:"repository-analysis-offline-v1",snapshot_sha256:"snap",...extra});
const sdkJob=(id,status="DRAFT")=>job(id,status,{mode:"sdk",profile:"repository-analysis-sdk-v1"});
const state=jobs=>({csrf:"synthetic",repositories:[{id:"tiny-shop",label:"Sample",files:["README.md","inventory.py"]}],questions:{overview:"Overview",review:"Review"},jobs});
function load() {
  const map=new Map(),calls=[];
  const document={
    getElementById(id){
      if(!map.has(id)){
        const el=new Element(["repository","question","mode"].includes(id)?"select":"div");
        if(id==="mode")for(const value of ["offline","sdk"]){const option=new Element("option");option.value=value;el.append(option);}
        if(id==="error")el.hidden=true;
        map.set(id,el);
      }
      return map.get(id);
    },
    createElement(tag){return new Element(tag);}
  };
  const fetch=(url,options={})=>new Promise((resolve,reject)=>calls.push({
    path:url,method:options.method||"GET",body:options.body?JSON.parse(options.body):undefined,
    respond(data,status=200){resolve({ok:status>=200&&status<300,json:async()=>data});},
    fail(message="network down"){reject(new TypeError(message));}
  }));
  const context=vm.createContext({document,console,fetch,setTimeout(){return 1;},clearTimeout(){}});
  vm.runInContext(source,context);
  const posts=()=>calls.filter(call=>call.method==="POST");
  return {calls,posts,context,byId:id=>document.getElementById(id)};
}
async function boot(jobs=[]) {
  const page=load();
  page.calls[0].respond(state(jobs));await flush();
  return page;
}
const report=(run,extra)=>({run_id:run,mode:"mock-sdk",model_requests:1,real_model_requests:0,markdown:"md-"+run,...extra});
const findingsReport=run=>report(run,{report:{report_version:2,repository:"tiny-shop",findings:[{id:"F1",problem:"<img src=x onerror=bad()>",impact:"impact text",suggested_fix:"fix text",file:"inventory.py",line:5,sha256:"x"}]}});
const factsReport=run=>report(run,{report:{repository:"tiny-shop",claims:[{id:"project",value:"Tiny Shop",file:"README.md",line:1,sha256:"x"}]}});
const emptyReport=run=>report(run,{report:{report_version:2,repository:"tiny-shop",findings:[]}});
const previewData=text=>({live_enabled:true,model:"m",recipient:"r",limits:{max_turns:1,max_budget_usd:"0.02",timeout_seconds:30},query_text:text,snapshot_sha256:"snap"});
let count=0;
async function step(name,fn){await fn();count++;console.log("PASS",name);}

async function main() {
  await step("out-of-order refresh results are ignored",async()=>{
    const page=await boot([]);
    page.byId("refresh").click();page.byId("refresh").click();
    const [older,newer]=page.calls.slice(1);
    newer.respond(state([job("new","RUNNING")]));await flush();
    older.respond(state([job("old","DRAFT")]));await flush();
    assert.match(texts(page.byId("jobs")),/RUNNING/);
    assert.doesNotMatch(texts(page.byId("jobs")),/DRAFT/);
  });
  await step("stale refresh errors are silent, the newest error is shown",async()=>{
    const page=await boot([]);
    page.byId("refresh").click();page.byId("refresh").click();
    const [older,newer]=page.calls.slice(1);
    newer.respond(state([job("new","COMPLETED")]));await flush();
    older.fail("old failure");await flush();
    assert.equal(page.byId("error").hidden,true);
    page.byId("refresh").click();
    page.calls[3].fail("current failure");await flush();
    assert.equal(page.byId("error").textContent,"current failure");
    assert.match(texts(page.byId("jobs")),/COMPLETED/);
  });
  await step("repeated prepare clicks send one request while pending",async()=>{
    const page=await boot([]);
    const first=page.byId("prepare").click(),second=page.byId("prepare").click();
    assert.equal(page.posts().length,1);
    assert.equal(page.byId("prepare").disabled,true);
    page.posts()[0].respond(job("new","DRAFT"));await flush();
    page.calls[2].respond(state([job("new","DRAFT")]));await Promise.all([first,second]);
    assert.equal(page.posts().length,1);
    assert.equal(page.byId("prepare").disabled,false);
  });
  await step("repeated start clicks send one request while pending",async()=>{
    const page=await boot([job("j","DRAFT")]);
    const [start]=findButtons(page.byId("jobs"),"Start offline analysis");
    const first=start.click(),second=start.click();
    assert.equal(page.posts().length,1);
    page.posts()[0].respond({});await flush();
    page.calls[2].respond(state([job("j","RUNNING")]));await Promise.all([first,second]);
    assert.equal(page.posts().length,1);
  });
  await step("a failed mutation inspects state and is never replayed",async()=>{
    for(const how of ["http","network"]){
      const page=await boot([job("j","DRAFT")]);
      const [start]=findButtons(page.byId("jobs"),"Start offline analysis");
      const done=start.click();
      if(how==="http")page.posts()[0].respond({error:"Analysis operation rejected; refresh state"},409);else page.posts()[0].fail();
      await flush();
      const inspect=page.calls[2];
      assert.equal(inspect.method,"GET");
      inspect.respond(state([job("j","RUNNING")]));await done;
      assert.equal(page.posts().length,1);
      assert.match(page.byId("status").textContent,/nothing was retried/);
      assert.equal(page.byId("error").hidden,false);
      assert.match(texts(page.byId("jobs")),/RUNNING/);
    }
  });
  await step("refresh started before a mutation cannot overwrite its result",async()=>{
    const page=await boot([job("j","DRAFT")]);
    page.byId("refresh").click();
    const stale=page.calls[1];
    const [start]=findButtons(page.byId("jobs"),"Start offline analysis");
    const done=start.click();
    page.posts()[0].respond({});await flush();
    page.calls[3].respond(state([job("j","RUNNING")]));await done;
    stale.respond(state([job("j","DRAFT")]));await flush();
    assert.match(texts(page.byId("jobs")),/RUNNING/);
    assert.doesNotMatch(texts(page.byId("jobs")),/DRAFT/);
    assert.equal(page.posts().length,1);
  });
  await step("completion wins a late stop rejection",async()=>{
    const page=await boot([job("j","RUNNING")]);
    const [stop]=findButtons(page.byId("jobs"),"Stop");
    const done=stop.click();
    page.posts()[0].respond({error:"Analysis operation rejected; refresh state"},409);await flush();
    page.calls[2].respond(state([job("j","COMPLETED")]));await done;
    assert.equal(page.byId("error").hidden,true);
    assert.match(page.byId("status").textContent,/already COMPLETED/);
    assert.match(texts(page.byId("jobs")),/Open report/);
  });
  await step("a terminal state is not replaced by a late non-terminal view",async()=>{
    const page=await boot([job("j","COMPLETED")]);
    page.context.late=state([job("j","RUNNING")]);
    vm.runInContext("apply(late)",page.context);
    assert.match(texts(page.byId("jobs")),/COMPLETED/);
    assert.match(texts(page.byId("jobs")),/Open report/);
    assert.doesNotMatch(texts(page.byId("jobs")),/RUNNING/);
  });
  await step("stop is sent once and is described as a local request",async()=>{
    const page=await boot([job("j","RUNNING")]);
    const [stop]=findButtons(page.byId("jobs"),"Stop");
    const first=stop.click(),second=stop.click();
    assert.equal(page.posts().length,1);
    page.posts()[0].respond({});await flush();
    page.calls[2].respond(state([job("j","STOPPING")]));await Promise.all([first,second]);
    assert.match(page.byId("status").textContent,/provider-side cancellation is not claimed/);
    assert.equal(page.posts().length,1);
  });
  await step("only the newest report request renders, older results and errors are ignored",async()=>{
    const page=await boot([job("a","COMPLETED"),job("b","COMPLETED")]);
    const buttons=findButtons(page.byId("jobs"),"Open report"); // newest job first: b, a
    buttons[1].click();buttons[0].click();
    const [forA,forB]=page.calls.slice(1);
    assert.match(forA.path,/\/a\/report$/);assert.match(forB.path,/\/b\/report$/);
    forB.respond(findingsReport("run-b"));await flush();
    forA.respond(factsReport("run-a"));await flush();
    assert.match(page.byId("provenance").textContent,/run-b/);
    assert.match(page.byId("provenance").textContent,/1 bounded findings/);
    assert.match(texts(page.byId("claims")),/<img src=x onerror=bad\(\)>/);
    assert.equal(page.byId("claims").children[0].children[1].tag,"p");
    assert.match(page.byId("claims").children[0].children[4].href,/files\/inventory.py#L5$/);
    assert.equal(page.byId("markdown").textContent,"md-run-b");
    buttons[1].click();buttons[0].click();
    const [lateA,currentB]=page.calls.slice(3);
    currentB.respond(factsReport("run-b2"));await flush();
    lateA.respond({error:"Analysis unavailable"},409);await flush();
    assert.equal(page.byId("error").hidden,true);
    assert.match(page.byId("provenance").textContent,/run-b2/);
    assert.match(page.byId("provenance").textContent,/1 validated source facts/);
  });
  await step("only the newest preview renders and a changed job invalidates it",async()=>{
    const page=await boot([sdkJob("a"),sdkJob("b")]);
    const buttons=findButtons(page.byId("jobs"),"Review SDK payload"); // b, a
    buttons[1].click();buttons[0].click();
    const [forA,forB]=page.calls.slice(1);
    const preview=text=>({live_enabled:true,model:"m",recipient:"r",limits:{max_turns:1,max_budget_usd:"0.02",timeout_seconds:30},query_text:text,snapshot_sha256:"snap"});
    forB.respond(preview("B-payload"));await flush();
    forA.respond(preview("A-payload"));await flush();
    const panel=page.byId("sdk-preview");
    assert.equal(panel.children[3].textContent,"B-payload");
    page.context.next=state([sdkJob("a"),sdkJob("b","RUNNING")]);
    vm.runInContext("apply(next)",page.context);
    assert.equal(panel.hidden,true);assert.equal(panel.children.length,0);
  });
  await step("preview consent is single use and bound to the preview",async()=>{
    const page=await boot([sdkJob("j")]);
    findButtons(page.byId("jobs"),"Review SDK payload")[0].click();
    page.calls[1].respond({live_enabled:true,model:"m",recipient:"r",limits:{max_turns:1,max_budget_usd:"0.02",timeout_seconds:30},query_text:"payload",snapshot_sha256:"snap"});await flush();
    const panel=page.byId("sdk-preview"),[first,second,start]=panel.children.slice(4);
    first.children[0].checked=second.children[0].checked=true;
    first.children[0].listeners.change();second.children[0].listeners.change();
    assert.equal(start.disabled,false);
    const one=start.click(),two=start.click();
    assert.equal(page.posts().length,1);
    assert.deepEqual(page.posts()[0].body,{allow_live:true,allow_existing_login:true,snapshot_sha256:"snap"});
    assert.equal(panel.hidden,true);
    page.posts()[0].respond({error:"Analysis operation rejected; refresh state"},409);await flush();
    page.calls[3].respond(state([sdkJob("j")]));await Promise.all([one,two]);
    const again=start.click();
    await flush();
    assert.equal(page.posts().length,1);
    assert.match(page.byId("error").textContent,/out of date/);
    await again;
  });
  await step("the review question forces the SDK mode",async()=>{
    const page=await boot([]);
    page.byId("question").value="review";
    page.byId("question").listeners.change();
    assert.equal(page.byId("mode").value,"sdk");
    assert.equal(page.byId("mode").options[0].disabled,true);
    page.byId("mode").value="offline";
    const done=page.byId("prepare").click();
    assert.equal(page.posts()[0].body.mode,"sdk");
    assert.equal(page.posts()[0].body.question,"review");
    assert.deepEqual(page.posts()[0].body.files,["README.md","inventory.py"]);
    page.posts()[0].respond({});await flush();
    page.calls[2].respond(state([]));await done;
  });
  // Report A (completed) is requested first, preview B (draft) second; B is the newest selection.
  const crossKind=async()=>{
    const page=await boot([job("a","COMPLETED"),sdkJob("b")]);
    findButtons(page.byId("jobs"),"Open report")[0].click();
    findButtons(page.byId("jobs"),"Review SDK payload")[0].click();
    const [forA,forB]=page.calls.slice(1);
    assert.match(forA.path,/\/a\/report$/);assert.match(forB.path,/\/b\/preview$/);
    return {page,forA,forB};
  };
  await step("a stale report response cannot steal a newer preview selection",async()=>{
    const {page,forA,forB}=await crossKind();
    forB.respond(previewData("B-payload"));await flush();
    forA.respond(factsReport("run-a"));await flush();
    assert.equal(page.byId("sdk-preview").children[3].textContent,"B-payload");
    assert.equal(page.byId("sdk-preview").hidden,false);
    assert.equal(page.byId("sdk-preview").scrolled,1);
    assert.equal(page.byId("report-panel").scrolled,undefined);
    assert.equal(page.byId("report-panel").hidden,false); // never rendered: untouched initial state
    assert.equal(page.byId("claims").children.length,0);
    assert.equal(page.byId("provenance").textContent,"");
  });
  await step("a stale report rejection is silent after a newer preview selection",async()=>{
    const {page,forA,forB}=await crossKind();
    forB.respond(previewData("B-payload"));await flush();
    forA.respond({error:"Old report error"},409);await flush();
    assert.equal(page.byId("error").hidden,true);
    assert.equal(page.byId("error").textContent,"");
    assert.equal(page.byId("sdk-preview").children[3].textContent,"B-payload");
    assert.equal(page.byId("sdk-preview").scrolled,1);
  });
  await step("a stale preview response or rejection cannot steal a newer report selection",async()=>{
    for(const how of ["response","rejection"]){
      const page=await boot([job("a","COMPLETED"),sdkJob("b")]);
      findButtons(page.byId("jobs"),"Review SDK payload")[0].click();
      findButtons(page.byId("jobs"),"Open report")[0].click();
      const [forB,forA]=page.calls.slice(1);
      forA.respond(findingsReport("run-a"));await flush();
      if(how==="response")forB.respond(previewData("B-payload"));else forB.respond({error:"Old preview error"},409);
      await flush();
      assert.equal(page.byId("error").hidden,true);
      assert.equal(page.byId("sdk-preview").hidden,true);
      assert.equal(page.byId("sdk-preview").children.length,0);
      assert.equal(page.byId("sdk-preview").scrolled,undefined);
      assert.match(page.byId("provenance").textContent,/run-a/);
      assert.equal(page.byId("report-panel").scrolled,1);
    }
  });
  await step("selecting a report invalidates a shown preview consent",async()=>{
    const page=await boot([job("a","COMPLETED"),sdkJob("b")]);
    findButtons(page.byId("jobs"),"Review SDK payload")[0].click();
    page.calls[1].respond(previewData("B-payload"));await flush();
    const panel=page.byId("sdk-preview"),[first,second,start]=panel.children.slice(4);
    first.children[0].checked=second.children[0].checked=true;
    first.children[0].listeners.change();second.children[0].listeners.change();
    findButtons(page.byId("jobs"),"Open report")[0].click();
    assert.equal(panel.hidden,true);assert.equal(panel.children.length,0);
    page.calls[2].respond(findingsReport("run-a"));await flush();
    await start.click(); // a hidden stale start action must not send anything
    assert.equal(page.posts().length,0);
    assert.match(page.byId("error").textContent,/out of date/);
  });
  await step("an unknown mutation plus a failed re-read stays locked until Refresh succeeds",async()=>{
    const page=await boot([job("j","DRAFT")]);
    const [start]=findButtons(page.byId("jobs"),"Start offline analysis");
    const done=start.click();
    page.posts()[0].fail();await flush();
    page.calls[2].fail("state unavailable");await done;
    assert.equal(page.byId("error").hidden,false);
    assert.doesNotMatch(page.byId("status").textContent,/State was re-read/);
    assert.match(page.byId("status").textContent,/locked/);
    assert.equal(page.byId("prepare").disabled,true);
    await start.click(); // the old button must not replay the start
    await page.byId("prepare").click();
    assert.equal(page.posts().length,1);
    assert.equal(page.calls.length,3); // no automatic retry or hidden read
    assert.match(page.byId("error").textContent,/unconfirmed/);
    page.byId("refresh").click();
    page.calls[3].respond(state([job("j","RUNNING")]));await flush();
    assert.equal(page.byId("error").hidden,true);
    assert.equal(page.byId("prepare").disabled,false);
    assert.equal(page.posts().length,1);
    const [stop]=findButtons(page.byId("jobs"),"Stop");
    const next=stop.click(); // an intentional new action is allowed again
    assert.equal(page.posts().length,2);
    assert.match(page.posts()[1].path,/\/stop$/);
    page.posts()[1].respond({});await flush();
    page.calls[5].respond(state([job("j","STOPPING")]));await next;
    assert.equal(page.posts().length,2);
  });
  await step("an HTTP 500 start plus a failed re-read stays locked and recovers only through Refresh",async()=>{
    const page=await boot([job("j","DRAFT")]);
    const [start]=findButtons(page.byId("jobs"),"Start offline analysis");
    const done=start.click();
    page.posts()[0].respond({error:"Server failure"},500);await flush();
    page.calls[2].fail("state unavailable");await done;
    assert.equal(page.byId("prepare").disabled,true);
    assert.match(page.byId("status").textContent,/locked/);
    await start.click(); // the server may have applied the start: no second POST
    await page.byId("prepare").click();
    assert.equal(page.posts().length,1);
    assert.equal(page.calls.length,3);
    assert.match(page.byId("error").textContent,/unconfirmed/);
    page.byId("refresh").click();
    page.calls[3].respond(state([job("j","RUNNING")]));await flush();
    assert.equal(page.byId("error").hidden,true);
    assert.equal(page.byId("prepare").disabled,false);
    assert.equal(page.posts().length,1);
    const [stop]=findButtons(page.byId("jobs"),"Stop");
    const next=stop.click();
    assert.equal(page.posts().length,2);
    page.posts()[1].respond({});await flush();
    page.calls[5].respond(state([job("j","STOPPING")]));await next;
  });
  await step("a failed Refresh keeps the lock, and an HTTP 409 with a failed re-read also locks",async()=>{
    const page=await boot([job("j","DRAFT")]);
    const [start]=findButtons(page.byId("jobs"),"Start offline analysis");
    const done=start.click();
    page.posts()[0].fail();await flush();
    page.calls[2].fail("state unavailable");await done;
    page.byId("refresh").click();
    page.calls[3].fail("still unavailable");await flush();
    assert.equal(page.byId("prepare").disabled,true);
    await start.click();
    assert.equal(page.posts().length,1);
    const other=await boot([job("j","DRAFT")]);
    const [again]=findButtons(other.byId("jobs"),"Start offline analysis");
    const rejected=again.click();
    other.posts()[0].respond({error:"Analysis operation rejected; refresh state"},409);await flush();
    other.calls[2].fail("state unavailable");await rejected;
    assert.match(other.byId("status").textContent,/locked/);
    assert.equal(other.byId("prepare").disabled,true);
    await again.click();
    assert.equal(other.posts().length,1);
  });
  await step("an empty v2 findings list renders a clean review without claiming correctness",async()=>{
    const page=await boot([sdkJob("r","COMPLETED")]);
    findButtons(page.byId("jobs"),"Open report")[0].click();
    page.calls[1].respond(emptyReport("run-r"));await flush();
    assert.match(texts(page.byId("claims")),/No findings reported/);
    assert.match(texts(page.byId("claims")),/not proof/);
    assert.match(page.byId("provenance").textContent,/No findings reported/);
    assert.doesNotMatch(page.byId("provenance").textContent,/0 bounded findings/);
  });
  console.log(`Analysis UI races: ${count} scenarios PASS`);
}
main().catch(error=>{console.error(error);process.exitCode=1;});
