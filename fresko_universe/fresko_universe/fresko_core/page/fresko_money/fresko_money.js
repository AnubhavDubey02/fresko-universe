frappe.pages['fresko-money'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Money Operations'),
		single_column: true
	});
	fresko_money.init(page);
};

var fresko_money = {
	in_flight: false,
	page: null,
	company_field: null,
	container_field: null,
	cutoff_field: null,
	active_tab: 'collections',

	has_role: function(role) {
		return frappe.user_roles && frappe.user_roles.includes(role);
	},
	is_supplier: function() {
		return (frappe.user_roles || []).some(function(role) { return role.toLowerCase().includes('supplier'); });
	},

	init: function(page) {
		var me = this;
		me.page = page;
		if (me.is_supplier() || (!me.has_role('Fresko Accounts') && !me.has_role('Fresko Approver'))) {
			$(page.main).html('<div class="fm-denied">' + __('Access denied: requires Fresko Accounts or Fresko Approver role.') + '</div>');
			return;
		}

		me.setup_filters();
		me.setup_layout();
		me.refresh_all();
	},

	setup_filters: function() {
		var me = this;
		me.company_field = me.page.add_field({
			fieldname: 'company',
			label: __('Company'),
			fieldtype: 'Link',
			options: 'Company',
			reqd: 1,
			default: frappe.defaults.get_user_default('Company'),
			change: function() { me.refresh_all(); }
		});
		me.container_field = me.page.add_field({
			fieldname: 'container',
			label: __('Container (Optional)'),
			fieldtype: 'Link',
			options: 'Fresko Container',
			change: function() { me.refresh_all(); }
		});
		me.cutoff_field = me.page.add_field({
			fieldname: 'cutoff',
			label: __('Cutoff As-Of'),
			fieldtype: 'Datetime',
			default: frappe.datetime.now_datetime(),
			change: function() { me.refresh_all(); }
		});

		if (me.has_role('Fresko Accounts')) {
		me.page.set_primary_action(__('New Collection'), function() {
			me.show_capture_collection_dialog();
		}, 'add');

		me.page.add_inner_button(__('Propose Allocation'), function() {
			me.show_propose_allocation_dialog();
		});
		me.page.add_inner_button(__('Propose Adjustment'), function() {
			me.show_propose_adjustment_dialog();
		});
		me.page.add_inner_button(__('Propose Application'), function() {
			me.show_propose_application_dialog();
		});
		}
		me.page.add_inner_button(__('Sync Ledger'), function() {
			me.call_api('fresko_universe.money.refresh_money_reconciliation', { company: me.get_company() }, function() {
				frappe.show_alert({ message: __('Reconciliation recalculated'), indicator: 'green' });
				me.refresh_all();
			});
		});
	},

	get_company: function() { return this.company_field ? this.company_field.get_value() : null; },
	get_container: function() { return this.container_field ? this.container_field.get_value() : null; },
	get_cutoff: function() { return this.cutoff_field ? this.cutoff_field.get_value() : null; },

	setup_layout: function() {
		var me = this;
		var html = [
			'<div class="fm-page">',
			'  <div class="fm-notice">',
			'    <span class="badge badge-warning">CAPTURED_SUBSET</span> ',
			'    <span>' + __('Balance projections authoritative from server ledger. Unknown sums displayed as PENDING.') + '</span>',
			'  </div>',
			'  <div class="fm-projections-bar row" id="fm-projections"></div>',
			'  <div class="fm-tabs">',
			'    <button class="fm-tab-btn active" data-tab="collections">' + __('Collections & Review') + '</button>',
			'    <button class="fm-tab-btn" data-tab="receivables">' + __('Receivables & Positions') + '</button>',
			'  </div>',
			'  <div class="fm-tab-content" id="fm-tab-collections">',
			'    <div class="fm-section" id="sec-collections"><h5>' + __('Collections') + '</h5><div class="fm-table-wrap" id="tbl-collections"></div></div>',
			'    <div class="fm-section" id="sec-allocations"><h5>' + __('Payment Allocations') + '</h5><div class="fm-table-wrap" id="tbl-allocations"></div></div>',
			'    <div class="fm-section" id="sec-adjustments"><h5>' + __('Receivable Adjustments') + '</h5><div class="fm-table-wrap" id="tbl-adjustments"></div></div>',
			'    <div class="fm-section" id="sec-applications"><h5>' + __('Adjustment Applications') + '</h5><div class="fm-table-wrap" id="tbl-applications"></div></div>',
			'    <div class="fm-section"><h5>' + __('Receipt Exceptions') + '</h5><div id="fm-money-exceptions"></div></div>',
			'  </div>',
			'  <div class="fm-tab-content hidden" id="fm-tab-receivables">',
			'    <div class="fm-receivable-query row">',
			'      <div class="col-sm-4"><input type="text" class="form-control input-sm" id="rec-customer" placeholder="' + __('Customer') + '"></div>',
			'      <div class="col-sm-3"><input type="text" class="form-control input-sm" id="rec-sale" placeholder="' + __('Sale ID') + '"></div>',
			'      <div class="col-sm-3"><button class="btn btn-primary btn-sm" id="btn-query-rec">' + __('Query Authoritative Debt') + '</button></div>',
			'    </div>',
			'    <div class="fm-receivable-result" id="fm-receivable-result"></div>',
			'  </div>',
			'</div>'
		].join('');

		$(me.page.main).html(html);

		$(me.page.main).find('.fm-tab-btn').on('click', function() {
			var tab = $(this).attr('data-tab');
			$(me.page.main).find('.fm-tab-btn').removeClass('active');
			$(this).addClass('active');
			$(me.page.main).find('.fm-tab-content').addClass('hidden');
			$('#fm-tab-' + tab).removeClass('hidden');
			me.active_tab = tab;
		});

		$(me.page.main).find('#btn-query-rec').on('click', function() {
			me.query_receivables();
		});
	},

	call_api: function(method, args, callback) {
		var me = this;
        var is_read = method.split('.').pop().indexOf('get_') === 0;
		if (!me.get_company()) { frappe.msgprint(__('Select a Company first.')); return; }
		if (me.in_flight) {
			frappe.msgprint(__('A request is already in-flight. Please wait.'));
			return;
		}
		me.in_flight = true;
		frappe.call({
			method: method,
			args: args,
			freeze: true,
			callback: function(r) {
				me.in_flight = false;
				if (r.exc) {
					frappe.msgprint(__('Server error encountered. Refreshing state.'));
					if (!is_read) me.refresh_all();
					return;
				}
				if (callback) callback(r.message);
			},
			error: function() {
				me.in_flight = false;
				frappe.msgprint(__('Request failed. View error log and refreshed state.'));
				if (!is_read) me.refresh_all();
			}
		});
	},

	refresh_all: function() {
		var me = this;
		var company = me.get_company();
		if (!company) return;
		me.load_projections();
		me.load_collections_tab();
		me.load_exceptions();
	},

	load_exceptions: function() {
        var me = this, company = me.get_company();
        frappe.call({ method: 'fresko_universe.money.get_open_money_exceptions', args: {company: company} }).then(function(r) {
            if (company !== me.get_company()) return;
            var box = $(me.page.main).find('#fm-money-exceptions').empty();
            ((r.message || {}).exceptions || []).forEach(function(row) {
                var link = $('<a></a>').attr('href', '/app/fresko-exception/' + encodeURIComponent(row.name)).text(row.exception_type + ': ' + row.collection);
                box.append($('<p></p>').append(link).append($('<span></span>').text(' — ' + row.description)));
            });
        });
    },

	load_projections: function() {
		var me = this;
		var comp = me.get_company();
		var cutoff = me.get_cutoff();
		me.call_api('fresko_universe.money.get_unallocated_collections', { company: comp, as_of: cutoff }, function(unalloc) {
			me.call_api('fresko_universe.money.get_bank_pending_collections', { company: comp, as_of: cutoff }, function(pending) {
				me.render_projections(unalloc || {}, pending || {});
			});
		});
	},

	render_projections: function(unalloc, pending) {
		var $box = $('#fm-projections');
		$box.empty();
		function cur_map(obj) {
			if (!obj) return '-';
			var keys = Object.keys(obj);
			if (!keys.length) return __('No captured eligible funds');
			return keys.map(function(k) { return frappe.utils.escape_html(k) + ' ' + frappe.utils.escape_html(obj[k] === null ? 'PENDING' : obj[k]); }).join(', ');
		}

		var cards = [
			{ label: __('Cash Declared Unallocated'), val: cur_map(unalloc.cash_unallocated_by_currency), cls: 'text-success' },
			{ label: __('Bank Cleared Unallocated'), val: cur_map(unalloc.bank_cleared_unallocated_by_currency), cls: 'text-primary' },
			{ label: __('Total Eligible Unallocated'), val: cur_map(unalloc.total_unallocated_by_currency), cls: 'text-info' },
			{ label: __('Bank Pending Authorizations'), val: cur_map(pending.pending_amount_by_currency), cls: 'text-warning' }
		];

		cards.forEach(function(c) {
			var col = $('<div class="col-sm-3 col-xs-6 fm-stat-card"></div>');
			var title = $('<div class="fm-stat-title"></div>').text(c.label);
			var num = $('<div class="fm-stat-val ' + c.cls + '"></div>').text(c.val);
			col.append(title).append(num);
			$box.append(col);
		});
	},

	load_collections_tab: function() {
		var me = this;
		var comp = me.get_company();
		me.render_doctype_list('Fresko Collection', '#tbl-collections', {
			doctype: 'Fresko Collection',
			filters: { company: comp },
			fields: ['name', 'status', 'company', 'direction', 'amount', 'currency', 'amount_state', 'payment_channel', 'bank_state', 'payer_raw', 'effective_at', 'modified', 'version', 'prepared_by', 'verified_by'],
			kind: 'collection'
		});
		me.render_doctype_list('Fresko Payment Allocation', '#tbl-allocations', {
			doctype: 'Fresko Payment Allocation',
			filters: { company: comp },
			fields: ['name', 'status', 'collection', 'allocation_type', 'amount', 'currency', 'sale', 'container', 'customer', 'modified', 'version', 'prepared_by', 'verified_by'],
			kind: 'allocation'
		});
		me.render_doctype_list('Fresko Receivable Adjustment', '#tbl-adjustments', {
			doctype: 'Fresko Receivable Adjustment',
			filters: { company: comp },
			fields: ['name', 'status', 'company', 'customer', 'adjustment_type', 'amount', 'currency', 'agreement_reference', 'modified', 'version', 'prepared_by', 'verified_by'],
			kind: 'adjustment'
		});
		me.render_doctype_list('Fresko Adjustment Application', '#tbl-applications', {
			doctype: 'Fresko Adjustment Application',
			filters: { company: comp },
			fields: ['name', 'status', 'receivable_adjustment', 'sale', 'amount', 'currency', 'modified', 'version', 'prepared_by', 'verified_by'],
			kind: 'application'
		});
	},

	render_doctype_list: function(doctype, target_sel, query_cfg) {
		var me = this;
		var $wrap = $(target_sel);
		$wrap.html('<div class="text-muted">' + __('Loading...') + '</div>');

		frappe.db.get_list(query_cfg.doctype, {
			filters: query_cfg.filters,
			fields: query_cfg.fields,
			limit_page_length: 25,
			order_by: 'modified desc'
		}).then(function(rows) {
			$wrap.empty();
			if (!rows || !rows.length) {
				$wrap.html('<div class="text-muted fm-empty">' + __('No records found.') + '</div>');
				return;
			}
			var $table = $('<table class="table table-bordered table-hover fm-table"></table>');
			var $thead = $('<thead></thead>');
			var $tbody = $('<tbody></tbody>');
			var headers = ['ID', 'Status', 'Summary', 'Amount', 'Modified', 'Actions'];
			var $trh = $('<tr></tr>');
			headers.forEach(function(h) { $trh.append($('<th></th>').text(h)); });
			$thead.append($trh);
			$table.append($thead).append($tbody);

			rows.forEach(function(r) {
				var $tr = $('<tr></tr>');
				var $link = $('<a href="#"></a>').text(r.name).on('click', function(e) {
					e.preventDefault();
					frappe.set_route('Form', doctype, r.name);
				});
				$tr.append($('<td></td>').append($link));
				$tr.append($('<td></td>').append($('<span class="badge badge-secondary"></span>').text(r.status || 'DRAFT')));

				var summary = '';
				if (query_cfg.kind === 'collection') {
					summary = [r.direction, r.payment_channel, r.bank_state, r.payer_raw].filter(Boolean).join(' | ');
				} else if (query_cfg.kind === 'allocation') {
					summary = [r.allocation_type, r.sale || r.container, 'Coll: ' + r.collection].filter(Boolean).join(' | ');
				} else if (query_cfg.kind === 'adjustment') {
					summary = [r.customer, r.adjustment_type, r.agreement_reference].filter(Boolean).join(' | ');
				} else {
					summary = ['Sale: ' + r.sale, 'Adj: ' + r.receivable_adjustment].join(' | ');
				}
				$tr.append($('<td></td>').text(summary));

				var amt_display = r.amount_state === 'UNKNOWN' ? 'PENDING' : ((r.currency || '') + ' ' + (r.amount || '-'));
				$tr.append($('<td></td>').text(amt_display));
				$tr.append($('<td></td>').text(frappe.datetime.comment_when(r.modified)));

				var $actions = $('<td></td>');
				me.render_workflow_buttons($actions, query_cfg.kind, r);
				$tr.append($actions);
				$tbody.append($tr);
			});
			$wrap.append($table);
		}).catch(function(err) {
			$wrap.html('<div class="text-danger">' + __('Failed to load data: ') + frappe.utils.escape_html(err.message || 'error') + '</div>');
		});
	},

	render_workflow_buttons: function($td, kind, row) {
		var me = this;
		var st = row.status || 'DRAFT';
		var name = row.name;

		function btn(lbl, cls, fn) {
			var $b = $('<button class="btn btn-xs ' + cls + ' fm-action-btn"></button>').text(lbl);
			$b.on('click', function() { fn(); });
			$td.append($b);
		}

		if (me.has_role('Fresko Accounts')) {
			if (st === 'DRAFT' && row.prepared_by === frappe.session.user) {
				btn(__('Submit'), 'btn-primary', function() {
					me.call_api('fresko_universe.money.submit_' + me.workflow_kind(kind), me.workflow_arg(kind, name, row.version), function() { me.refresh_all(); });
				});
			}
			if (st === 'REVIEW_PENDING' && row.prepared_by !== frappe.session.user) {
				btn(__('Verify'), 'btn-info', function() {
					me.call_api('fresko_universe.money.verify_' + me.workflow_kind(kind), me.workflow_arg(kind, name, row.version), function() { me.refresh_all(); });
				});
			}
		}

		if (me.has_role('Fresko Approver')) {
			if (st === 'VERIFIED' && row.prepared_by !== frappe.session.user && row.verified_by !== frappe.session.user) {
				btn(__('Approve'), 'btn-success', function() {
					me.call_api('fresko_universe.money.approve_' + me.workflow_kind(kind), me.workflow_arg(kind, name, row.version), function() { me.refresh_all(); });
				});
				btn(__('Reject'), 'btn-danger', function() {
					frappe.prompt({ fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }, function(v) {
						var payload = me.workflow_arg(kind, name, row.version);
						payload.reason = v.reason;
						me.call_api('fresko_universe.money.reject_' + me.workflow_kind(kind), payload, function() { me.refresh_all(); });
					}, __('Reject ' + kind), __('Confirm'));
				});
			}
			if (st === 'APPROVED') {
				btn(__('Reverse'), 'btn-warning', function() {
					frappe.prompt([
						{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Reversal Reason'), reqd: 1 },
						{ fieldname: 'evidence', fieldtype: 'Small Text', label: __('Reversal Evidence'), reqd: 1 }
					], function(v) {
						var payload = me.workflow_arg(kind, name, row.version);
						payload.reason = v.reason;
						payload.evidence = v.evidence;
						me.call_api('fresko_universe.money.reverse_' + me.workflow_kind(kind), payload, function() { me.refresh_all(); });
					}, __('Reverse ' + kind), __('Execute Reversal'));
				});
			}
		}

		if (me.has_role('Fresko Accounts') && kind === 'collection' && st === 'APPROVED') {
			btn(__('Supersede'), 'btn-default', function() {
				me.show_supersede_dialog(name);
			});
		}
	},

	workflow_kind: function(kind) { return {collection: 'collection', allocation: 'payment_allocation', adjustment: 'adjustment', application: 'adjustment_application'}[kind]; },

	workflow_arg: function(kind, name, version) {
		var res = { expected_version: version };
		if (kind === 'collection') res.collection_name = name;
		else if (kind === 'allocation') res.allocation_name = name;
		else if (kind === 'adjustment') res.adjustment_name = name;
		else if (kind === 'application') res.application_name = name;
		return res;
	},

	show_capture_collection_dialog: function() {
		var me = this;
		var d = new frappe.ui.Dialog({
			title: __('Receive / Capture Collection'),
			fields: [
				{ fieldname: 'direction', label: __('Direction'), fieldtype: 'Select', options: ['UNKNOWN', 'INFLOW', 'OUTFLOW', 'INTERNAL_TRANSFER'], default: 'INFLOW', reqd: 1 },
				{ fieldname: 'amount_state', label: __('Amount State'), fieldtype: 'Select', options: ['KNOWN', 'UNKNOWN'], default: 'KNOWN', reqd: 1 },
				{ fieldname: 'amount', label: __('Amount (Decimal Text)'), fieldtype: 'Data', depends_on: 'eval:doc.amount_state==="KNOWN"' },
				{ fieldname: 'currency', label: __('Currency'), fieldtype: 'Data', default: 'INR', reqd: 1 },
				{ fieldname: 'payment_channel', label: __('Payment Channel'), fieldtype: 'Select', options: ['BANK', 'CASH', 'UNKNOWN'], default: 'BANK', reqd: 1 },
				{ fieldname: 'bank_state', label: __('Bank State (Pending/Cleared/None)'), fieldtype: 'Select', options: ['NONE', 'UNKNOWN', 'PENDING', 'AUTHORIZATION_INPROCESS', 'BANK_CLEARED'], default: 'PENDING' },
				{ fieldname: 'source_classification', label: __('Classification'), fieldtype: 'Select', options: ['NONE', 'BANK_RECEIPT', 'BANK_CREDIT_CONFIRMATION', 'RTGS_NEFT', 'CASH_DECLARATION', 'OTHER'], default: 'NONE' },
				{ fieldname: 'payer_raw', label: __('Payer Raw (Exact string)'), fieldtype: 'Data' },
				{ fieldname: 'bank_account', label: __('Bank Account'), fieldtype: 'Link', options: 'Bank Account' },
				{ fieldname: 'bank_reference', label: __('Bank Reference / UTR'), fieldtype: 'Data' },
				{ fieldname: 'rail', label: __('Rail (UPI/NEFT/RTGS/IMPS/CASH)'), fieldtype: 'Data' },
				{ fieldname: 'customer', label: __('Customer Link'), fieldtype: 'Link', options: 'Customer' },
				{ fieldname: 'effective_at', label: __('Effective At'), fieldtype: 'Datetime', default: frappe.datetime.now_datetime() },
				{ fieldname: 'source_evidence', label: __('Receipt Evidence (Optional for declared cash)'), fieldtype: 'Link', options: 'Fresko Evidence' }
			],
			primary_action_label: __('Create Collection'),
			primary_action: function(v) {
				if (v.amount_state === 'UNKNOWN') v.amount = null;
				if (v.payment_channel === 'CASH') v.bank_state = 'NONE';
				v.company = me.get_company();
				v.source_namespace = 'manual_workspace';
				v.source_event_id = d.fresko_event_id;
				me.call_api('fresko_universe.money.create_collection', v, function() {
					d.hide();
					frappe.show_alert({ message: __('Collection captured'), indicator: 'green' });
					me.refresh_all();
				});
			}
		});
		d.fresko_event_id = crypto.randomUUID();
		d.show();
	},

	show_supersede_dialog: function(coll_name) {
		var me = this;
		var d = new frappe.ui.Dialog({
			title: __('Supersede / Correct Collection: ' + coll_name),
			fields: [
				{ fieldname: 'reason', label: __('Correction Reason'), fieldtype: 'Small Text', reqd: 1 },
				{ fieldname: 'source_evidence', label: __('New Evidence / Reference'), fieldtype: 'Link', options: 'Fresko Evidence', reqd: 1 },
				{ fieldname: 'payer_raw', label: __('Payer Raw (Corrected)'), fieldtype: 'Data' },
				{ fieldname: 'bank_reference', label: __('Bank Reference (Corrected)'), fieldtype: 'Data' },
				{ fieldname: 'amount', label: __('Amount (Corrected Decimal Text)'), fieldtype: 'Data' },
				{ fieldname: 'bank_state', label: __('Bank State (Leave blank to preserve)'), fieldtype: 'Select', options: ['', 'UNKNOWN', 'PENDING', 'AUTHORIZATION_INPROCESS', 'BANK_CLEARED'] },
				{ fieldname: 'bank_account', label: __('Bank Account (Optional correction)'), fieldtype: 'Link', options: 'Bank Account' },
				{ fieldname: 'source_classification', label: __('Receipt Classification (Leave blank to preserve)'), fieldtype: 'Select', options: ['', 'NONE', 'BANK_RECEIPT', 'BANK_CREDIT_CONFIRMATION', 'RTGS_NEFT', 'CASH_DECLARATION', 'OTHER'] },
				{ fieldname: 'direction', label: __('Direction (Leave blank to preserve)'), fieldtype: 'Select', options: ['', 'UNKNOWN', 'INFLOW', 'OUTFLOW', 'INTERNAL_TRANSFER'] }
			],
			primary_action_label: __('Execute Correction'),
			primary_action: function(v) {
				var changes = {};
				if (v.payer_raw) changes.payer_raw = v.payer_raw;
				if (v.bank_reference) changes.bank_reference = v.bank_reference;
				if (v.amount) { changes.amount = v.amount; changes.amount_state = 'KNOWN'; }
				['bank_state', 'bank_account', 'source_classification', 'direction'].forEach(function(key) { if (v[key]) changes[key] = v[key]; });
				var payload = {
					collection_name: coll_name,
					source_event_id: d.fresko_event_id,
					reason: v.reason,
					source_evidence: v.source_evidence,
					changes: changes
				};
				me.call_api('fresko_universe.money.supersede_collection', payload, function() {
					d.hide();
					frappe.show_alert({ message: __('Collection superseded'), indicator: 'green' });
					me.refresh_all();
				});
			}
		});
		d.fresko_event_id = crypto.randomUUID();
		d.show();
	},

	show_propose_allocation_dialog: function() {
		var me = this;
		var d = new frappe.ui.Dialog({
			title: __('Propose Payment Allocation'),
			fields: [
				{ fieldname: 'collection', label: __('Collection'), fieldtype: 'Link', options: 'Fresko Collection', reqd: 1 },
				{ fieldname: 'allocation_type', label: __('Type'), fieldtype: 'Select', options: ['SALE', 'CONTAINER_UNAPPLIED'], default: 'SALE', reqd: 1 },
				{ fieldname: 'info', fieldtype: 'HTML', options: '<p class="text-muted text-small">' + __('CONTAINER_UNAPPLIED parks unapplied money for a container without discharging any sales debt.') + '</p>' },
				{ fieldname: 'amount', label: __('Amount (Decimal Text)'), fieldtype: 'Data', reqd: 1 },
				{ fieldname: 'currency', label: __('Currency'), fieldtype: 'Data', default: 'INR', reqd: 1 },
				{ fieldname: 'sale', label: __('Sale ID'), fieldtype: 'Link', options: 'Fresko Commercial Sale', depends_on: 'eval:doc.allocation_type==="SALE"' },
				{ fieldname: 'container', label: __('Container'), fieldtype: 'Link', options: 'Fresko Container' },
				{ fieldname: 'customer', label: __('Customer Link'), fieldtype: 'Link', options: 'Customer' },
				{ fieldname: 'evidence', label: __('Allocation Evidence'), fieldtype: 'Link', options: 'Fresko Evidence', reqd: 1 },
				{ fieldname: 'supersedes', label: __('Supersedes Allocation (Optional)'), fieldtype: 'Link', options: 'Fresko Payment Allocation' },
				{ fieldname: 'reason', label: __('Replacement Reason (If superseding)'), fieldtype: 'Small Text' }
			],
			primary_action_label: __('Propose Allocation'),
			primary_action: function(v) {
				v.source_event_id = d.fresko_event_id;
				me.call_api('fresko_universe.money.propose_payment_allocation', v, function() {
					d.hide();
					frappe.show_alert({ message: __('Allocation proposed'), indicator: 'green' });
					me.refresh_all();
				});
			}
		});
		d.fresko_event_id = crypto.randomUUID();
		d.show();
	},

	show_propose_adjustment_dialog: function() {
		var me = this;
		var d = new frappe.ui.Dialog({
			title: __('Propose Receivable Non-Cash Adjustment'),
			fields: [
				{ fieldname: 'customer', label: __('Customer'), fieldtype: 'Link', options: 'Customer', reqd: 1 },
				{ fieldname: 'adjustment_type', label: __('Adjustment Type'), fieldtype: 'Select', options: ['UNCLASSIFIED', 'DISCOUNT', 'COMMISSION_SETOFF', 'CUSTOMER_PAID_EXPENSE_SETOFF'], reqd: 1 },
				{ fieldname: 'agreement_reference', label: __('Discharge Agreement Reference'), fieldtype: 'Data', reqd: 1 },
				{ fieldname: 'amount', label: __('Amount (Decimal Text)'), fieldtype: 'Data', reqd: 1 },
				{ fieldname: 'currency', label: __('Currency'), fieldtype: 'Data', default: 'INR', reqd: 1 },
				{ fieldname: 'evidence', label: __('Signed Agreement / Evidence'), fieldtype: 'Link', options: 'Fresko Evidence', reqd: 1 }
			],
			primary_action_label: __('Propose Adjustment'),
			primary_action: function(v) {
				v.company = me.get_company();
				v.source_event_id = d.fresko_event_id;
				me.call_api('fresko_universe.money.propose_adjustment', v, function() {
					d.hide();
					frappe.show_alert({ message: __('Adjustment proposed'), indicator: 'green' });
					me.refresh_all();
				});
			}
		});
		d.fresko_event_id = crypto.randomUUID();
		d.show();
	},

	show_propose_application_dialog: function() {
		var me = this;
		var d = new frappe.ui.Dialog({
			title: __('Propose Adjustment Application to Sale'),
			fields: [
				{ fieldname: 'receivable_adjustment', label: __('Approved Receivable Adjustment'), fieldtype: 'Link', options: 'Fresko Receivable Adjustment', reqd: 1 },
				{ fieldname: 'sale', label: __('Sale ID'), fieldtype: 'Link', options: 'Fresko Commercial Sale', reqd: 1 },
				{ fieldname: 'amount', label: __('Amount (Decimal Text)'), fieldtype: 'Data', reqd: 1 },
				{ fieldname: 'currency', label: __('Currency'), fieldtype: 'Data', default: 'INR', reqd: 1 },
				{ fieldname: 'evidence', label: __('Discharge Application Evidence'), fieldtype: 'Link', options: 'Fresko Evidence', reqd: 1 }
			],
			primary_action_label: __('Propose Application'),
			primary_action: function(v) {
				v.source_event_id = d.fresko_event_id;
				me.call_api('fresko_universe.money.propose_adjustment_application', v, function() {
					d.hide();
					frappe.show_alert({ message: __('Application proposed'), indicator: 'green' });
					me.refresh_all();
				});
			}
		});
		d.fresko_event_id = crypto.randomUUID();
		d.show();
	},

	query_receivables: function() {
		var me = this;
		var comp = me.get_company();
		var cutoff = me.get_cutoff();
		var cust = $('#rec-customer').val().trim();
		var sale = $('#rec-sale').val().trim();
		var cont = me.get_container();
		var $res = $('#fm-receivable-result');
		$res.empty();

		if (sale) {
			me.call_api('fresko_universe.money.get_sale_receivable', { sale: sale, as_of: cutoff }, function(sr) {
				me.render_sale_position($res, sr);
			});
		} else if (cont) {
			me.call_api('fresko_universe.money.get_container_receivable', { container: cont, as_of: cutoff }, function(cr) {
				me.render_container_position($res, cr);
			});
		} else if (cust) {
			me.call_api('fresko_universe.money.get_customer_receivable', { customer: cust, company: comp, as_of: cutoff }, function(cpos) {
				me.render_customer_position($res, cpos);
			});
		} else {
			frappe.msgprint(__('Specify a Sale ID, Container, or Customer.'));
		}
	},

	render_sale_position: function($target, sr) {
		if (!sr || !sr.exists) {
			$target.html('<div class="text-muted">' + __('Sale debt position does not exist or superseded.') + '</div>');
			return;
		}
		var safe_sale = frappe.utils.escape_html(sr.sale);
		var safe_link = '<a href="/app/fresko-commercial-sale/' + encodeURIComponent(sr.sale) + '">' + safe_sale + '</a>';
		var out = sr.outstanding_receivable === null ? '<span class="text-warning font-weight-bold">PENDING (Unsettled lines)</span>' : frappe.utils.escape_html(sr.currency + ' ' + sr.outstanding_receivable);

		var card = [
			'<div class="fm-pos-card">',
			'  <h4>' + __('Sale: ') + safe_link + ' <span class="badge badge-info">' + frappe.utils.escape_html(sr.settlement_status) + '</span></h4>',
			'  <p><strong>' + __('Customer: ') + '</strong>' + frappe.utils.escape_html(sr.customer || '-') + '</p>',
			'  <p><strong>' + __('Gross Commercial Amount: ') + '</strong>' + frappe.utils.escape_html(sr.gross_commercial_amount === null ? 'PENDING' : (sr.currency + ' ' + sr.gross_commercial_amount)) + '</p>',
			'  <p><strong>' + __('Cash Applied: ') + '</strong>' + frappe.utils.escape_html(sr.currency + ' ' + sr.cash_applied_amount) + '</p>',
			'  <p><strong>' + __('Adjustment Applied: ') + '</strong>' + frappe.utils.escape_html(sr.currency + ' ' + sr.adjustment_applied_amount) + '</p>',
			'  <p><strong>' + __('Authoritative Outstanding Receivable: ') + '</strong>' + out + '</p>',
			'</div>'
		].join('');
		$target.html(card);
	},

	render_container_position: function($target, cr) {
		var safe_cont = frappe.utils.escape_html(cr.container);
		var cur_str = Object.keys(cr.outstanding_receivable_by_currency || {}).map(function(c) {
			var v = cr.outstanding_receivable_by_currency[c];
			return frappe.utils.escape_html(c) + ': ' + (v === null ? 'PENDING (Unresolved sales: ' + (cr.unresolved_pricing_sales_count || 0) + ')' : frappe.utils.escape_html(v));
		}).join(', ') || '-';

		var parked_str = Object.keys(cr.container_parked_by_currency || {}).map(function(c) {
			return frappe.utils.escape_html(c) + ': ' + frappe.utils.escape_html(cr.container_parked_by_currency[c]);
		}).join(', ') || '0.00';

		var card = [
			'<div class="fm-pos-card">',
			'  <h4>' + __('Container: ') + '<a href="/app/fresko-container/' + encodeURIComponent(cr.container) + '">' + safe_cont + '</a></h4>',
			'  <p><strong>' + __('Sales Count: ') + '</strong>' + cr.sales_count + '</p>',
			'  <p><strong>' + __('Outstanding Debt by Currency: ') + '</strong>' + cur_str + '</p>',
			'  <p><strong>' + __('Parked Unapplied by Currency: ') + '</strong>' + parked_str + ' <span class="text-muted">(' + __('no debt discharge') + ')</span></p>',
			'</div>'
		].join('');
		$target.html(card);
	},

	render_customer_position: function($target, cpos) {
		var safe_cust = frappe.utils.escape_html(cpos.customer);
		var cur_str = Object.keys(cpos.outstanding_receivable_by_currency || {}).map(function(c) {
			var v = cpos.outstanding_receivable_by_currency[c];
			return frappe.utils.escape_html(c) + ': ' + (v === null ? 'PENDING' : frappe.utils.escape_html(v));
		}).join(', ') || '-';

		var card = [
			'<div class="fm-pos-card">',
			'  <h4>' + __('Customer: ') + '<a href="/app/customer/' + encodeURIComponent(cpos.customer) + '">' + safe_cust + '</a></h4>',
			'  <p><strong>' + __('Authoritative Outstanding: ') + '</strong>' + cur_str + '</p>',
			'</div>'
		].join('');
		$target.html(card);
	}
};
