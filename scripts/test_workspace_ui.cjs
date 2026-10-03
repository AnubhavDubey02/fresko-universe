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
                appendChild: (child) => { el.children.push(child); return child; },
                setAttribute: (k, v) => { el.attrs[k] = v; },
                getAttribute: (k) => el.attrs[k],
                addEventListener: () => {}
            };
            createdElements.push(el);
            return el;
        },
        createTextNode: (t) => String(t)
    },
    Node: function() {},
    window: {},
    console: console,
    Math: Math,
    crypto: typeof crypto !== 'undefined' ? crypto : undefined
};

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
    let capturedDialogConfig = null;
    sandbox.frappe.ui.Dialog = function(cfg) {
        capturedDialogConfig = cfg;
        this.fields = cfg.fields;
        this.get_value = () => '';
        this.set_value = () => {};
        this.set_df_property = () => {};
        this.get_field = () => ({ $input: { attr: () => {} } });
        this.show = () => {};
        this.hide = () => {};
    };

    ws.open_allocation_dialog(null, null);
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

    const calls = [];
    sandbox.frappe.call = (request) => {
        calls.push(request);
        return Promise.resolve({ message: { lines: [] } });
    };
    ws.as_of_value = '';
    ws.open_allocation_dialog({ name: 'SYNTHETIC-SALE' }, null);
    const saleLookup = calls.find(call => call.method === 'fresko_universe.commercial.get_sale_as_of');
    assert(saleLookup, 'sale line lookup must call get_sale_as_of');
    assert.strictEqual(saleLookup.args.as_of, '2026-10-03 18:00:00', 'required as_of must fall back to site time when the cutoff is empty');
    console.log('✓ Allocation dialog contract (Select lines, Data decimal, no Float/BOX default) verified');
}

console.log('All offline VM UI logic tests passed. Full browser verification pending root bench execution.');
