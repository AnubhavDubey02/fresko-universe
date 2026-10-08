#!/usr/bin/env node
// Offline regression: the exact target handoff must clear sessionStorage BEFORE panel exposure.
// Runs against application JS through Node vm, no Frappe dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname,'../fresko_universe/fresko_universe/fresko_core/page/fresko_money/fresko_money.js'),'utf8');
const target = (name) => ({doctype:'Fresko Collection',document_name:name,action:'verify_collection'});
const reply = (name) => ({message:{doctype:'Fresko Collection',action:'verify_collection',allowed:false,blocked_reason:'Already approved',record:{name,company:'Company A',status:'APPROVED',version:2}}});
function harness() {
  const map = new Map(), requests = [], snapshots = [], notices = [];
  let currentCompany = 'Old Company', currentRoute = ['fresko-money'], routeChange;
  const sessionStorage = {getItem:k=>map.has(k)?map.get(k):null,setItem:(k,v)=>map.set(k,String(v)),removeItem:k=>map.delete(k)};
  const frappe = {
    pages:{'fresko-money':{}},user_roles:['Fresko Accounts'],get_route:()=>currentRoute,
    router:{on:(event,callback)=>{assert.equal(event,'change');routeChange=callback;}},
    msgprint:m=>notices.push(m),call:()=>new Promise((resolve,reject)=>requests.push({resolve,reject})),
  };
  const $ = () => ({find:()=>({remove:()=>{}})});
  const ctx=vm.createContext({frappe,$,sessionStorage,__:(v)=>v,Promise,Object,JSON,console});
  vm.runInContext(src,ctx,{filename:'fresko_money.js'});
  const ui=vm.runInContext('fresko_money',ctx);
  ui.page={main:{}};
  ui.read_context=()=>[1,currentCompany];
  ui.context_is_current=(c)=>JSON.stringify(c)===JSON.stringify([1,currentCompany]);
  ui.get_company=()=>currentCompany;
  ui.company_field={set_value(v){currentCompany=v;return Promise.resolve()}};
  ui.show_action_target=()=>snapshots.push(sessionStorage.getItem('fresko_money_target'));
  return {ui,frappe,sessionStorage,requests,snapshots,notices,visit(route){currentRoute=[route];return routeChange();}};
}
async function run() {
  const h=harness();
  for(const name of ['COL-1','COL-2']) {
    h.sessionStorage.setItem('fresko_money_target',JSON.stringify(target(name)));
    const task=h.ui.consume_action_target();
    assert.equal(h.requests.length, name==='COL-1'?1:2);
    h.requests.at(-1).resolve(reply(name));
    await task;
    assert.equal(h.sessionStorage.getItem('fresko_money_target'),null,'target cleared after success');
  }
  assert.deepEqual(h.snapshots,[null,null], 'target was visible before storage cleanup');
  const routed=harness();
  routed.sessionStorage.setItem('fresko_money_target',JSON.stringify(target('COL-ROUTE')));
  routed.visit('fresko-workspace');
  assert.equal(routed.requests.length,0,'other routes do not consume a Money target');
  const routeTask=routed.visit('fresko-money');
  assert.equal(routed.requests.length,1,'cached Money Page route change consumes the pending target');
  routed.requests[0].resolve(reply('COL-ROUTE'));
  await routeTask;
  assert.deepEqual(routed.snapshots,[null]);
  const denied=harness();denied.frappe.user_roles=['Fresko Accounts','Supplier Viewer'];
  denied.sessionStorage.setItem('fresko_money_target',JSON.stringify(target('DENY')));
  await denied.ui.consume_action_target();
  assert.equal(denied.requests.length,0);
  assert.equal(denied.sessionStorage.getItem('fresko_money_target'),null);
  console.log('PASS: atomic Money target cleanup before rendering, twice; mixed-role denial preserved');
}
run().catch(e=>{console.error(e.stack||String(e));process.exitCode=1});
