"use strict";
// Execute the actual vanilla inspector with a minimal DOM, no framework dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor() { this.children=[]; this.textContent=''; this.classList={toggle(){}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  addEventListener() {}
  setAttribute() {}
  scrollIntoView() {}
}
const elements=new Map();
const document={getElementById(id) { if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id); },createElement(){return new Element();}};
const context=vm.createContext({document,fetch:async()=>({ok:true,json:async()=>({runs:[],total:0})}),window:{}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8'),context);
function render(value, run=null) {
  context.comparison=value; context.run=run;
  vm.runInContext('renderUsageComparison(comparison,run)',context);
  return document.getElementById('usage-comparison');
}
function texts(node) {return [node.textContent,...node.children.flatMap(texts)].join(' ');}
assert.match(texts(render({version:1,status:{toString:null},fields:{}})),/No usage comparison/);
assert.match(texts(render(null)),/No usage comparison/);
const data={version:1,status:'different-observed-values',fields:{output_tokens:{native:314,derived:105,native_minus_derived:209}}};
assert.match(texts(render(data)),/209/);
assert.doesNotMatch(texts(render({...data,status:'scope-unverified'})),/209/);
assert.doesNotMatch(texts(render(data,{resumes_run_id:'synthetic-old-run'})),/209/);
assert.doesNotMatch(texts(render(data,{usage:{application:{subagent_activity_observed:true}}})),/209/);
const bad={version:1,status:'partial-observed-values',fields:{output_tokens:{native:-1,derived:0,native_minus_derived:-1}}};
assert.doesNotMatch(texts(render(bad)),/-1/);
console.log('usage comparison DOM: 7 assertions PASS');
