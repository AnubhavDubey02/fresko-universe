#!/usr/bin/env node
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../fresko_universe/fresko_universe/fresko_core/page/fresko_money/fresko_money.js'), 'utf8');
const dialogs = [];
const frappe = {
  pages: { 'fresko-money': {} },
  user_roles: ['Fresko Accounts'],
  session: { user: 'accounts@example.test' },
  ui: { Dialog: function(options) { this.options = options; this.show = () => {}; this.hide = () => {}; dialogs.push(this); } },
  defaults: { get_user_default: () => 'Fresko Test Co' },
  datetime: { now_datetime: () => '2026-10-03 10:00:00' }
};
const context = vm.createContext({ frappe, crypto: { randomUUID: () => 'stable-event-id' }, console, __: (value) => value });
vm.runInContext(source, context, { filename: 'fresko_money.js' });
const ui = vm.runInContext('fresko_money', context);

assert.equal(ui.workflow_kind('collection'), 'collection');
assert.equal(ui.workflow_kind('allocation'), 'payment_allocation');
assert.equal(ui.workflow_kind('adjustment'), 'adjustment');
assert.equal(ui.workflow_kind('application'), 'adjustment_application');
assert.deepEqual(JSON.parse(JSON.stringify(ui.workflow_arg('collection', 'COLL-1', 7))), { collection_name: 'COLL-1', expected_version: 7 });
assert.deepEqual(JSON.parse(JSON.stringify(ui.workflow_arg('allocation', 'PAL-1', 3))), { allocation_name: 'PAL-1', expected_version: 3 });
assert.deepEqual(JSON.parse(JSON.stringify(ui.workflow_arg('adjustment', 'ADJ-1', 4))), { adjustment_name: 'ADJ-1', expected_version: 4 });
assert.deepEqual(JSON.parse(JSON.stringify(ui.workflow_arg('application', 'ADJA-1', 5))), { application_name: 'ADJA-1', expected_version: 5 });

function jqueryButton() {
  return { on(_event, handler) { this.handler = handler; return this; }, text(value) { this.label = value; return this; } };
}
context.$ = jqueryButton;
const actions = [];
ui.has_role = (role) => role === 'Fresko Accounts';
ui.call_api = (method, args) => actions.push({ method, args });
ui.refresh_all = () => {};
ui.render_workflow_buttons({ append: (button) => actions.push(button) }, 'collection', {
  name: 'COLL-1', status: 'DRAFT', prepared_by: frappe.session.user, version: 7
});
const submitButton = actions.find((button) => button.label === 'Submit');
assert.ok(submitButton, 'draft maker sees a submit action');
submitButton.handler();
assert.deepEqual(JSON.parse(JSON.stringify(actions.at(-1))), {
  method: 'fresko_universe.money.submit_collection',
  args: { collection_name: 'COLL-1', expected_version: 7 }
});

frappe.user_roles = ['Fresko Accounts', 'External Supplier Viewer'];
assert.equal(ui.is_supplier(), true, 'supplier substring blocks mixed internal roles');
let deniedText = '';
context.$ = () => ({ html: (value) => { deniedText = value; } });
ui.init({ main: {} });
assert.match(deniedText, /Access denied/);

frappe.user_roles = ['Fresko Accounts'];
ui.get_company = () => 'Fresko Test Co';
ui.call_api = (method, args, callback) => actions.push({ method, args, callback });
ui.refresh_all = () => {};
ui.show_capture_collection_dialog();
const capture = dialogs.at(-1);
const fields = Object.fromEntries(capture.options.fields.map((field) => [field.fieldname, field]));
assert.equal(fields.source_evidence.fieldtype, 'Link');
assert.equal(fields.source_evidence.options, 'Fresko Evidence');
assert.notEqual(fields.source_evidence.reqd, 1, 'cash declaration may omit a supporting slip');
assert.equal(fields.bank_account.options, 'Bank Account');
assert.equal(fields.customer.options, 'Customer');
assert.ok(fields.source_classification.options.includes('CASH_DECLARATION'));
assert.ok(fields.source_classification.options.includes('BANK_RECEIPT'));
assert.ok(fields.source_classification.options.includes('BANK_CREDIT_CONFIRMATION'));
assert.ok(fields.source_classification.options.includes('RTGS_NEFT'));

const cashValues = { direction: 'INFLOW', amount_state: 'KNOWN', amount: '12.00', payment_channel: 'CASH', source_classification: 'CASH_DECLARATION' };
capture.options.primary_action(cashValues);
capture.options.primary_action({ ...cashValues });
const cashCalls = actions.slice(-2);
assert.ok(cashCalls.every((call) => call.method === 'fresko_universe.money.create_collection'));
assert.ok(cashCalls.every((call) => call.args.source_event_id === 'stable-event-id'), 'retry reuses the dialog event id');
assert.ok(cashCalls.every((call) => call.args.company === 'Fresko Test Co'));
assert.ok(cashCalls.every((call) => !call.args.source_evidence), 'cash capture does not require bank evidence');

const bankValues = { direction: 'INFLOW', amount_state: 'KNOWN', amount: '12.00', payment_channel: 'BANK', bank_state: 'BANK_CLEARED', source_classification: 'RTGS_NEFT', source_evidence: 'EVIDENCE-1' };
capture.options.primary_action(bankValues);
const bankCall = actions.at(-1);
assert.equal(bankCall.args.source_classification, 'RTGS_NEFT');
assert.equal(bankCall.args.source_evidence, 'EVIDENCE-1');
console.log('test_money_ui.cjs passed');

// A delayed response must not replace the result of a newer filter selection.
const pending = [], notices = [], rendered = [];
const raceFrappe = { ...frappe, call: (request) => pending.push(request), msgprint: (message) => notices.push(message) };
const raceContext = vm.createContext({ frappe: raceFrappe, console, __: (value) => value });
vm.runInContext(source, raceContext);
const raceUI = vm.runInContext('fresko_money', raceContext);
let selectedContainer = 'A';
raceUI.get_company = () => 'Fresko Test Co';
raceUI.get_container = () => selectedContainer;
raceUI.get_cutoff = () => '2026-10-03 10:00:00';
raceUI.call_api('fresko_universe.money.get_container_receivable', { container: 'A' }, (result) => rendered.push(result.container));
selectedContainer = 'B';
raceUI.call_api('fresko_universe.money.get_container_receivable', { container: 'B' }, (result) => rendered.push(result.container));
assert.equal(pending.length, 2, 'a slow read must not prevent the newly selected read');
pending[1].callback({ message: { container: 'B' } });
pending[0].callback({ message: { container: 'A' } });
assert.deepEqual(rendered, ['B'], 'the obsolete response cannot overwrite current data');
assert.equal(pending[0].freeze, false, 'reads must permit filter changes');
assert.equal(notices.length, 0);
raceUI.call_api('fresko_universe.money.submit_collection', {}, () => {});
raceUI.call_api('fresko_universe.money.submit_collection', {}, () => {});
assert.equal(pending.length, 3, 'duplicate writes stay serialized');
assert.equal(pending[2].freeze, true);
assert.equal(notices.length, 1);
pending[2].callback({ message: {} });
assert.equal(raceUI.in_flight, false);
console.log('Money delayed-read and duplicate-write checks passed');
