/**
 * Deterministic offline harness testing actual Fresko Workspace UI source functions via Node VM.
 * NOTE: Node offline harness validates code invariants and syntax; it is not browser proof.
 * Full browser E2E and multi-tenant live execution remain verification pending root runs.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const srcPath = path.resolve(__dirname, '../fresko_universe/fresko_universe/fresko_core/page/fresko_workspace/fresko_workspace.js');
const srcCode = fs.readFileSync(srcPath, 'utf8');
let capturedDialogConfig = null;
const dialogValues = {};

// Create sandbox providing minimal Frappe and DOM stubs for compiling actual workspace code
const createdElements = [];
const sandbox = {
    frappe: {
        pages: { 'fresko-workspace': {} },
        ui: {
            make_app_page: () => ({
                clear_fields: () => {},
                clear_actions: () => {},
                add_field: (cfg) => ({ get_value: () => null, set_value: () => {} }),
                set_primary_action: () => {},
                add_inner_button: () => {},
                main: { empty: () => ({ append: () => {} }) }
            }),
            Dialog: function(config) {
                this.config = config;
                this.fields = config.fields || [];
                this.$wrapper = {
                    find: () => ({
                        each: () => {},
                        length: 0
                    })
                };
                this.get_field = (name) => ({
                    $input: { val: () => '', attr: () => {} },
                    $wrapper: { empty: () => {} }
                });
                this.get_value = (name) => '';
                this.set_value = () => {};
                this.set_df_property = () => {};
                this.show = () => {};
                this.hide = () => {};
            }
        },
        datetime: { now_datetime: () => '2026-10-03 18:00:00' },
        get_route: () => [],
        call: () => Promise.resolve({})
    },
    __: (s) => s,
    document: {
        createElement: (tag) => {
            const el = {
                tagName: tag.toUpperCase(),
                className: '',
                style: {},
                children: [],
                attrs: {},
                _innerHTML: '',
                get innerHTML() { return this._innerHTML; },
                set innerHTML(val) {
                    this._innerHTML = val;
                    if (val === '') this.children = [];
                },
                appendChild: (child) => { el.children.push(child); return child; },
                setAttribute: (k, v) => { el.attrs[k] = v; },
                removeAttribute: (k) => { delete el.attrs[k]; },
                getAttribute: (k) => el.attrs[k],
                listeners: {},
                addEventListener: (name, callback) => { el.listeners[name] = callback; }
            };
            createdElements.push(el);
            return el;
        },
        createTextNode: (t) => String(t)
    },
    Node: function() {},
    sessionStorage: {
        _store: {},
        getItem(k) { return this._store[k] || null; },
        setItem(k, v) { this._store[k] = String(v); },
        removeItem(k) { delete this._store[k]; }
    },
    window: {},
    console: console,
    Math: Math,
    crypto: typeof crypto !== 'undefined' ? crypto : undefined
};
sandbox.frappe.set_route = (route) => { sandbox.frappe._last_route = route; };

vm.createContext(sandbox);
vm.runInContext(srcCode, sandbox);

console.log('Running test_workspace_ui.cjs on actual compiled source functions...');
const FreskoWorkspace = vm.runInContext('FreskoWorkspace', sandbox);

// 1. Test escape_html (actual source function)
{
    const escape_html = sandbox.escape_html;
    assert.strictEqual(typeof escape_html, 'function', 'escape_html must be defined in source');
    const clean = escape_html('<script>alert("xss")</script>&foo=\'bar\';');
    assert(!clean.includes('<script>'), 'Failed to escape open script tag');
    assert(!clean.includes('"'), 'Failed to escape quotes');
    assert(!clean.includes("'"), 'Failed to escape single quotes');
    assert.strictEqual(escape_html(null), '');
    assert.strictEqual(escape_html(undefined), '');
    console.log('✓ Actual escape_html verified');
}

// 2. Test render_raw_alias_node (actual source function - preserves whitespace)
{
    const render_raw_alias_node = sandbox.render_raw_alias_node;
    assert.strictEqual(typeof render_raw_alias_node, 'function');
    const alias = '   Raw   Spaced   Customer   ';
    const node = render_raw_alias_node(alias);
    assert.strictEqual(node.textContent, alias, 'Exact whitespace must be preserved');
    assert.strictEqual(node.className, 'fresko-raw-alias');
    console.log('✓ Actual render_raw_alias_node verified');
}

// 3. Test financial amount & qty non-zero null semantics (actual source functions)
{
    const format_financial_amount = sandbox.format_financial_amount;
    const format_qty = sandbox.format_qty;
    assert.strictEqual(format_financial_amount(null, 'INR'), 'PENDING / UNKNOWN');
    assert.strictEqual(format_financial_amount(undefined, 'INR'), 'PENDING / UNKNOWN');
    assert.strictEqual(format_financial_amount('', 'INR'), 'PENDING / UNKNOWN');
    assert.notStrictEqual(format_financial_amount(null, 'INR'), '0');
    assert.notStrictEqual(format_financial_amount(null, 'INR'), 'INR 0.00');
    assert.strictEqual(format_financial_amount('150000.00', 'INR'), 'INR 150000.00');

    assert.strictEqual(format_qty(null, 'BOX'), 'UNKNOWN');
    assert.strictEqual(format_qty(undefined, 'BOX'), 'UNKNOWN');
    assert.notStrictEqual(format_qty(null, 'BOX'), '0 BOX');
    assert.strictEqual(format_qty('450', 'BOX'), '450 BOX');
    console.log('✓ Actual format_financial_amount & format_qty verified');
}

// 4. Test decimal validation regex functions (actual source functions)
{
    const is_valid_decimal_string = sandbox.is_valid_decimal_string;
    const is_positive_decimal_string = sandbox.is_positive_decimal_string;
    assert.strictEqual(typeof is_valid_decimal_string, 'function');
    assert.strictEqual(typeof is_positive_decimal_string, 'function');

    // Valid decimal strings
    assert.strictEqual(is_positive_decimal_string('100.50'), true);
    assert.strictEqual(is_positive_decimal_string('0.000001', 6), true);
    assert.strictEqual(is_positive_decimal_string('450', 6), true);

    // Rejection of invalid inputs: exponents, trailing junk, signs, non-strings
    assert.strictEqual(is_positive_decimal_string('1e5'), false, 'Exponents must be rejected');
    assert.strictEqual(is_positive_decimal_string('100.50abc'), false, 'Trailing junk must be rejected');
    assert.strictEqual(is_positive_decimal_string('-10'), false, 'Negative values must be rejected');
    assert.strictEqual(is_positive_decimal_string('0'), false, 'Pure zero must be rejected for positive quantity');
    assert.strictEqual(is_positive_decimal_string('0.00'), false, 'Zero decimal must be rejected for positive quantity');
    assert.strictEqual(is_positive_decimal_string('10.1234567', 6), false, 'Excess decimal scale must be rejected');
    assert.strictEqual(is_valid_decimal_string('150.25', 2), true);
    assert.strictEqual(is_valid_decimal_string('150.255', 2), false, 'Rate beyond 2 decimals rejected');
    console.log('✓ Decimal validation string regexes (no parseFloat/exponent) verified');
}

// 5. Test UUID generator
{
    const generate_uuid = sandbox.generate_uuid;
    assert.strictEqual(typeof generate_uuid, 'function');
    const u1 = generate_uuid();
    const u2 = generate_uuid();
    assert.notStrictEqual(u1, u2);
    assert.match(u1, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i, 'UUID format invalid');
    console.log('✓ UUID generator verified');
}

// 6. Test Role Separation and can_prepare calculation
{
    assert.strictEqual(typeof FreskoWorkspace, 'function');

    function getPreparedContext(roles) {
        const ws = Object.create(FreskoWorkspace.prototype);
        let setupCalled = false;
        ws.setup_ui = () => { setupCalled = true; };
        ws.render_fatal_error = (message) => { throw new Error(message); };
        sandbox.frappe.call = () => ({
            then: (callback) => {
                callback({ message: { roles, is_internal: roles.includes('Fresko Accounts') || roles.includes('System Manager') } });
                return { catch: () => {} };
            }
        });
        ws.init();
        assert(setupCalled, 'workspace setup must follow successful server authorization');
        return ws.user_context;
    }

    assert.strictEqual(getPreparedContext(['Fresko Salesperson']).can_prepare, true);
    assert.strictEqual(getPreparedContext(['System Manager']).can_prepare, false, 'System Manager alone must not prepare commercial sales');
    assert.strictEqual(getPreparedContext(['Fresko Accounts']).can_prepare, false, 'Fresko Accounts must not prepare commercial sales');
    assert.strictEqual(getPreparedContext(['Fresko Approver']).can_prepare, false, 'Fresko Approver must not prepare commercial sales');
    console.log('✓ Actual init() role authorization (Salesperson prepare only) verified');
}

// 7. Regression Test on Allocation Dialog Contract (IDs, Select pickers, no Float, no guessed BOX)
{
    const ws = Object.create(FreskoWorkspace.prototype);
    ws.as_of_value = '2026-10-03 18:00:00';
    const calls = [];
    const messages = [];
    const values = {};
    sandbox.frappe.msgprint = (message) => messages.push(String(message));
    sandbox.frappe.session = { user: 'maker@example.invalid' };
    sandbox.frappe.ui.Dialog = function(cfg) {
        capturedDialogConfig = cfg;
        this.fields = cfg.fields;
        this.get_value = (name) => dialogValues[name] || '';
        this.set_value = (name, value) => { dialogValues[name] = value; };
        this.set_df_property = () => {};
        this.get_field = () => ({ $input: { attr: () => {} } });
        this.show = () => {};
        this.hide = () => {};
    };

    ws.container_name = 'SYNTHETIC-CONTAINER';
    ws.container_data = { projection_mode: 'LIVE' };
    ws.as_of_value = '';
    sandbox.frappe.call = (request) => {
        calls.push(request);
        return Promise.resolve({ message: { lines: [] } });
    };
    ws.open_allocation_dialog({ name: 'SYNTHETIC-SALE', current_version: 7 }, null);
    assert(capturedDialogConfig, 'open_allocation_dialog did not instantiate Dialog');
    const fields = capturedDialogConfig.fields;

    const qtyField = fields.find(f => f.fieldname === 'qty');
    assert(qtyField, 'qty field missing');
    assert.strictEqual(qtyField.fieldtype, 'Data', 'qty field must be Data (string decimal), never Float');

    const saleLineKeyField = fields.find(f => f.fieldname === 'sale_line_key');
    assert(saleLineKeyField, 'sale_line_key field missing');
    assert.strictEqual(saleLineKeyField.fieldtype, 'Select', 'sale_line_key must be Select dropdown populated from API, never guessed Data line_1');

    const outwardLineKeyField = fields.find(f => f.fieldname === 'outward_line_key');
    assert(outwardLineKeyField, 'outward_line_key field missing');
    assert.strictEqual(outwardLineKeyField.fieldtype, 'Select', 'outward_line_key must be Select dropdown populated from API, never guessed Data line_1');

    const uomField = fields.find(f => f.fieldname === 'uom');
    assert(uomField, 'uom field missing');
    assert.strictEqual(uomField.read_only, 1, 'uom must be derived and read-only, never hardcoded BOX default');

    const evtField = fields.find(f => f.fieldname === 'source_event_id');
    assert(evtField, 'source_event_id field missing');
    assert.strictEqual(evtField.hidden, 1, 'source_event_id must be hidden from user');

    const saleLookup = calls.find(call => call.method === 'fresko_universe.commercial.get_sale_current');
    assert(saleLookup, 'Live allocation sale lookup must use get_sale_current');
    assert(!('as_of' in saleLookup.args), 'Live lookup must not synthesize a historical cutoff');
    console.log('✓ Allocation dialog contract and live current-sale lookup verified');
}

async function runProjectionRegressionTests() {
function allNodes(node, result = []) {
    if (!node || typeof node !== 'object') return result;
    result.push(node);
    (node.children || []).forEach(child => allNodes(child, result));
    return result;
}
// 8. Live/Historical mode: exact current tokens, no fallback, programmatic guards,
//    and a dialog opened live cannot mutate after switching to a historical cutoff.
{
    const ws = Object.create(FreskoWorkspace.prototype);
    const calls = [];
    const messages = [];
    sandbox.frappe.msgprint = (message) => messages.push(String(message));
    sandbox.frappe.call = (request) => {
        calls.push(request);
        return Promise.resolve({ message: {} });
    };
    ws.container_name = 'SYNTHETIC-CONTAINER';
    ws.as_of_value = '';
    ws.container_data = { projection_mode: 'LIVE' };
    ws.user_context = { can_prepare: true, can_verify: true, can_approve: true, roles: ['Fresko Salesperson', 'Fresko Accounts', 'Fresko Approver'] };
    ws.load_container_data = () => {};

    const liveSale = { name: 'SALE-1', status: 'DRAFT', projection_mode: 'LIVE', current_version: 9, lines: [], allocations: [] };
    ws.submit_sale(liveSale);
    let mutation = calls.find(call => call.method === 'fresko_universe.commercial.submit_sale');
    assert(mutation, 'Live sale submit should dispatch');
    assert.strictEqual(mutation.args.expected_version, 9, 'Sale action must send the captured current_version exactly');
    assert(!calls.some(call => call.args && call.args.expected_version === null), 'No mutation may fall back to null/version 1');

    for (const [method, action] of [
        ['fresko_universe.commercial.verify_sale', () => ws.verify_sale(liveSale)],
        ['fresko_universe.commercial.approve_sale', () => ws.approve_sale(liveSale)]
    ]) {
        calls.length = 0;
        action();
        const request = calls.find(call => call.method === method);
        assert(request, `${method} should dispatch in Live mode`);
        assert.strictEqual(request.args.expected_version, 9, `${method} must forward current_version exactly`);
    }

    const currentMapping = { name: 'ALIAS-1', version: 4 };
    const currentAllocation = { name: 'ALLOC-1', version: 6 };
    for (const [method, action, expected] of [
        ['fresko_universe.commercial.verify_alias_mapping', () => ws.verify_alias(currentMapping), 4],
        ['fresko_universe.commercial.approve_alias_mapping', () => ws.approve_alias(currentMapping), 4],
        ['fresko_universe.commercial.verify_sale_outward_allocation', () => ws.verify_allocation(currentAllocation), 6],
        ['fresko_universe.commercial.approve_sale_outward_allocation', () => ws.approve_allocation(currentAllocation), 6]
    ]) {
        calls.length = 0;
        action();
        const request = calls.find(call => call.method === method);
        assert(request, `${method} should dispatch in Live mode`);
        assert.strictEqual(request.args.expected_version, expected, `${method} must forward the captured row version exactly`);
    }

    calls.length = 0;
    ws.submit_sale({ name: 'SALE-MISSING-TOKEN', status: 'DRAFT' });
    assert.strictEqual(calls.length, 0, 'Missing current_version must block programmatic mutation');
    const missingVersionCard = ws.render_selected_sale_detail({ name: 'SALE-UNKNOWN', status: 'DRAFT', lines: [], allocations: [] });
    const renderedText = allNodes(missingVersionCard).flatMap(node => node.children || []).filter(child => typeof child === 'string').join(' ');
    assert(!renderedText.includes('Version 1'), 'Unknown current version must not be displayed as version 1');

    ws.as_of_value = '2026-10-01 12:00:00';
    ws.container_data = { projection_mode: 'HISTORICAL', as_of: ws.as_of_value };
    calls.length = 0;
    for (const action of [
        () => ws.submit_sale(liveSale), () => ws.verify_sale(liveSale), () => ws.approve_sale(liveSale),
        () => ws.verify_alias(currentMapping), () => ws.approve_alias(currentMapping),
        () => ws.verify_allocation(currentAllocation), () => ws.approve_allocation(currentAllocation)
    ]) action();
    assert.strictEqual(calls.length, 0, 'Historical view must block all direct programmatic workflow mutations');
    const historicalCard = ws.render_selected_sale_detail(liveSale);
    function allNodes(node, result = []) {
        if (!node || typeof node !== 'object') return result;
        result.push(node);
        (node.children || []).forEach(child => allNodes(child, result));
        return result;
    }
    const actionNodes = allNodes(historicalCard).filter(node => node.listeners && node.listeners.click);
    assert(actionNodes.every(node => node.attrs && node.attrs.disabled === 'disabled'), 'Historical Sale detail may show action affordances only as disabled');

    // Open a rejection prompt while Live, then switch to History before submitting it.
    ws.as_of_value = '';
    ws.container_data = { projection_mode: 'LIVE' };
    let promptSubmit;
    sandbox.frappe.prompt = (_fields, callback) => { promptSubmit = callback; };
    ws.reject_sale_dialog({ name: 'SALE-1', current_version: 9, projection_mode: 'LIVE' });
    assert.strictEqual(typeof promptSubmit, 'function', 'Live reject dialog should open');
    promptSubmit({ reason: 'synthetic reason' });
    const liveReject = calls.find(call => call.method === 'fresko_universe.commercial.reject_sale');
    assert(liveReject, 'Live Sale rejection should dispatch');
    assert.strictEqual(liveReject.args.expected_version, 9, 'Reject must forward the captured current_version exactly');
    ws.as_of_value = '2026-10-01 12:00:00';
    ws.container_data = { projection_mode: 'HISTORICAL', as_of: ws.as_of_value };
    calls.length = 0;
    promptSubmit({ reason: 'synthetic reason' });
    assert.strictEqual(calls.length, 0, 'Dialog opened in Live must re-check mode before historical submission');

    // Use a proposal dialog primary action to prove the same check covers a delayed callback.
    ws.as_of_value = '';
    ws.container_data = { projection_mode: 'LIVE' };
    dialogValues.sale_line_key = 'line-1';
    dialogValues.outward_line_key = 'out-1';
    dialogValues.qty = '1';
    dialogValues.uom = 'BOX';
    ws.open_allocation_dialog({ name: 'SALE-1', current_version: 9 }, null);
    const proposal = capturedDialogConfig.primary_action;
    ws.as_of_value = '2026-10-01 12:00:00';
    ws.container_data = { projection_mode: 'HISTORICAL', as_of: ws.as_of_value };
    calls.length = 0;
    proposal({ sale_name: 'SALE-1', outward: 'OUT-1', evidence: 'EVIDENCE-1' });
    assert.strictEqual(calls.length, 0, 'Allocation dialog opened in Live must re-check mode on submit');
    console.log('✓ Live/Historical mutation guards and delayed dialog callbacks verified');
}

// 9. Historical queue suppression and late-read rejection; selected Sale must rebind
//    to the fresh current token from the accepted response, never keep an old object.
{
    const ws = Object.create(FreskoWorkspace.prototype);
    const calls = [];
    ws.container_name = 'SYNTHETIC-CONTAINER';
    ws.as_of_value = '2026-10-01 12:00:00';
    ws.container_data = { projection_mode: 'HISTORICAL' };
    ws.current_load_seq = 0;
    ws.content_panel = { querySelector: () => ({ innerHTML: '', appendChild: () => {} }) };
    sandbox.frappe.call = (request) => { calls.push(request); return Promise.resolve({ message: [] }); };
    ws.load_alias_mappings();
    ws.load_sale_allocations({ name: 'SALE-1' }, { innerHTML: '', appendChild: () => {} });
    assert.strictEqual(calls.length, 0, 'Historical view must not load current alias/allocation review queues');

    const pending = [];
    sandbox.frappe.call = (request) => {
        calls.push(request);
        return new Promise(resolve => pending.push(resolve));
    };
    ws.as_of_value = '';
    ws.container_data = { projection_mode: 'LIVE' };
    ws.selected_sale = { name: 'SALE-1', current_version: 2, marker: 'stale' };
    ws.update_header_banner = () => {};
    ws.render_active_tab = () => {};
    ws.render_loading = () => {};
    ws.render_error = () => {};
    ws.load_container_data();
    assert.strictEqual(calls[calls.length - 1].args.as_of, null, 'Blank cutoff should request Live projection without a synthetic timestamp');
    ws.as_of_value = '2026-10-01 12:00:00';
    ws.load_container_data();
    const liveRow = { name: 'SALE-1', current_version: 5, marker: 'latest' };
    const staleRow = { name: 'SALE-1', version_at_cutoff: 1, marker: 'historical' };
    pending[0]({ message: { projection_mode: 'LIVE', sales: [staleRow] } });
    await new Promise(resolve => setImmediate(resolve));
    assert.notStrictEqual(ws.selected_sale, staleRow, 'Late response from the prior filter must be ignored');
    pending[1]({ message: { projection_mode: 'HISTORICAL', sales: [liveRow] } });
    await new Promise(resolve => setImmediate(resolve));
    assert.strictEqual(ws.selected_sale, liveRow, 'Accepted response must rebind selected Sale by name to its new row');
    assert.strictEqual(ws.selected_sale.current_version, 5, 'Rebound selection must use its current captured version');
    assert.strictEqual(ws.selected_sale.version, undefined, 'No version-1/null compatibility fallback is introduced');

    // Clearing the selected Container while a request is in flight must invalidate it.
    ws.container_name = 'SYNTHETIC-CONTAINER-2';
    ws.as_of_value = '';
    ws.selected_sale = { name: 'SALE-2', current_version: 1 };
    ws.load_container_data();
    const clearedContainerResponse = { projection_mode: 'LIVE', sales: [{ name: 'SALE-2', current_version: 2 }] };
    ws.container_name = null;
    ws.selected_sale = null;
    ws.load_container_data();
    pending[2]({ message: clearedContainerResponse });
    await new Promise(resolve => setImmediate(resolve));
    assert.strictEqual(ws.container_data, null, 'A late response must not repopulate a container after its filter is cleared');
    console.log('✓ Historical queue suppression and stale selection/token rebinding verified');

    // 9. Test Operator Action Inbox Feed & Detail Pane
    {
        const inboxWs = Object.create(FreskoWorkspace.prototype);
        assert.strictEqual(typeof inboxWs.render_inbox_panel, 'function');
        assert.strictEqual(typeof inboxWs.render_inbox_feed, 'function');
        assert.strictEqual(typeof inboxWs.render_inbox_detail_pane, 'function');

        const leftCol = sandbox.document.createElement('div');
        const rightCol = sandbox.document.createElement('div');

        // Test empty feed
        inboxWs.render_inbox_feed({ sections: [], counts: { total_actionable: 0 } }, leftCol, rightCol);
        assert(leftCol.children.length > 0, 'Empty feed should render All Clear message');

        // Test populated feed with action item and blocked chips
        const sampleItem = {
            kind: 'unpriced_sale',
            doc_ref: 'FSALE-001',
            human_title: 'Unpriced Sale: Om Trading',
            subtitle: 'Container FCON-001',
            state: 'DRAFT',
            state_reason: 'Awaiting rate proposal',
            amount_string: 'PENDING / UNKNOWN',
            qty_string: '100 boxes',
            actions: [
                { action: 'propose_rate', label: 'Propose Rate', allowed: false, blocked_reason: 'Awaiting preparing salesperson' }
            ],
            evidence_state: 'RESTRICTED'
        };
        const feed = {
            counts: { total_actionable: 1 },
            sections: [
                { title: 'Unpriced Sales', count: 1, items: [sampleItem] }
            ]
        };
        inboxWs.render_inbox_feed(feed, leftCol, rightCol);
        assert(leftCol.children.length > 0, 'Feed should render sections');
        assert(rightCol.children.length > 0, 'Detail pane should render selected item');

        // FR-QA-020: Verify card accessibility (role=button, tabindex=0, keydown handler)
        const card = leftCol.children[0].children[1];
        assert.strictEqual(card.attrs.role, 'button', 'Card must have role="button"');
        assert.strictEqual(card.attrs.tabindex, '0', 'Card must have tabindex="0"');
        assert.strictEqual(typeof card.listeners.keydown, 'function', 'Card must have keydown listener');
        let cardKeydownHandled = false;
        inboxWs.render_inbox_detail_pane = (item) => { cardKeydownHandled = true; };
        card.listeners.keydown({ key: 'Enter', preventDefault: () => {} });
        assert.strictEqual(cardKeydownHandled, true, 'Enter key must trigger detail pane selection');

        console.log('✓ Operator Action Inbox feed, split view, keyboard navigation verified');

        // FR-QA-014: Live-only notice when as_of_value is set
        const liveOnlyWs = Object.create(FreskoWorkspace.prototype);
        liveOnlyWs.as_of_value = '2026-10-01 12:00:00';
        liveOnlyWs.content_panel = sandbox.document.createElement('div');
        liveOnlyWs.as_of_field = { set_value: (v) => { liveOnlyWs.as_of_value = v; } };
        let liveOnlyCallDispatched = false;
        sandbox.frappe.call = (req) => {
            if (req.method.includes('get_operator_action_feed')) liveOnlyCallDispatched = true;
            return Promise.resolve({ message: {} });
        };
        liveOnlyWs.render_inbox_panel();
        assert.strictEqual(liveOnlyCallDispatched, false, 'Historical view must not call get_operator_action_feed');
        const nodes = allNodes(liveOnlyWs.content_panel);
        const headingNode = nodes.find(n => (n.children || []).includes('Needs My Action is Live-Only'));
        assert(headingNode, 'Notice heading must indicate live-only');

        // Verify Return to Live button clears as_of
        const returnBtn = nodes.find(n => (n.children || []).includes('Return to Live'));
        assert(returnBtn && returnBtn.listeners && returnBtn.listeners.click, 'Return to Live button must exist');
        returnBtn.listeners.click();
        assert.ok(!liveOnlyWs.as_of_value, 'Return to Live must clear as_of_value');
        console.log('✓ FR-QA-014: Needs My Action live-only notice & Return to Live verified');

        // FR-QA-016: Target dispatch in execute_inbox_action
        const dispatchWs = Object.create(FreskoWorkspace.prototype);
        let switchedTab = null;
        let inspectedOutward = null;
        dispatchWs.switch_tab = (t) => { switchedTab = t; };
        dispatchWs.inspect_outward = (o) => { inspectedOutward = o; };
        dispatchWs.execute_inbox_action({ doc_ref: 'OUT-101', document_name: 'OUT-101' }, { action: 'propose_commercial_allocation' });
        assert.strictEqual(switchedTab, 'outwards', 'Outward allocation proposal must switch to outwards tab');
        assert.strictEqual(inspectedOutward, 'OUT-101', 'Outward allocation proposal must inspect outward');

        // Money navigation with sessionStorage target
        sandbox.sessionStorage.removeItem('fresko_money_target');
        dispatchWs.execute_inbox_action({ doctype: 'Fresko Collection', document_name: 'COLL-01' }, { action: 'verify_collection' });
        assert.strictEqual(sandbox.frappe._last_route, 'fresko-money', 'Money action must route to fresko-money');
        const storedTarget = JSON.parse(sandbox.sessionStorage.getItem('fresko_money_target'));
        assert.strictEqual(storedTarget.doctype, 'Fresko Collection');
        assert.strictEqual(storedTarget.document_name, 'COLL-01');
        console.log('✓ FR-QA-016: Target dispatch (outward tab & money routing) verified');

        // FR-QA-002: Idempotent render_sales_panel
        const salesWs = Object.create(FreskoWorkspace.prototype);
        salesWs.user_context = { can_prepare: true, roles: ['Fresko Salesperson'] };
        salesWs.container_data = { sales: [{ name: 'S-1', current_version: 1, projection_mode: 'LIVE' }] };
        salesWs.content_panel = sandbox.document.createElement('div');
        salesWs.is_live_view = () => true;
        salesWs.render_sales_panel();
        const childCount1 = salesWs.content_panel.children.length;
        salesWs.render_sales_panel();
        const childCount2 = salesWs.content_panel.children.length;
        assert.strictEqual(childCount1, childCount2, 'Repeated render_sales_panel must be idempotent without node accumulation');
        console.log('✓ FR-QA-002: Idempotent sales panel rendering verified');

        // FR-QA-004: + Prepare Sale disabled in historical mode
        salesWs.is_live_view = () => false;
        salesWs.as_of_value = '2026-10-01 12:00:00';
        salesWs.render_sales_panel();
        const prepBtn = salesWs.content_panel.children[0].children[0].children[0].children[1];
        assert.strictEqual(prepBtn.attrs.disabled, 'disabled', 'Prepare Sale button must be disabled in historical mode');
        console.log('✓ FR-QA-004: Prepare Sale button disabled in historical mode verified');

        // FR-QA-005: Alias queue error handling and Retry button
        const aliasWs = Object.create(FreskoWorkspace.prototype);
        aliasWs.content_panel = sandbox.document.createElement('div');
        const aliasWrap = sandbox.document.createElement('div');
        aliasWrap.setAttribute('id', 'fresko-alias-queue-wrap');
        aliasWs.content_panel.children.push(aliasWrap);
        aliasWs.content_panel.querySelector = (sel) => aliasWrap;
        aliasWs.is_live_view = () => true;
        aliasWs.current_load_seq = 1;
        let aliasRetried = false;
        sandbox.frappe.call = () => Promise.reject(new Error('Network failure'));
        aliasWs.load_alias_mappings();
        await new Promise(r => setImmediate(r));
        const retryBtn = aliasWrap.children.find(c => c.children && c.children.includes('Retry'));
        assert(retryBtn, 'Alias queue must render Retry button on error');
        aliasWs.load_alias_mappings = () => { aliasRetried = true; };
        retryBtn.listeners.click();
        assert.strictEqual(aliasRetried, true, 'Retry button click must re-trigger load_alias_mappings');
        console.log('✓ FR-QA-005: Alias queue error handling and Retry button verified');
    }
}

console.log('All offline VM UI logic tests passed. Full browser verification pending root bench execution.');
}

runProjectionRegressionTests().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
