"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
class Element {
  constructor(tag="div"){this.tag=tag;this.children=[];this.options=[];this.hidden=false;this.textContent="";this.listeners={};}
  append(...items){this.children.push(...items);if(this.tag==="select")this.options.push(...items);}
  replaceChildren(...items){this.children=items;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  scrollIntoView(){}
}
const map=new Map();
const document={getElementById(id){if(!map.has(id))map.set(id,new Element(["repository","question"].includes(id)?"select":"div"));return map.get(id);},createElement(tag){return new Element(tag);}};
const context=vm.createContext({document,console,clearTimeout(){},setTimeout(){return 1;},fetch:async()=>({ok:true,json:async()=>({csrf:"synthetic",repositories:[{id:"tiny-shop",label:"Sample",files:["README.md"]}],questions:{overview:"Overview"},jobs:[]})})});
vm.runInContext(fs.readFileSync(path.join(__dirname,"../static/analysis.js"),"utf8"),context);
const texts=el=>[el.textContent,...el.children.flatMap(texts)].join(" ");
context.payload={run_id:"synthetic-run",model_requests:0,markdown:"<script>bad</script>",report:{claims:[{id:"function:x",value:'<img src=x onerror="bad()">',file:"inventory.py",line:5}]}};
vm.runInContext('renderReport("synthetic-job",payload)',context);
assert.match(texts(map.get("claims")),/<img src=x onerror=/);
assert.equal(map.get("claims").children[0].children[1].tag,"p");
assert.match(map.get("claims").children[0].children[2].href,/files\/inventory.py#L5$/);
assert.equal(map.get("markdown").textContent,"<script>bad</script>");
assert.equal(map.get("download").href,"/api/analysis/jobs/synthetic-job/download");
context.jobs=[{job_id:"draft",status:"DRAFT",question:"overview"},{job_id:"done",status:"COMPLETED",question:"overview",run_id:"run"},{job_id:"stop",status:"CANCELLED",question:"overview",run_id:"stoprun"}];
vm.runInContext("renderJobs(jobs)",context);
assert.match(texts(map.get("jobs")),/Start offline analysis/);
assert.match(texts(map.get("jobs")),/Open report/);
assert.match(texts(map.get("jobs")),/will not replay/);
console.log("Analysis UI DOM: 8 assertions PASS");

context.jobs=[{job_id:"sdk-draft",status:"DRAFT",question:"overview",mode:"sdk"}];
vm.runInContext("renderJobs(jobs)",context);
assert.match(texts(map.get("jobs")),/Review SDK payload/);
assert.doesNotMatch(texts(map.get("jobs")),/Start offline analysis/);
context.fetch=async()=>({ok:true,json:async()=>({live_enabled:false,model:"claude-haiku-5-5",recipient:"synthetic",limits:{max_turns:1,max_budget_usd:"0.02",timeout_seconds:30},query_text:"<script>preview</script>",snapshot_sha256:"synthetic"})});
vm.runInContext('showPreview("sdk-draft")',context).then(()=>{
 const panel=map.get("sdk-preview");assert.match(texts(panel),/Live gate closed/);
 assert.equal(panel.children[3].tag,"pre");assert.equal(panel.children[3].textContent,"<script>preview</script>");
 const first=panel.children[4].children[0], second=panel.children[5].children[0], start=panel.children[6];
 assert.equal(first.checked,false);assert.equal(second.checked,false);assert.equal(start.disabled,true);
 first.checked=second.checked=true;first.listeners.change();assert.equal(start.disabled,true);
 console.log("SDK preview DOM: closed gate, fresh consent and literal payload PASS");
}).catch(error=>{console.error(error);process.exitCode=1;});
