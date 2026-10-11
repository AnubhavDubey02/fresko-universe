/* Fresko Operations Workspace - Native Frappe Desk Page */

frappe.pages['fresko-workspace'].on_page_load = function(wrapper) {
    page_on_page_load(wrapper);
};

function page_on_page_load(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __('Fresko'),
        single_column: true
    });
    wrapper.fresko_workspace = new FreskoWorkspace(wrapper, page);
}

function escape_html(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function create_dom_element(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
        for (var key in attrs) {
            if (Object.prototype.hasOwnProperty.call(attrs, key)) {
                var val = attrs[key];
                if (key === 'className' || key === 'class') {
                    el.className = val;
                } else if (key === 'style' && typeof val === 'object') {
                    Object.assign(el.style, val);
                } else if (key.indexOf('on') === 0 && typeof val === 'function') {
                    el.addEventListener(key.slice(2).toLowerCase(), val);
                } else if (key === 'disabled' || typeof val === 'boolean') {
                    if (val) {
                        el.setAttribute(key, key === 'disabled' ? 'disabled' : '');
                        el[key] = true;
                    } else {
                        if (typeof el.removeAttribute === 'function') {
                            el.removeAttribute(key);
                        }
                        el[key] = false;
                    }
                } else if (val !== null && val !== undefined) {
                    el.setAttribute(key, val);
                }
            }
        }
    }
    if (children) {
        if (!Array.isArray(children)) children = [children];
        for (var i = 0; i < children.length; i++) {
            var child = children[i];
            if (child === null || child === undefined) continue;
            if (typeof child === 'string' || typeof child === 'number') {
                el.appendChild(document.createTextNode(String(child)));
            } else if ((typeof Node !== 'undefined' && child instanceof Node) || (child && child.tagName)) {
                el.appendChild(child);
            }
        }
    }
    return el;
}

function render_raw_alias_node(raw_alias) {
    var span = document.createElement('span');
    span.className = 'fresko-raw-alias';
    span.textContent = (raw_alias !== null && raw_alias !== undefined) ? raw_alias : '—';
    return span;
}

function render_evidence_link_node(evidence_name) {
    if (!evidence_name) {
        var span = document.createElement('span');
        span.className = 'text-muted';
        span.textContent = 'None';
        return span;
    }
    var a = document.createElement('a');
    a.href = '/app/fresko-evidence/' + encodeURIComponent(evidence_name);
    a.className = 'fresko-link font-weight-bold';
    a.target = '_blank';
    a.textContent = evidence_name;
    return a;
}

function render_badge_node(status, custom_class) {
    var span = document.createElement('span');
    var text = String(status || 'UNKNOWN').toUpperCase();
    var cls = 'fresko-badge';
    if (custom_class) {
        cls += ' ' + custom_class;
    } else {
        var lower = text.toLowerCase().replace(/\s+/g, '_');
        cls += ' fresko-badge-' + lower;
    }
    span.className = cls;
    span.textContent = text;
    return span;
}

function format_financial_amount(amount, currency) {
    if (amount === null || amount === undefined || amount === '') {
        return 'PENDING / UNKNOWN';
    }
    var curr = currency ? currency + ' ' : '';
    return curr + amount;
}

function format_qty(qty, uom) {
    if (qty === null || qty === undefined || qty === '') {
        return 'UNKNOWN';
    }
    var unit = uom ? ' ' + uom : '';
    return qty + unit;
}

function generate_uuid() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function is_valid_decimal_string(val, max_decimals) {
    if (typeof val !== 'string') return false;
    val = val.trim();
    if (!val) return false;
    var regex = max_decimals ? new RegExp('^\\d+(\\.\\d{1,' + max_decimals + '})?$') : /^\d+(\.\d+)?$/;
    return regex.test(val);
}

function is_positive_decimal_string(val, max_decimals) {
    if (!is_valid_decimal_string(val, max_decimals)) return false;
    val = val.trim();
    return !/^0+(\.0+)?$/.test(val);
}

class FreskoWorkspace {
    constructor(wrapper, page) {
        this.wrapper = wrapper;
        this.page = page;
        this.container_name = null;
        this.as_of_value = null;
        this.user_context = {
            is_internal: false,
            can_verify: false,
            can_approve: false,
            roles: []
        };
        this.current_load_seq = 0;
        this.active_tab = 'inbox';
        this.container_data = null;
        this.selected_sale = null;
        this.selected_outward_name = null;
        this.selected_outward_data = null;
        this.alias_mappings = [];

        this.init();
    }

    init() {
        var self = this;
        frappe.call({
            method: 'fresko_universe.fresko_core.page.fresko_workspace.fresko_workspace.get_user_workspace_context'
        }).then(function(r) {
            if (r && r.message) {
                self.user_context = r.message;
            }
            // Canonical role authorization: UI may prepare only Fresko Salesperson, not SM just because technical visible
            self.user_context.can_prepare = Boolean(
                self.user_context &&
                Array.isArray(self.user_context.roles) &&
                self.user_context.roles.indexOf('Fresko Salesperson') !== -1
            );
            self.setup_ui();
        }).catch(function(err) {
            self.render_fatal_error(__('Access Denied: You do not have permissions for Fresko Workspace.'));
        });
    }

    setup_ui() {
        var self = this;
        this.page.clear_fields();
        this.page.clear_actions();

        // Container selector
        this.container_field = this.page.add_field({
            fieldname: 'container',
            fieldtype: 'Link',
            options: 'Fresko Container',
            label: __('Container'),
            change: function() {
                var val = self.container_field.get_value();
                if (val !== self.container_name) {
                    self.container_name = val;
                    if (!self._preserve_selection) {
                        self.selected_sale = null;
                        self.selected_outward_name = null;
                        self.selected_outward_data = null;
                    }
                    if (val && self.active_tab === 'inbox') {
                        self.active_tab = 'overview';
                    }
                    self.load_container_data();
                }
            }
        });

        // As-Of selector
        this.as_of_field = this.page.add_field({
            fieldname: 'as_of',
            fieldtype: 'Datetime',
            label: __('As Of (blank = Live)'),
            default: null,
            change: function() {
                self.as_of_value = self.as_of_field.get_value();
                self.selected_sale = null;
                self.selected_outward_name = null;
                self.selected_outward_data = null;
                self.update_view_actions();
                if (self.active_tab === 'inbox') {
                    self.render_inbox_panel();
                } else {
                    self.load_container_data();
                }
            }
        });
        this.as_of_value = this.as_of_field.get_value();

        // Primary & Action buttons
        this.page.set_primary_action(__('Refresh'), function() {
            if (self.active_tab === 'inbox') {
                self.render_inbox_panel();
            } else {
                self.load_container_data();
            }
        }, 'octicon octicon-sync');

        if (this.user_context.can_prepare) {
            this.new_sale_button = this.page.add_inner_button(__('New Sale'), function() {
                self.open_sale_preparation_dialog();
            });
        }

        if ((this.user_context.roles || []).some(function(r) { return r === 'Fresko Accounts' || r === 'Fresko Approver'; })) {
            this.page.add_inner_button(__('Money'), function() { frappe.set_route('fresko-money'); });
        }

        this.propose_alias_button = this.page.add_inner_button(__('Propose Alias'), function() {
            self.open_propose_alias_dialog();
        });

        // Main DOM container
        this.root_dom = create_dom_element('div', { class: 'fresko-workspace-container' });
        this.page.main.append(this.root_dom); // Preserve the native Page filter form.

        this.render_skeleton();

        // Auto-select container if passed in route
        var route = frappe.get_route();
        if (route && route[2]) {
            this.container_field.set_value(route[2]);
        }
    }

    render_skeleton() {
        var self = this;
        this.root_dom.innerHTML = '';

        // Header Status Banner
        this.header_banner = create_dom_element('div', { class: 'fresko-header-card' });
        this.root_dom.appendChild(this.header_banner);

        // Tabs
        this.tabs_bar = create_dom_element('div', { class: 'fresko-nav-tabs' });
        var tabs = [
            { id: 'inbox', label: __('Needs My Action') },
            { id: 'overview', label: __('Container Overview') },
            { id: 'sales', label: __('Sales') },
            { id: 'outwards', label: __('Outwards') },
            { id: 'alias', label: __('Alias Review Queue') }
        ];
        tabs.forEach(function(tab) {
            var btn = create_dom_element('button', {
                class: 'fresko-tab-btn' + (self.active_tab === tab.id ? ' active' : ''),
                type: 'button',
                onClick: function() {
                    self.switch_tab(tab.id);
                }
            }, [tab.label]);
            btn.dataset.tabId = tab.id;
            self.tabs_bar.appendChild(btn);
        });
        this.root_dom.appendChild(this.tabs_bar);

        // Content Panel
        this.content_panel = create_dom_element('div', { class: 'fresko-content-panel' });
        this.root_dom.appendChild(this.content_panel);

        this.update_header_banner();
        if (this.active_tab === 'inbox') {
            this.render_inbox_panel();
        } else {
            this.render_empty_state(__('Select a Container to inspect reconciliation projections.'));
        }
    }

    is_live_view() {
        return !this.as_of_value && (!this.container_data || this.container_data.projection_mode === 'LIVE');
    }

    require_live_view() {
        if (this.is_live_view()) return true;
        frappe.msgprint(__('Historical views are read-only. Clear As Of to work in Live view.'));
        return false;
    }

    require_mutation(record, token_field = 'version') {
        if (!this.require_live_view()) return false;
        if (token_field === 'current_version' && record.projection_mode !== 'LIVE') {
            frappe.msgprint(__('Reload the current Sale before taking an action.'));
            return false;
        }
        var token = record[token_field];
        if (!Number.isSafeInteger(Number(token)) || !/^[1-9][0-9]*$/.test(String(token))) {
            frappe.msgprint(__('A current version is required. Refresh this record.'));
            return false;
        }
        return true;
    }

    update_view_actions() {
        var disabled = !this.is_live_view();
        if (this.new_sale_button) this.new_sale_button.prop('disabled', disabled);
        if (this.propose_alias_button) this.propose_alias_button.prop('disabled', disabled);
    }

    update_header_banner() {
        this.header_banner.innerHTML = '';
        var title_group = create_dom_element('div', {}, [
            create_dom_element('h2', { class: 'fresko-header-title' }, [__('Fresko Commercial Operations')]),
            create_dom_element('div', { class: 'text-muted small' }, [
                this.container_name ? ('Container: ' + this.container_name) : __('No Container Selected')
            ])
        ]);

        var meta_group = create_dom_element('div', { class: 'fresko-header-meta' });
        var as_of_text = this.is_live_view() ? __('LIVE') : (this.as_of_value || __('Historical'));
        this.update_view_actions();
        meta_group.appendChild(create_dom_element('div', { class: 'fresko-meta-item' }, [
            'As-Of: ',
            create_dom_element('strong', {}, [as_of_text])
        ]));

        var scope_text = this.container_data && this.container_data.view_scope ? this.container_data.view_scope : (this.user_context.is_internal ? 'INTERNAL' : 'ASSIGNED');
        meta_group.appendChild(create_dom_element('div', { class: 'fresko-meta-item' }, [
            'Scope: ',
            create_dom_element('strong', {}, [scope_text])
        ]));

        var state_text = this.container_data && this.container_data.reconciliation_state ? this.container_data.reconciliation_state : 'PENDING';
        meta_group.appendChild(render_badge_node(state_text));

        this.header_banner.appendChild(title_group);
        this.header_banner.appendChild(meta_group);
    }

    switch_tab(tab_id) {
        this.active_tab = tab_id;
        var buttons = this.tabs_bar.querySelectorAll('.fresko-tab-btn');
        buttons.forEach(function(b) {
            if (b.dataset.tabId === tab_id) {
                b.classList.add('active');
            } else {
                b.classList.remove('active');
            }
        });
        this.render_active_tab();
    }

    load_container_data() {
        var self = this;
        var seq = ++this.current_load_seq;
        if (!this.container_name) {
            this.container_data = null;
            this.selected_sale = null;
            this.selected_outward_name = null;
            this.selected_outward_data = null;
            this.update_header_banner();
            this.render_empty_state(__('Select a Container to inspect reconciliation projections.'));
            return;
        }

        this.render_loading(__('Loading commercial reconciliation projections...'));

        frappe.call({
            method: 'fresko_universe.commercial.get_container_reconciliation',
            args: {
                container: this.container_name,
                as_of: this.as_of_value || null
            }
        }).then(function(r) {
            if (seq !== self.current_load_seq) {
                return; // Guard against asynchronous stale responses
            }
            self.container_data = r.message || null;
            if (self.selected_sale) {
                var selected_name = self.selected_sale.name;
                self.selected_sale = ((self.container_data || {}).sales || []).find(function(row) { return row.name === selected_name; }) || null;
            }
            self.update_header_banner();
            self.render_active_tab();
        }).catch(function(err) {
            if (seq !== self.current_load_seq) return;
            self.render_error(__('Failed to load container reconciliation: ') + (err.message || 'Error'));
        });
    }

    render_active_tab() {
        if (this.active_tab === 'inbox') {
            this.render_inbox_panel();
            return;
        }

        if (!this.container_data && this.active_tab !== 'alias') {
            this.render_empty_state(__('Select a Container to view data.'));
            return;
        }

        this.content_panel.innerHTML = '';
        if (this.active_tab === 'overview') {
            this.render_overview_panel();
        } else if (this.active_tab === 'sales') {
            this.render_sales_panel();
        } else if (this.active_tab === 'outwards') {
            this.render_outwards_panel();
        } else if (this.active_tab === 'alias') {
            this.render_alias_panel();
        }
    }

    render_inbox_panel() {
        var self = this;
        this.content_panel.innerHTML = '';
        var wrap = create_dom_element('div', { class: 'fresko-inbox-split-view' });
        var left = create_dom_element('div', { class: 'fresko-inbox-feed-col' });
        var right = create_dom_element('div', { class: 'fresko-inbox-detail-col' });
        wrap.appendChild(left);
        wrap.appendChild(right);
        this.content_panel.appendChild(wrap);

        if (!this.is_live_view() || this.as_of_value) {
            left.appendChild(create_dom_element('div', { class: 'fresko-state-container' }, [
                create_dom_element('div', { class: 'fresko-state-title' }, [__('Needs My Action is Live-Only')]),
                create_dom_element('div', { class: 'text-muted', style: { marginBottom: '12px' } }, [
                    __('Pending action items reflect the live operational queue and are not available in historical view.')
                ]),
                create_dom_element('button', {
                    class: 'btn btn-sm btn-primary',
                    onClick: function() {
                        self.as_of_value = null;
                        if (self.as_of_field && typeof self.as_of_field.set_value === 'function') {
                            self.as_of_field.set_value('');
                        }
                        self.render_inbox_panel();
                    }
                }, [__('Return to Live')])
            ]));
            right.appendChild(create_dom_element('div', { class: 'fresko-detail-placeholder' }, [
                __('Historical projection active. Switch to live view to inspect and execute pending actions.')
            ]));
            return;
        }

        left.appendChild(create_dom_element('div', { class: 'fresko-state-container' }, [
            create_dom_element('div', { class: 'text-muted' }, [__('Loading action feed...')])
        ]));
        right.appendChild(create_dom_element('div', { class: 'fresko-detail-placeholder' }, [
            __('Select an action item to review contextual details and evidence.')
        ]));

        frappe.call({
            method: 'fresko_universe.fresko_core.services.operator_service.get_operator_action_feed',
            args: {
                as_of: null
            }
        }).then(function(r) {
            if (!r || !r.message) {
                left.innerHTML = '';
                left.appendChild(create_dom_element('div', { class: 'fresko-state-container' }, [
                    create_dom_element('div', { class: 'text-muted' }, [__('No actionable items.')])
                ]));
                return;
            }
            self.render_inbox_feed(r.message, left, right);
        }).catch(function(err) {
            left.innerHTML = '';
            left.appendChild(create_dom_element('div', { class: 'fresko-state-container' }, [
                create_dom_element('div', { class: 'text-danger' }, [__('Failed to load action feed: ') + (err.message || 'Error')])
            ]));
        });
    }

    render_inbox_feed(feed, leftCol, rightCol) {
        var self = this;
        leftCol.innerHTML = '';
        var sections = feed.sections || [];
        var total = feed.counts ? feed.counts.total_actionable : 0;
        if (sections.length === 0 || total === 0) {
            leftCol.appendChild(create_dom_element('div', { class: 'fresko-state-container' }, [
                create_dom_element('div', { class: 'fresko-state-title' }, [__('All Clear')]),
                create_dom_element('div', { class: 'text-muted' }, [__('No pending items require your action right now.')])
            ]));
            return;
        }

        var selected_card_el = null;
        var first_card_el = null;
        var first_item = null;

        sections.forEach(function(section) {
            var sec_dom = create_dom_element('div', { class: 'fresko-action-section' });
            var heading = create_dom_element('div', { class: 'fresko-action-section-title' }, [
                section.title,
                create_dom_element('span', { class: 'badge badge-pill badge-secondary' }, [String(section.count)])
            ]);
            sec_dom.appendChild(heading);

            (section.items || []).forEach(function(item) {
                var card = create_dom_element('div', {
                    class: 'fresko-action-card',
                    role: 'button',
                    tabindex: '0'
                });
                var header = create_dom_element('div', { class: 'fresko-action-card-header' }, [
                    create_dom_element('span', { class: 'fresko-action-card-title' }, [item.human_title]),
                    render_badge_node(item.state)
                ]);
                var sub = create_dom_element('div', { class: 'fresko-action-card-sub' }, [item.subtitle || '—']);
                var footer = create_dom_element('div', { class: 'fresko-action-card-footer' }, [
                    create_dom_element('span', { class: 'text-muted' }, [item.state_reason || '—']),
                    create_dom_element('strong', {}, [item.amount_string || '—'])
                ]);
                card.appendChild(header);
                card.appendChild(sub);
                card.appendChild(footer);

                var select_card = function() {
                    if (selected_card_el) {
                        if (selected_card_el.classList) selected_card_el.classList.remove('selected');
                        else selected_card_el.className = (selected_card_el.className || '').replace(/\bselected\b/, '').trim();
                    }
                    if (card.classList) card.classList.add('selected');
                    else card.className = ((card.className || '') + ' selected').trim();
                    selected_card_el = card;
                    self.render_inbox_detail_pane(item, rightCol);
                };

                card.addEventListener('click', select_card);
                card.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ' || e.keyCode === 13 || e.keyCode === 32) {
                        e.preventDefault();
                        select_card();
                    }
                });

                if (!first_card_el) {
                    first_card_el = card;
                    first_item = item;
                }

                sec_dom.appendChild(card);
            });

            leftCol.appendChild(sec_dom);
        });

        // Select first item by default if present
        if (first_card_el && first_item) {
            if (first_card_el.classList) first_card_el.classList.add('selected');
            else first_card_el.className = ((first_card_el.className || '') + ' selected').trim();
            selected_card_el = first_card_el;
            self.render_inbox_detail_pane(first_item, rightCol);
        }
    }

    render_inbox_detail_pane(item, rightCol) {
        var self = this;
        rightCol.innerHTML = '';
        var panel = create_dom_element('div', { class: 'fresko-detail-panel' });

        var title = create_dom_element('h4', { class: 'fresko-card-title' }, [
            item.human_title,
            create_dom_element('code', { style: { fontSize: '12px' } }, [item.doc_ref])
        ]);
        panel.appendChild(title);

        var table = create_dom_element('table', { class: 'fresko-table', style: { marginBottom: '16px' } });
        var rows = [
            [__('Document Ref'), item.doc_ref],
            [__('Status'), item.state],
            [__('Reason'), item.state_reason],
            [__('Amount'), item.amount_string],
            [__('Quantity'), item.qty_string],
            [__('Projection'), item.projection_mode || 'LIVE']
        ];
        rows.forEach(function(r) {
            var tr = create_dom_element('tr', {}, [
                create_dom_element('td', { style: { fontWeight: '600', width: '35%' } }, [r[0]]),
                create_dom_element('td', {}, [String(r[1] || '—')])
            ]);
            table.appendChild(tr);
        });
        panel.appendChild(table);

        // Actions
        var actions_wrap = create_dom_element('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' } });
        if (item.actions && item.actions.length > 0) {
            item.actions.forEach(function(act) {
                var btn = create_dom_element('button', {
                    class: 'btn btn-sm ' + (act.allowed ? 'btn-primary' : 'btn-secondary'),
                    type: 'button',
                    disabled: !act.allowed
                }, [act.label]);

                if (!act.allowed && act.blocked_reason) {
                    btn.title = act.blocked_reason;
                }

                if (act.allowed) {
                    btn.addEventListener('click', function() {
                        self.execute_inbox_action(item, act);
                    });
                }
                actions_wrap.appendChild(btn);
            });
        }
        panel.appendChild(actions_wrap);

        // Evidence Inspector Section
        var ev_section = create_dom_element('div', { class: 'fresko-extension-box', style: { marginTop: '16px' } });
        ev_section.appendChild(create_dom_element('strong', {}, [__('Contextual Evidence')]));
        if (item.evidence_name) {
            ev_section.appendChild(create_dom_element('div', { style: { marginTop: '8px' } }, [
                create_dom_element('span', { class: 'text-muted' }, [__('Linked Evidence: ')]),
                render_evidence_link_node(item.evidence_name)
            ]));
        } else {
            ev_section.appendChild(create_dom_element('div', { class: 'text-muted', style: { marginTop: '8px' } }, [
                item.evidence_state === 'RESTRICTED' ? __('Evidence Restricted by Access Policy') : __('No Evidence Attached')
            ]));
        }
        panel.appendChild(ev_section);

        rightCol.appendChild(panel);
    }

    execute_inbox_action(item, action) {
        var self = this;
        if (action.action === 'propose_rate' || action.action === 'verify_sale' || action.action === 'approve_sale') {
            if (item.container) {
                this.selected_sale = { name: item.document_name, container: item.container };
                this._preserve_selection = true;
                if (this.container_field && typeof this.container_field.set_value === 'function') {
                    this.container_field.set_value(item.container);
                }
                this._preserve_selection = false;
                this.selected_sale = { name: item.document_name, container: item.container };
                this.switch_tab('sales');
            }
        } else if (action.action === 'propose_commercial_allocation') {
            if (item.container && this.container_field && typeof this.container_field.set_value === 'function') {
                this.container_field.set_value(item.container);
            }
            this.selected_outward_name = item.document_name || item.doc_ref;
            this.switch_tab('outwards');
            if (this.selected_outward_name) {
                this.inspect_outward(this.selected_outward_name);
            }
        } else if (action.action === 'verify_sale_outward_allocation' || action.action === 'approve_sale_outward_allocation') {
            frappe.call({
                method: 'frappe.client.get',
                args: {
                    doctype: 'Fresko Sale Outward Allocation',
                    name: item.document_name || item.doc_ref
                }
            }).then(function(r) {
                var alloc = r.message;
                if (!alloc) {
                    frappe.msgprint(__('Allocation record not found.'));
                    return;
                }
                if (action.action === 'approve_sale_outward_allocation') {
                    if (alloc.status !== 'PROPOSED') {
                        frappe.msgprint(__('Allocation status has changed to ') + alloc.status);
                        self.render_inbox_panel();
                        return;
                    }
                    self.approve_allocation(alloc);
                } else if (action.action === 'verify_sale_outward_allocation') {
                    self.verify_allocation(alloc);
                }
            }).catch(function(err) {
                frappe.msgprint(__('Error fetching allocation: ') + (err.message || 'Error'));
            });
        } else if (action.action === 'verify_collection' || action.action === 'approve_collection' || action.action === 'verify_payment_allocation' || action.action === 'approve_payment_allocation') {
            try {
                sessionStorage.setItem('fresko_money_target', JSON.stringify({
                    doctype: action.action.endsWith('payment_allocation') ? 'Fresko Payment Allocation' : 'Fresko Collection',
                    document_name: item.document_name,
                    action: action.action
                }));
            } catch(e) {}
            frappe.set_route('fresko-money');
        } else if (action.action === 'verify_alias' || action.action === 'approve_alias' || action.action === 'propose_alias') {
            this.switch_tab('alias');
        }
    }

    // -----------------------------------------------------
    // Panel 1: Overview
    // -----------------------------------------------------
    render_overview_panel() {
        this.content_panel.innerHTML = '';
        var data = this.container_data;
        var self = this;
        var container_dom = create_dom_element('div', {});

        // Exceptions banner
        if (data.exceptions && data.exceptions.length > 0) {
            var exc_card = create_dom_element('div', { class: 'fresko-section-card', style: { borderColor: '#fad2cf', background: '#fff9f9' } });
            exc_card.appendChild(create_dom_element('h4', { class: 'fresko-card-title', style: { color: '#c5221f' } }, [__('Reconciliation Exceptions & Unresolved States')]));
            var badge_wrap = create_dom_element('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' } });
            data.exceptions.forEach(function(exc) {
                badge_wrap.appendChild(render_badge_node(exc, 'fresko-badge-exception'));
            });
            exc_card.appendChild(badge_wrap);

            var counts_grid = create_dom_element('div', { class: 'fresko-grid-2' }, [
                create_dom_element('div', { class: 'fresko-summary-box' }, [
                    create_dom_element('div', { class: 'fresko-summary-label' }, [__('Unknown Quantity Lines')]),
                    create_dom_element('div', { class: 'fresko-summary-value' }, [String(data.unknown_quantity_count || 0)])
                ]),
                create_dom_element('div', { class: 'fresko-summary-box' }, [
                    create_dom_element('div', { class: 'fresko-summary-label' }, [__('Unresolved Buyer Sales')]),
                    create_dom_element('div', { class: 'fresko-summary-value' }, [String(data.unresolved_buyer_count || 0)])
                ]),
                create_dom_element('div', { class: 'fresko-summary-box' }, [
                    create_dom_element('div', { class: 'fresko-summary-label' }, [__('Pending Sales Count')]),
                    create_dom_element('div', { class: 'fresko-summary-value' }, [String(data.pending_sale_count || 0)])
                ])
            ]);
            exc_card.appendChild(counts_grid);
            container_dom.appendChild(exc_card);
        }

        // Quantities by UOM Card
        var uom_card = create_dom_element('div', { class: 'fresko-section-card' });
        uom_card.appendChild(create_dom_element('h3', { class: 'fresko-card-title' }, [__('Physical & Commercial Quantities by UOM')]));

        var totals = data.totals_by_uom || {};
        var uoms = Object.keys(totals);
        if (uoms.length === 0) {
            uom_card.appendChild(create_dom_element('div', { class: 'text-muted' }, [__('No quantities recorded for this container.')]));
        } else {
            var table_wrap = create_dom_element('div', { class: 'fresko-table-responsive' });
            var table = create_dom_element('table', { class: 'fresko-table' });
            var thead = create_dom_element('thead', {}, [
                create_dom_element('tr', {}, [
                    create_dom_element('th', {}, [__('UOM')]),
                    create_dom_element('th', {}, [__('Physical Qty')]),
                    create_dom_element('th', {}, [__('Sold Qty')]),
                    create_dom_element('th', {}, [__('Allocated Qty')]),
                    create_dom_element('th', {}, [__('Physically Unallocated')]),
                    create_dom_element('th', {}, [__('Sold Not Allocated')]),
                    create_dom_element('th', {}, [__('Priced Qty')]),
                    create_dom_element('th', {}, [__('Unpriced Qty')])
                ])
            ]);
            var tbody = create_dom_element('tbody');
            uoms.forEach(function(uom) {
                var g = totals[uom] || {};
                var tr = create_dom_element('tr', {}, [
                    create_dom_element('td', {}, [create_dom_element('strong', {}, [uom])]),
                    create_dom_element('td', {}, [g.physical_qty || '0']),
                    create_dom_element('td', {}, [g.commercially_sold_qty || '0']),
                    create_dom_element('td', {}, [g.physically_allocated_qty || '0']),
                    create_dom_element('td', {}, [g.physically_unallocated_qty || '0']),
                    create_dom_element('td', {}, [g.sold_not_physically_allocated_qty || '0']),
                    create_dom_element('td', {}, [g.priced_qty || '0']),
                    create_dom_element('td', {}, [g.unpriced_qty || '0'])
                ]);
                tbody.appendChild(tr);
            });
            table.appendChild(thead);
            table.appendChild(tbody);
            table_wrap.appendChild(table);
            uom_card.appendChild(table_wrap);
        }
        container_dom.appendChild(uom_card);

        // Confirmed Value by Currency Card
        var val_card = create_dom_element('div', { class: 'fresko-section-card' });
        val_card.appendChild(create_dom_element('h3', { class: 'fresko-card-title' }, [__('Confirmed Commercial Value (Deterministic Backend Projections)')]));
        var vals = data.confirmed_value_by_currency || {};
        var currs = Object.keys(vals);
        if (currs.length === 0) {
            val_card.appendChild(create_dom_element('div', { class: 'text-muted' }, [__('No fully confirmed commercial sales for this container as of cutoff.')]));
        } else {
            var grid = create_dom_element('div', { class: 'fresko-grid-2' });
            currs.forEach(function(curr) {
                grid.appendChild(create_dom_element('div', { class: 'fresko-summary-box' }, [
                    create_dom_element('div', { class: 'fresko-summary-label' }, [curr]),
                    create_dom_element('div', { class: 'fresko-summary-value' }, [curr + ' ' + vals[curr]])
                ]));
            });
            val_card.appendChild(grid);
        }
        container_dom.appendChild(val_card);

        // Money Extension Point Box
        var ext_box = create_dom_element('div', { class: 'fresko-extension-box' }, [
            create_dom_element('strong', {}, [__('Extension Point: Money Reconciliation')]),
            create_dom_element('div', {}, [__('Financial settlements, banking transactions, and accounting balance reconciliation interfaces are reserved here. Concrete fields will be integrated upon settled money contract. Client-side financial arithmetic is prohibited.')])
        ]);
        container_dom.appendChild(ext_box);

        this.content_panel.appendChild(container_dom);
    }

    // -----------------------------------------------------
    // Panel 2: Sales
    // -----------------------------------------------------
    render_sales_panel() {
        this.content_panel.innerHTML = '';
        var self = this;
        var sales = (this.container_data && this.container_data.sales) ? this.container_data.sales : [];
        var layout = create_dom_element('div', {});

        var card = create_dom_element('div', { class: 'fresko-section-card' });
        var head_children = [create_dom_element('span', {}, [__('Commercial Sales (As-Of Reconciled)')])];
        if (this.user_context.can_prepare) {
            var prep_attrs = {
                class: 'fresko-btn-sm fresko-btn-primary'
            };
            if (!this.is_live_view() || this.as_of_value) {
                prep_attrs.disabled = 'disabled';
                prep_attrs.title = __('Preparing sales is only permitted in live view');
            } else {
                prep_attrs.onClick = function() { self.open_sale_preparation_dialog(); };
            }
            head_children.push(create_dom_element('button', prep_attrs, [__('+ Prepare Sale')]));
        }
        var head_row = create_dom_element('div', { class: 'fresko-card-title' }, head_children);
        card.appendChild(head_row);

        if (sales.length === 0) {
            card.appendChild(create_dom_element('div', { class: 'text-muted' }, [__('No commercial sales recorded for this container as-of cutoff.')]));
        } else {
            var table_wrap = create_dom_element('div', { class: 'fresko-table-responsive' });
            var table = create_dom_element('table', { class: 'fresko-table' });
            var thead = create_dom_element('thead', {}, [
                create_dom_element('tr', {}, [
                    create_dom_element('th', {}, [__('Sale ID')]),
                    create_dom_element('th', {}, [__('Sale At')]),
                    create_dom_element('th', {}, [__('Status')]),
                    create_dom_element('th', {}, [__('Customer / Raw Alias')]),
                    create_dom_element('th', {}, [__('Movement Status')]),
                    create_dom_element('th', {}, [__('Reconciliation State')]),
                    create_dom_element('th', {}, [__('Known Amount')]),
                    create_dom_element('th', {}, [__('Action')])
                ])
            ]);
            var tbody = create_dom_element('tbody');
            sales.forEach(function(s) {
                var tr = create_dom_element('tr', {
                    class: (self.selected_sale && self.selected_sale.name === s.name ? 'selected' : '')
                });
                var sale_link = create_dom_element('a', {
                    href: '#',
                    class: 'fresko-link font-weight-bold',
                    onClick: function(e) {
                        e.preventDefault();
                        self.selected_sale = s;
                        self.render_sales_panel();
                    }
                }, [s.name]);

                var party_node = s.customer ?
                    create_dom_element('span', {}, [s.customer]) :
                    render_raw_alias_node(s.raw_party_alias);

                var amt_display = format_financial_amount(s.total_commercial_amount, s.currency);
                if (s.total_commercial_amount === null && s.known_commercial_amount) {
                    amt_display = s.currency + ' ' + s.known_commercial_amount + ' (PARTIAL: ' + s.pending_amount_line_count + ' unpriced)';
                }

                tr.appendChild(create_dom_element('td', {}, [sale_link]));
                tr.appendChild(create_dom_element('td', {}, [s.sale_at || '—']));
                tr.appendChild(create_dom_element('td', {}, [render_badge_node(s.status)]));
                tr.appendChild(create_dom_element('td', {}, [party_node]));
                tr.appendChild(create_dom_element('td', {}, [render_badge_node(s.movement_status)]));
                tr.appendChild(create_dom_element('td', {}, [render_badge_node(s.reconciliation_state)]));
                tr.appendChild(create_dom_element('td', {}, [amt_display]));

                var act_btn = create_dom_element('button', {
                    class: 'fresko-btn-sm fresko-btn-secondary',
                    onClick: function() {
                        self.selected_sale = s;
                        self.render_sales_panel();
                    }
                }, [__('Inspect')]);
                tr.appendChild(create_dom_element('td', {}, [act_btn]));

                tbody.appendChild(tr);
            });
            table.appendChild(thead);
            table.appendChild(tbody);
            table_wrap.appendChild(table);
            card.appendChild(table_wrap);
        }
        layout.appendChild(card);

        // Selected Sale Detail View
        if (this.selected_sale) {
            layout.appendChild(this.render_selected_sale_detail(this.selected_sale));
        }

        this.content_panel.appendChild(layout);
    }

    render_selected_sale_detail(sale) {
        var self = this;
        var card = create_dom_element('div', { class: 'fresko-section-card', style: { borderColor: '#1b66c9' } });

        var head = create_dom_element('div', { class: 'fresko-card-title' }, [
            create_dom_element('span', {}, [__('Selected Sale: ') + sale.name + (sale.projection_mode === 'LIVE' ? ' (Live version ' + sale.current_version + ')' : ' (Historical version ' + (sale.version_at_cutoff === null || sale.version_at_cutoff === undefined ? 'UNKNOWN' : sale.version_at_cutoff) + ')')]),
            create_dom_element('div', { style: { display: 'flex', gap: '8px' } }, [
                render_badge_node(sale.status),
                render_badge_node(sale.reconciliation_state)
            ])
        ]);
        card.appendChild(head);

        // Meta Summary
        var meta_grid = create_dom_element('div', { class: 'fresko-grid-2', style: { marginBottom: '16px' } }, [
            create_dom_element('div', {}, [
                create_dom_element('div', { class: 'text-muted small' }, [__('Customer / Raw Alias')]),
                sale.customer ? create_dom_element('strong', {}, [sale.customer]) : render_raw_alias_node(sale.raw_party_alias)
            ]),
            create_dom_element('div', {}, [
                create_dom_element('div', { class: 'text-muted small' }, [__('Source Evidence')]),
                render_evidence_link_node(sale.source_evidence)
            ]),
            create_dom_element('div', {}, [
                create_dom_element('div', { class: 'text-muted small' }, [__('Effective At Cutoff')]),
                create_dom_element('strong', {}, [sale.effective_at_cutoff ? __('Yes') : __('No')])
            ]),
            create_dom_element('div', {}, [
                create_dom_element('div', { class: 'text-muted small' }, [__('Movement Status')]),
                render_badge_node(sale.movement_status)
            ])
        ]);
        card.appendChild(meta_grid);

        // Workflow Action Buttons (Role-aware client controls; server authorizes strictly)
        var act_bar = create_dom_element('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' } });
        if (this.is_live_view() && sale.projection_mode === 'LIVE' && sale.status === 'DRAFT') {
            if (this.user_context.can_prepare) {
                act_bar.appendChild(create_dom_element('button', {
                    class: 'fresko-btn-sm fresko-btn-primary',
                    onClick: function() { self.submit_sale(sale); }
                }, [__('Submit Sale')]));
            }
        } else if (this.is_live_view() && sale.projection_mode === 'LIVE' && sale.status === 'REVIEW_PENDING') {
            if (self.user_context.can_verify) {
                act_bar.appendChild(create_dom_element('button', {
                    class: 'fresko-btn-sm fresko-btn-primary',
                    onClick: function() { self.verify_sale(sale); }
                }, [__('Verify Sale')]));
                act_bar.appendChild(create_dom_element('button', {
                    class: 'fresko-btn-sm fresko-btn-danger',
                    onClick: function() { self.reject_sale_dialog(sale); }
                }, [__('Reject Sale')]));
            }
        } else if (this.is_live_view() && sale.projection_mode === 'LIVE' && sale.status === 'VERIFIED') {
            if (self.user_context.can_approve) {
                act_bar.appendChild(create_dom_element('button', {
                    class: 'fresko-btn-sm fresko-btn-primary',
                    onClick: function() { self.approve_sale(sale); }
                }, [__('Approve Sale')]));
                act_bar.appendChild(create_dom_element('button', {
                    class: 'fresko-btn-sm fresko-btn-danger',
                    onClick: function() { self.reject_sale_dialog(sale); }
                }, [__('Reject Sale')]));
            }
        }

        act_bar.appendChild(create_dom_element('button', {
            class: 'fresko-btn-sm fresko-btn-secondary',
            disabled: self.is_live_view() ? null : 'disabled',
                onClick: function() { self.open_allocation_dialog(sale, null); }
        }, [__('+ Allocate to Outward')]));

        card.appendChild(act_bar);

        // Lines Table
        card.appendChild(create_dom_element('h4', { style: { fontSize: '14px', marginBottom: '8px' } }, [__('Sale Lines')]));
        var lines = sale.lines || [];
        var lines_wrap = create_dom_element('div', { class: 'fresko-table-responsive' });
        var lines_table = create_dom_element('table', { class: 'fresko-table' });
        var lines_thead = create_dom_element('thead', {}, [
            create_dom_element('tr', {}, [
                create_dom_element('th', {}, [__('Line Key')]),
                create_dom_element('th', {}, [__('Item')]),
                create_dom_element('th', {}, [__('Lot')]),
                create_dom_element('th', {}, [__('Qty')]),
                create_dom_element('th', {}, [__('UOM')]),
                create_dom_element('th', {}, [__('Price State')]),
                create_dom_element('th', {}, [__('Rate')]),
                create_dom_element('th', {}, [__('Amount')]),
                create_dom_element('th', {}, [__('Allocated Qty')]),
                create_dom_element('th', {}, [__('Remaining Qty')]),
                create_dom_element('th', {}, [__('Action')])
            ])
        ]);
        var lines_tbody = create_dom_element('tbody');
        lines.forEach(function(l) {
            var tr = create_dom_element('tr');
            var lot_desc = l.container_lot || l.raw_lot_text || '—';
            var qty_desc = format_qty(l.qty, null);
            var rate_desc = (l.rate !== null && l.rate !== undefined) ? l.rate : 'UNKNOWN';
            var amt_desc = format_financial_amount(l.amount, sale.currency);

            tr.appendChild(create_dom_element('td', {}, [l.line_key]));
            tr.appendChild(create_dom_element('td', {}, [l.item || '—']));
            tr.appendChild(create_dom_element('td', {}, [
                create_dom_element('div', {}, [lot_desc]),
                render_badge_node(l.lot_state, 'small')
            ]));
            tr.appendChild(create_dom_element('td', {}, [
                create_dom_element('div', {}, [qty_desc]),
                render_badge_node(l.qty_state, 'small')
            ]));
            tr.appendChild(create_dom_element('td', {}, [l.uom || '—']));
            tr.appendChild(create_dom_element('td', {}, [render_badge_node(l.price_state)]));
            tr.appendChild(create_dom_element('td', {}, [rate_desc]));
            tr.appendChild(create_dom_element('td', {}, [amt_desc]));
            tr.appendChild(create_dom_element('td', {}, [l.allocated_qty || '0']));
            tr.appendChild(create_dom_element('td', {}, [l.remaining_qty !== null ? l.remaining_qty : 'UNKNOWN']));

            var line_act = create_dom_element('td');
            if (self.is_live_view() && sale.projection_mode === 'LIVE' && (l.price_state === 'UNKNOWN' || l.price_state === 'PROPOSED')) {
                line_act.appendChild(create_dom_element('button', {
                    class: 'fresko-btn-sm fresko-btn-secondary',
                    onClick: function() { self.open_propose_rate_dialog(sale, l); }
                }, [__('Propose Rate')]));
            }
            tr.appendChild(line_act);
            lines_tbody.appendChild(tr);
        });
        lines_table.appendChild(lines_thead);
        lines_table.appendChild(lines_tbody);
        lines_wrap.appendChild(lines_table);
        card.appendChild(lines_wrap);

        // Allocations Table (Approved Projections)
        card.appendChild(create_dom_element('h4', { style: { fontSize: '14px', marginTop: '16px', marginBottom: '8px' } }, [__('Linked Outward Allocations (Approved Projections)')]));
        var allocs = sale.allocations || [];
        if (allocs.length === 0) {
            card.appendChild(create_dom_element('div', { class: 'text-muted small' }, [__('No physical outward allocations linked to this sale.')]));
        } else {
            var alloc_wrap = create_dom_element('div', { class: 'fresko-table-responsive' });
            var alloc_table = create_dom_element('table', { class: 'fresko-table' });
            alloc_table.appendChild(create_dom_element('thead', {}, [
                create_dom_element('tr', {}, [
                    create_dom_element('th', {}, [__('Allocation Name')]),
                    create_dom_element('th', {}, [__('Sale Line')]),
                    create_dom_element('th', {}, [__('Outward')]),
                    create_dom_element('th', {}, [__('Outward Line')]),
                    create_dom_element('th', {}, [__('Qty')]),
                    create_dom_element('th', {}, [__('UOM')]),
                    create_dom_element('th', {}, [__('Movement At')])
                ])
            ]));
            var alloc_tbody = create_dom_element('tbody');
            allocs.forEach(function(a) {
                alloc_tbody.appendChild(create_dom_element('tr', {}, [
                    create_dom_element('td', {}, [a.name]),
                    create_dom_element('td', {}, [a.sale_line_key]),
                    create_dom_element('td', {}, [a.outward]),
                    create_dom_element('td', {}, [a.outward_line_key]),
                    create_dom_element('td', {}, [String(a.qty)]),
                    create_dom_element('td', {}, [a.uom]),
                    create_dom_element('td', {}, [a.movement_at || '—'])
                ]));
            });
            alloc_table.appendChild(alloc_tbody);
            alloc_wrap.appendChild(alloc_table);
            card.appendChild(alloc_wrap);
        }

        // Allocation Review Queue (PROPOSED, VERIFIED, APPROVED, REJECTED, REVERSED lifecycle via frappe.client.get_list)
        card.appendChild(create_dom_element('h4', { style: { fontSize: '14px', marginTop: '16px', marginBottom: '8px' } }, [__('Allocation Review Queue & Physical Lifecycle')]));
        var alloc_queue_wrap = create_dom_element('div', { class: 'fresko-alloc-queue-wrap' });
        card.appendChild(alloc_queue_wrap);
        self.load_sale_allocations(sale, alloc_queue_wrap);

        return card;
    }

    // -----------------------------------------------------
    // Panel 3: Outwards
    // -----------------------------------------------------
    render_outwards_panel() {
        this.content_panel.innerHTML = '';
        var self = this;
        var container_dom = create_dom_element('div', {});

        var card = create_dom_element('div', { class: 'fresko-section-card' });
        card.appendChild(create_dom_element('h3', { class: 'fresko-card-title' }, [__('Physical Outwards Reconciliation')]));

        var fetch_btn = create_dom_element('button', {
            class: 'fresko-btn-sm fresko-btn-secondary',
            style: { marginBottom: '12px' },
            onClick: function() { self.load_outwards_list(); }
        }, [__('Load Container Outwards')]);
        card.appendChild(fetch_btn);

        var out_list_dom = create_dom_element('div', { id: 'fresko-outwards-list' });
        card.appendChild(out_list_dom);
        container_dom.appendChild(card);

        if (this.selected_outward_data) {
            container_dom.appendChild(this.render_selected_outward_detail(this.selected_outward_data));
        }

        this.content_panel.appendChild(container_dom);
        this.load_outwards_list();
    }

    load_outwards_list() {
        var self = this;
        var list_wrap = this.content_panel.querySelector('#fresko-outwards-list');
        if (!list_wrap) return;
        list_wrap.innerHTML = '<div class="text-muted">Loading outwards...</div>';

        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Fresko Outward',
                filters: { container: this.container_name, movement_type: 'OUTWARD' },
                fields: ['name', 'movement_at', 'status', 'vehicle_no', 'gatepass_no', 'company'],
                order_by: 'movement_at desc'
            }
        }).then(function(r) {
            var outwards = r.message || [];
            list_wrap.innerHTML = '';
            if (outwards.length === 0) {
                list_wrap.appendChild(create_dom_element('div', { class: 'text-muted' }, [__('No physical Outwards found for container.')]));
                return;
            }
            var table_wrap = create_dom_element('div', { class: 'fresko-table-responsive' });
            var table = create_dom_element('table', { class: 'fresko-table' });
            table.appendChild(create_dom_element('thead', {}, [
                create_dom_element('tr', {}, [
                    create_dom_element('th', {}, [__('Outward ID')]),
                    create_dom_element('th', {}, [__('Movement At')]),
                    create_dom_element('th', {}, [__('Status')]),
                    create_dom_element('th', {}, [__('Vehicle No')]),
                    create_dom_element('th', {}, [__('Gatepass No')]),
                    create_dom_element('th', {}, [__('Action')])
                ])
            ]));
            var tbody = create_dom_element('tbody');
            outwards.forEach(function(o) {
                var tr = create_dom_element('tr', {
                    class: (self.selected_outward_name === o.name ? 'selected' : '')
                });
                tr.appendChild(create_dom_element('td', {}, [create_dom_element('strong', {}, [o.name])]));
                tr.appendChild(create_dom_element('td', {}, [o.movement_at || '—']));
                tr.appendChild(create_dom_element('td', {}, [render_badge_node(o.status)]));
                tr.appendChild(create_dom_element('td', {}, [o.vehicle_no || '—']));
                tr.appendChild(create_dom_element('td', {}, [o.gatepass_no || '—']));
                tr.appendChild(create_dom_element('td', {}, [
                    create_dom_element('button', {
                        class: 'fresko-btn-sm fresko-btn-secondary',
                        onClick: function() { self.inspect_outward(o.name); }
                    }, [__('Reconcile')])
                ]));
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            table_wrap.appendChild(table);
            list_wrap.appendChild(table_wrap);
        });
    }

    inspect_outward(outward_name) {
        var self = this;
        this.selected_outward_name = outward_name;
        frappe.call({
            method: 'fresko_universe.commercial.get_outward_reconciliation',
            args: {
                outward_name: outward_name,
                as_of: this.as_of_value || null
            }
        }).then(function(r) {
            self.selected_outward_data = r.message || null;
            self.render_outwards_panel();
        }).catch(function(err) {
            frappe.msgprint(__('Failed to inspect outward: ') + (err.message || 'Error'));
        });
    }

    render_selected_outward_detail(outward) {
        var self = this;
        var card = create_dom_element('div', { class: 'fresko-section-card', style: { borderColor: '#1b66c9', marginTop: '16px' } });
        card.appendChild(create_dom_element('div', { class: 'fresko-card-title' }, [
            create_dom_element('span', {}, [__('Outward Reconciliation: ') + outward.outward]),
            render_badge_node(outward.reconciliation_state)
        ]));

        // Unresolved flags
        if (outward.unresolved_flags && outward.unresolved_flags.length > 0) {
            var flags_wrap = create_dom_element('div', { style: { display: 'flex', gap: '8px', marginBottom: '12px' } });
            outward.unresolved_flags.forEach(function(f) {
                flags_wrap.appendChild(render_badge_node(f, 'fresko-badge-exception'));
            });
            card.appendChild(flags_wrap);
        }

        // Lines table
        card.appendChild(create_dom_element('h4', { style: { fontSize: '14px', marginBottom: '8px' } }, [__('Physical Lines & Allocations')]));
        var lines = outward.lines || [];
        var table_wrap = create_dom_element('div', { class: 'fresko-table-responsive' });
        var table = create_dom_element('table', { class: 'fresko-table' });
        table.appendChild(create_dom_element('thead', {}, [
            create_dom_element('tr', {}, [
                create_dom_element('th', {}, [__('Line Key')]),
                create_dom_element('th', {}, [__('UOM')]),
                create_dom_element('th', {}, [__('Physical Qty')]),
                create_dom_element('th', {}, [__('Commercially Allocated')]),
                create_dom_element('th', {}, [__('Remaining Qty')])
            ])
        ]));
        var tbody = create_dom_element('tbody');
        lines.forEach(function(l) {
            tbody.appendChild(create_dom_element('tr', {}, [
                create_dom_element('td', {}, [l.line_key]),
                create_dom_element('td', {}, [l.uom]),
                create_dom_element('td', {}, [l.qty]),
                create_dom_element('td', {}, [l.commercially_allocated_qty]),
                create_dom_element('td', {}, [l.remaining_qty !== null ? l.remaining_qty : 'UNKNOWN'])
            ]));
        });
        table.appendChild(tbody);
        table_wrap.appendChild(table);
        card.appendChild(table_wrap);

        // Action: New Allocation Button
        card.appendChild(create_dom_element('div', { style: { marginTop: '12px' } }, [
            create_dom_element('button', {
                class: 'fresko-btn-sm fresko-btn-primary',
                disabled: self.is_live_view() ? null : 'disabled',
                onClick: function() { self.open_allocation_dialog(null, outward); }
            }, [__('+ Propose Sale Allocation for this Outward')])
        ]));

        return card;
    }

    // -----------------------------------------------------
    // Panel 4: Alias Review Queue
    // -----------------------------------------------------
    render_alias_panel() {
        this.content_panel.innerHTML = '';
        var self = this;
        var card = create_dom_element('div', { class: 'fresko-section-card' });
        card.appendChild(create_dom_element('div', { class: 'fresko-card-title' }, [
            create_dom_element('span', {}, [__('Party Alias Mapping Review Queue')]),
            create_dom_element('button', {
                class: 'fresko-btn-sm fresko-btn-primary',
                disabled: self.is_live_view() ? null : 'disabled',
                onClick: function() { self.open_propose_alias_dialog(); }
            }, [__('+ Propose New Alias Mapping')])
        ]));

        var wrap = create_dom_element('div', { id: 'fresko-alias-queue-wrap' });
        card.appendChild(wrap);
        this.content_panel.appendChild(card);
        this.load_alias_mappings();
    }

    load_alias_mappings() {
        var self = this;
        var wrap = this.content_panel.querySelector('#fresko-alias-queue-wrap');
        if (!wrap) return;
        if (!this.is_live_view()) {
            wrap.textContent = __('The current alias review queue is available in Live view.');
            return;
        }
        var generation = this.current_load_seq;
        wrap.innerHTML = '<div class="text-muted">Loading alias queue...</div>';

        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Fresko Party Alias Mapping',
                fields: ['name', 'company', 'raw_alias', 'proposed_customer', 'status', 'evidence', 'reason', 'version', 'proposed_by'],
                order_by: 'creation desc',
                limit_page_length: 50
            }
        }).then(function(r) {
            if (generation !== self.current_load_seq || !self.is_live_view()) return;
            var mappings = r.message || [];
            wrap.innerHTML = '';
            if (mappings.length === 0) {
                wrap.appendChild(create_dom_element('div', { class: 'text-muted' }, [__('No party alias mappings pending review.')]));
                return;
            }
            var table_wrap = create_dom_element('div', { class: 'fresko-table-responsive' });
            var table = create_dom_element('table', { class: 'fresko-table' });
            table.appendChild(create_dom_element('thead', {}, [
                create_dom_element('tr', {}, [
                    create_dom_element('th', {}, [__('Mapping ID')]),
                    create_dom_element('th', {}, [__('Raw Exact Alias')]),
                    create_dom_element('th', {}, [__('Proposed Customer')]),
                    create_dom_element('th', {}, [__('Status')]),
                    create_dom_element('th', {}, [__('Evidence')]),
                    create_dom_element('th', {}, [__('Reason')]),
                    create_dom_element('th', {}, [__('Actions')])
                ])
            ]));
            var tbody = create_dom_element('tbody');
            mappings.forEach(function(m) {
                var tr = create_dom_element('tr');
                tr.appendChild(create_dom_element('td', {}, [m.name]));
                tr.appendChild(create_dom_element('td', {}, [render_raw_alias_node(m.raw_alias)]));
                tr.appendChild(create_dom_element('td', {}, [m.proposed_customer || '—']));
                tr.appendChild(create_dom_element('td', {}, [render_badge_node(m.status)]));
                tr.appendChild(create_dom_element('td', {}, [render_evidence_link_node(m.evidence)]));
                tr.appendChild(create_dom_element('td', {}, [m.reason || '—']));

                var act_td = create_dom_element('td');
                var act_group = create_dom_element('div', { style: { display: 'flex', gap: '6px' } });
                if (m.status === 'PROPOSED') {
                    if (self.user_context.can_verify) {
                        act_group.appendChild(create_dom_element('button', {
                            class: 'fresko-btn-sm fresko-btn-primary',
                            onClick: function() { self.verify_alias(m); }
                        }, [__('Verify')]));
                        act_group.appendChild(create_dom_element('button', {
                            class: 'fresko-btn-sm fresko-btn-danger',
                            onClick: function() { self.reject_alias_dialog(m); }
                        }, [__('Reject')]));
                    }
                } else if (m.status === 'VERIFIED') {
                    if (self.user_context.can_approve) {
                        act_group.appendChild(create_dom_element('button', {
                            class: 'fresko-btn-sm fresko-btn-primary',
                            onClick: function() { self.approve_alias(m); }
                        }, [__('Approve')]));
                        act_group.appendChild(create_dom_element('button', {
                            class: 'fresko-btn-sm fresko-btn-danger',
                            onClick: function() { self.reject_alias_dialog(m); }
                        }, [__('Reject')]));
                    }
                }
                act_td.appendChild(act_group);
                tr.appendChild(act_td);
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            table_wrap.appendChild(table);
            wrap.appendChild(table_wrap);
        }).catch(function(err) {
            if (generation !== self.current_load_seq || !self.is_live_view()) return;
            wrap.innerHTML = '';
            var err_box = create_dom_element('div', { class: 'text-danger', style: { marginBottom: '8px' } }, [
                __('Failed to load alias queue: ') + (err.message || 'Error')
            ]);
            var retry_btn = create_dom_element('button', {
                class: 'btn btn-sm btn-secondary',
                onClick: function() { self.load_alias_mappings(); }
            }, [__('Retry')]);
            wrap.appendChild(err_box);
            wrap.appendChild(retry_btn);
        });
    }

    load_sale_allocations(sale, wrap_el) {
        var self = this;
        if (!this.is_live_view()) {
            wrap_el.textContent = __('The current allocation review queue is available in Live view.');
            return;
        }
        var generation = this.current_load_seq;
        wrap_el.innerHTML = '<div class="text-muted small">Loading allocation records...</div>';

        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Fresko Sale Outward Allocation',
                filters: { sale: sale.name },
                fields: ['name', 'sale', 'sale_line_key', 'outward', 'outward_line_key', 'qty', 'uom', 'state', 'verified_by', 'prepared_by', 'evidence', 'reason', 'source_event_key', 'version'],
                order_by: 'creation desc',
                limit_page_length: 50
            }
        }).then(function(r) {
            if (generation !== self.current_load_seq || !self.is_live_view()) return;
            var allocs = r.message || [];
            wrap_el.innerHTML = '';
            if (allocs.length === 0) {
                wrap_el.appendChild(create_dom_element('div', { class: 'text-muted small' }, [__('No allocation records found for this sale.')]));
                return;
            }
            var table_wrap = create_dom_element('div', { class: 'fresko-table-responsive' });
            var table = create_dom_element('table', { class: 'fresko-table' });
            table.appendChild(create_dom_element('thead', {}, [
                create_dom_element('tr', {}, [
                    create_dom_element('th', {}, [__('Allocation ID')]),
                    create_dom_element('th', {}, [__('Sale Line')]),
                    create_dom_element('th', {}, [__('Outward Line')]),
                    create_dom_element('th', {}, [__('Qty / UOM')]),
                    create_dom_element('th', {}, [__('Status')]),
                    create_dom_element('th', {}, [__('Evidence')]),
                    create_dom_element('th', {}, [__('Source Event Key')]),
                    create_dom_element('th', {}, [__('Actions')])
                ])
            ]));
            var tbody = create_dom_element('tbody');
            allocs.forEach(function(a) {
                var tr = create_dom_element('tr');
                tr.appendChild(create_dom_element('td', {}, [create_dom_element('strong', {}, [a.name])]));
                tr.appendChild(create_dom_element('td', {}, [a.sale_line_key || '—']));
                tr.appendChild(create_dom_element('td', {}, [(a.outward || '—') + ' / ' + (a.outward_line_key || '—')]));
                tr.appendChild(create_dom_element('td', {}, [String(a.qty) + ' ' + (a.uom || '')]));
                tr.appendChild(create_dom_element('td', {}, [render_badge_node(a.state === 'PROPOSED' && a.verified_by ? 'VERIFIED' : a.state)]));
                tr.appendChild(create_dom_element('td', {}, [render_evidence_link_node(a.evidence)]));
                tr.appendChild(create_dom_element('td', {}, [render_raw_alias_node(a.source_event_key)]));

                var act_td = create_dom_element('td');
                var act_group = create_dom_element('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } });

                if (a.state === 'PROPOSED' && !a.verified_by) {
                    if (self.user_context.can_verify && a.prepared_by !== frappe.session.user) {
                        act_group.appendChild(create_dom_element('button', {
                            class: 'fresko-btn-sm fresko-btn-primary',
                            onClick: function() { self.verify_allocation(a); }
                        }, [__('Verify')]));
                    }
                    act_group.appendChild(create_dom_element('button', {
                        class: 'fresko-btn-sm fresko-btn-danger',
                        onClick: function() { self.reject_allocation_dialog(a); }
                    }, [__('Reject')]));
                } else if (a.state === 'PROPOSED' && a.verified_by) {
                    if (self.user_context.can_approve && a.prepared_by !== frappe.session.user && a.verified_by !== frappe.session.user) {
                        act_group.appendChild(create_dom_element('button', {
                            class: 'fresko-btn-sm fresko-btn-primary',
                            onClick: function() { self.approve_allocation(a); }
                        }, [__('Approve')]));
                    }
                    act_group.appendChild(create_dom_element('button', {
                        class: 'fresko-btn-sm fresko-btn-danger',
                        onClick: function() { self.reject_allocation_dialog(a); }
                    }, [__('Reject')]));
                } else if (a.state === 'APPROVED' && self.user_context.can_approve) {
                    act_group.appendChild(create_dom_element('button', {
                        class: 'fresko-btn-sm fresko-btn-danger',
                        onClick: function() { self.reverse_allocation_dialog(a); }
                    }, [__('Reverse')]));
                }

                act_td.appendChild(act_group);
                tr.appendChild(act_td);
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            table_wrap.appendChild(table);
            wrap_el.appendChild(table_wrap);
        }).catch(function(err) {
            wrap_el.innerHTML = '<div class="text-danger small">' + escape_html(err.message || __('Failed to load allocations')) + '</div>';
        });
    }

    verify_allocation(alloc) {
        if (!this.require_mutation(alloc, 'version')) return;
        var self = this;
        frappe.call({
            method: 'fresko_universe.commercial.verify_sale_outward_allocation',
            args: { allocation_name: alloc.name, expected_version: alloc.version }
        }).then(function() {
            frappe.msgprint(__('Allocation verified successfully.'));
            self.load_container_data();
        }).catch(function(err) {
            frappe.msgprint(__('Verification failed: ') + (err.message || 'Error'));
        });
    }

    approve_allocation(alloc) {
        if (!this.require_mutation(alloc, 'version')) return;
        var self = this;
        frappe.call({
            method: 'fresko_universe.commercial.approve_sale_outward_allocation',
            args: { allocation_name: alloc.name, expected_version: alloc.version }
        }).then(function() {
            frappe.msgprint(__('Allocation approved successfully.'));
            self.load_container_data();
        }).catch(function(err) {
            frappe.msgprint(__('Approval failed: ') + (err.message || 'Error'));
        });
    }

    reject_allocation_dialog(alloc) {
        if (!this.require_mutation(alloc, 'version')) return;
        var self = this;
        frappe.prompt([
            { fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }
        ], function(values) {
            if (!self.require_live_view()) return;
            frappe.call({
                method: 'fresko_universe.commercial.reject_sale_outward_allocation',
                args: {
                    allocation_name: alloc.name,
                    reason: values.reason,
                    expected_version: alloc.version
                }
            }).then(function() {
                frappe.msgprint(__('Allocation rejected.'));
                self.load_container_data();
            }).catch(function(err) {
                frappe.msgprint(__('Rejection failed: ') + (err.message || 'Error'));
            });
        }, __('Reject Allocation: ') + alloc.name, __('Reject'));
    }

    reverse_allocation_dialog(alloc) {
        if (!this.require_mutation(alloc, 'version')) return;
        var self = this;
        var d = new frappe.ui.Dialog({
            title: __('Reverse Physical Allocation: ') + alloc.name,
            fields: [
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Reversal Reason'),
                    reqd: 1
                },
                {
                    fieldname: 'evidence',
                    fieldtype: 'Link',
                    options: 'Fresko Evidence',
                    label: __('Reversal Evidence'),
                    reqd: 1
                }
            ],
            primary_action_label: __('Reverse Allocation'),
            primary_action: function(values) {
                if (!self.require_live_view()) return;
                frappe.call({
                    method: 'fresko_universe.commercial.reverse_sale_outward_allocation',
                    args: {
                        allocation_name: alloc.name,
                        reason: values.reason,
                        evidence: values.evidence,
                        expected_version: alloc.version
                    }
                }).then(function() {
                    frappe.msgprint(__('Allocation reversed successfully.'));
                    d.hide();
                    self.load_container_data();
                }).catch(function(err) {
                    frappe.msgprint(__('Reversal failed: ') + (err.message || 'Error'));
                });
            }
        });
        d.show();
    }

    // -----------------------------------------------------
    // Dialog 1: Sale Preparation (Multi-lot, Qty/Rate unknown supported)
    // -----------------------------------------------------
    open_sale_preparation_dialog() {
        if (!this.require_live_view()) return;
        if (!this.user_context.can_prepare) {
            frappe.msgprint(__('Only Fresko Salesperson can prepare commercial sales.'));
            return;
        }
        var self = this;
        if (!this.container_name) {
            frappe.msgprint(__('Please select a Container first.'));
            return;
        }

        frappe.call({
            method: 'frappe.client.get',
            args: { doctype: 'Fresko Container', name: this.container_name }
        }).then(function(r) {
            var container_doc = r.message;
            self.show_sale_dialog_with_container(container_doc);
        });
    }

    show_sale_dialog_with_container(container_doc) {
        var self = this;
        var lots = container_doc.lots || [];
        var dialog_event_id = generate_uuid();

        var d = new frappe.ui.Dialog({
            title: __('Prepare Commercial Sale'),
            fields: [
                {
                    fieldname: 'company',
                    fieldtype: 'Link',
                    options: 'Company',
                    label: __('Company'),
                    reqd: 1,
                    default: container_doc.company
                },
                {
                    fieldname: 'container',
                    fieldtype: 'Link',
                    options: 'Fresko Container',
                    label: __('Container'),
                    reqd: 1,
                    default: container_doc.name,
                    read_only: 1
                },
                {
                    fieldname: 'sale_at',
                    fieldtype: 'Datetime',
                    label: __('Sale At'),
                    reqd: 1,
                    default: frappe.datetime.now_datetime()
                },
                {
                    fieldname: 'currency',
                    fieldtype: 'Link',
                    options: 'Currency',
                    label: __('Currency'),
                    reqd: 1,
                    default: container_doc.currency || 'INR'
                },
                {
                    fieldname: 'col_break_1',
                    fieldtype: 'Column Break'
                },
                {
                    fieldname: 'raw_party_alias',
                    fieldtype: 'Data',
                    label: __('Raw Party Alias (exact spacing preserved)')
                },
                {
                    fieldname: 'party_state',
                    fieldtype: 'Select',
                    options: 'UNKNOWN\nKNOWN\nCONTRADICTED',
                    label: __('Party State'),
                    reqd: 1,
                    default: 'UNKNOWN'
                },
                {
                    fieldname: 'source_evidence',
                    fieldtype: 'Link',
                    options: 'Fresko Evidence',
                    label: __('Source Evidence'),
                    reqd: 1
                },
                {
                    fieldname: 'source_event_id',
                    fieldtype: 'Data',
                    label: __('Source Event ID'),
                    reqd: 1,
                    hidden: 1,
                    default: dialog_event_id
                },
                {
                    fieldname: 'sec_lines',
                    fieldtype: 'Section Break',
                    label: __('Sale Lot Lines')
                },
                {
                    fieldname: 'lines_area',
                    fieldtype: 'HTML'
                }
            ],
            primary_action_label: __('Create Sale'),
            primary_action: function(values) {
                if (!self.require_live_view()) return;
                var prepared_lines = [];
                var line_rows = d.$wrapper.find('.fresko-line-row');
                if (line_rows.length === 0) {
                    frappe.msgprint(__('At least one line is required.'));
                    return;
                }

                // Capture raw_party_alias straight from input without trimming whitespace
                var raw_party_input = d.get_field('raw_party_alias').$input;
                var raw_party_alias = raw_party_input ? raw_party_input.val() : values.raw_party_alias;
                if (raw_party_alias === '' || raw_party_alias === undefined) {
                    raw_party_alias = null;
                }

                var has_error = false;
                line_rows.each(function(idx) {
                    var row = $(this);
                    var item = (row.find('.line-item').val() || '').trim();
                    var lot_val = row.find('.line-lot').val() || null;
                    var raw_lot_val = row.find('.line-raw-lot').val();
                    var raw_lot = (raw_lot_val !== '' && raw_lot_val !== undefined && raw_lot_val !== null) ? raw_lot_val : null;
                    var lot_state = row.find('.line-lot-state').val();
                    var qty_state = row.find('.line-qty-state').val();
                    var qty_val = (row.find('.line-qty').val() || '').trim();
                    var uom = (row.find('.line-uom').val() || '').trim();
                    var price_state = row.find('.line-price-state').val();
                    var rate_val = (row.find('.line-rate').val() || '').trim();
                    var rate_basis = row.find('.line-rate-basis').val();
                    var bucket_key_val = (row.find('.line-bucket-key').val() || '').trim();
                    var evidence = (row.find('.line-evidence').val() || '').trim();

                    if (!item || !uom || !evidence) {
                        frappe.msgprint(__('Item, UOM, and Line Evidence are required on row ') + (idx + 1));
                        has_error = true;
                        return false;
                    }
                    if (lot_val && lot_state !== 'KNOWN') {
                        frappe.msgprint(__('Mapped container lot requires KNOWN lot state on row ') + (idx + 1));
                        has_error = true;
                        return false;
                    }
                    if (!lot_val && raw_lot === null && lot_state !== 'UNKNOWN') {
                        frappe.msgprint(__('Null raw lot requires UNKNOWN lot state on row ') + (idx + 1));
                        has_error = true;
                        return false;
                    }
                    if (qty_state === 'KNOWN') {
                        if (!is_positive_decimal_string(qty_val)) {
                            frappe.msgprint(__('Valid positive decimal quantity required on row ') + (idx + 1));
                            has_error = true;
                            return false;
                        }
                    } else {
                        qty_val = null;
                    }
                    if (price_state === 'PROPOSED') {
                        if (!is_valid_decimal_string(rate_val, 2)) {
                            frappe.msgprint(__('Valid decimal rate (up to 2 decimal places) required on row ') + (idx + 1));
                            has_error = true;
                            return false;
                        }
                        if (rate_basis === 'NONE') {
                            frappe.msgprint(__('Rate basis must not be NONE when price is PROPOSED on row ') + (idx + 1));
                            has_error = true;
                            return false;
                        }
                    } else {
                        rate_val = null;
                    }
                    if (rate_basis === 'PRICE_BUCKET') {
                        if (!bucket_key_val) {
                            frappe.msgprint(__('Bucket Key is required when Rate Basis is PRICE_BUCKET on row ') + (idx + 1));
                            has_error = true;
                            return false;
                        }
                    } else {
                        bucket_key_val = null;
                    }

                    prepared_lines.push({
                        line_key: 'line_' + (idx + 1),
                        source_line_ref: null,
                        item: item,
                        container_lot: lot_val,
                        raw_lot_text: raw_lot,
                        lot_state: lot_state,
                        qty: (qty_state === 'KNOWN' && qty_val) ? qty_val : null,
                        uom: uom,
                        qty_state: qty_state,
                        price_state: price_state,
                        rate: (price_state === 'PROPOSED' && rate_val) ? rate_val : null,
                        rate_basis: rate_basis,
                        bucket_key: bucket_key_val,
                        evidence: evidence
                    });
                });

                if (has_error) return;

                frappe.call({
                    method: 'fresko_universe.commercial.create_sale',
                    args: {
                        company: values.company,
                        container: values.container,
                        sale_at: values.sale_at,
                        source_evidence: values.source_evidence,
                        source_event_id: dialog_event_id,
                        lines: prepared_lines,
                        raw_party_alias: raw_party_alias,
                        party_state: values.party_state,
                        currency: values.currency
                    }
                }).then(function(r) {
                    frappe.msgprint(__('Sale created successfully: ') + (r.message ? r.message.name : ''));
                    d.hide();
                    self.load_container_data();
                }).catch(function(err) {
                    frappe.msgprint(__('Failed to create sale: ') + (err.message || 'Error'));
                });
            }
        });

        d.show();

        // Render dynamic lines builder
        var lines_area = d.get_field('lines_area').$wrapper;
        lines_area.empty();

        var table_container = $('<div class="fresko-lines-container"></div>').appendTo(lines_area);
        var add_line_btn = $('<button type="button" class="fresko-btn-sm fresko-btn-secondary">+ Add Lot Line</button>').appendTo(lines_area);

        function add_line_row() {
            var row = $('<div class="fresko-line-row" style="border:1px solid #d1d8dd; border-radius:6px; padding:10px; margin-bottom:10px; background:#fafbfc;"></div>');
            var row_html = `
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:8px; margin-bottom:8px;">
                    <div>
                        <label class="small text-muted">Item</label>
                        <input type="text" class="form-control input-sm line-item" value="${escape_html(container_doc.item || '')}" placeholder="Item">
                    </div>
                    <div>
                        <label class="small text-muted">Container Lot</label>
                        <select class="form-control input-sm line-lot">
                            <option value="">-- None / Unassigned --</option>
                            ${lots.map(l => `<option value="${escape_html(l.name || l.lot_no)}">${escape_html(l.lot_no || l.name)}</option>`).join('')}
                        </select>
                    </div>
                    <div>
                        <label class="small text-muted">Raw Lot Text</label>
                        <input type="text" class="form-control input-sm line-raw-lot" placeholder="Raw Lot">
                    </div>
                    <div>
                        <label class="small text-muted">Lot State</label>
                        <select class="form-control input-sm line-lot-state">
                            <option value="UNKNOWN" selected>UNKNOWN</option>
                            <option value="KNOWN">KNOWN</option>
                            <option value="CONTRADICTED">CONTRADICTED</option>
                        </select>
                    </div>
                </div>
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:8px; margin-bottom:8px;">
                    <div>
                        <label class="small text-muted">Qty State</label>
                        <select class="form-control input-sm line-qty-state">
                            <option value="KNOWN">KNOWN</option>
                            <option value="UNKNOWN">UNKNOWN</option>
                        </select>
                    </div>
                    <div>
                        <label class="small text-muted">Quantity</label>
                        <input type="text" inputmode="decimal" class="form-control input-sm line-qty" placeholder="Qty">
                    </div>
                    <div>
                        <label class="small text-muted">UOM</label>
                        <input type="text" class="form-control input-sm line-uom" value="${escape_html(container_doc.uom || '')}" placeholder="UOM">
                    </div>
                    <div>
                        <label class="small text-muted">Price State</label>
                        <select class="form-control input-sm line-price-state">
                            <option value="UNKNOWN">UNKNOWN</option>
                            <option value="PROPOSED">PROPOSED</option>
                        </select>
                    </div>
                    <div>
                        <label class="small text-muted">Rate</label>
                        <input type="text" inputmode="decimal" class="form-control input-sm line-rate" placeholder="Rate" disabled>
                    </div>
                    <div>
                        <label class="small text-muted">Rate Basis</label>
                        <select class="form-control input-sm line-rate-basis">
                            <option value="RATE_ASSERTION">RATE_ASSERTION</option>
                            <option value="PRICE_BUCKET">PRICE_BUCKET</option>
                            <option value="NONE">NONE</option>
                        </select>
                    </div>
                    <div class="line-bucket-wrap" style="display:none;">
                        <label class="small text-muted">Bucket Key</label>
                        <input type="text" class="form-control input-sm line-bucket-key" placeholder="Bucket Key">
                    </div>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:flex-end; gap:8px;">
                    <div style="flex:1;">
                        <label class="small text-muted">Line Evidence</label>
                        <input type="text" class="form-control input-sm line-evidence" placeholder="Fresko Evidence ID">
                    </div>
                    <button type="button" class="fresko-btn-sm fresko-btn-danger remove-line-btn">Remove</button>
                </div>
            `;
            row.html(row_html);

            // Event bindings for container lot, qty, price state, and rate basis
            row.find('.line-lot').on('change', function() {
                var lot_val = $(this).val();
                if (lot_val) {
                    row.find('.line-lot-state').val('KNOWN');
                    var matched = lots.find(function(l) { return (l.name || l.lot_no) === lot_val; });
                    if (matched) {
                        if (matched.item) row.find('.line-item').val(matched.item);
                        if (matched.uom) row.find('.line-uom').val(matched.uom);
                    }
                } else if (!row.find('.line-raw-lot').val()) {
                    row.find('.line-lot-state').val('UNKNOWN');
                    row.find('.line-item').val(container_doc.item || '');
                    row.find('.line-uom').val(container_doc.uom || '');
                }
            });

            row.find('.line-raw-lot').on('input', function() {
                var raw_val = $(this).val();
                if (!row.find('.line-lot').val() && !raw_val) {
                    row.find('.line-lot-state').val('UNKNOWN');
                }
            });

            row.find('.line-qty-state').on('change', function() {
                var val = $(this).val();
                var qty_input = row.find('.line-qty');
                if (val === 'UNKNOWN') {
                    qty_input.val('').prop('disabled', true);
                } else {
                    qty_input.prop('disabled', false);
                }
            });

            row.find('.line-price-state').on('change', function() {
                var val = $(this).val();
                var rate_input = row.find('.line-rate');
                if (val === 'UNKNOWN') {
                    rate_input.val('').prop('disabled', true);
                } else {
                    rate_input.prop('disabled', false);
                }
            });

            row.find('.line-rate-basis').on('change', function() {
                var basis = $(this).val();
                if (basis === 'PRICE_BUCKET') {
                    row.find('.line-bucket-wrap').show();
                } else {
                    row.find('.line-bucket-wrap').hide().find('.line-bucket-key').val('');
                }
            });

            row.find('.remove-line-btn').on('click', function() {
                row.remove();
            });

            table_container.appendChild ? table_container.appendChild(row[0]) : table_container.append(row);
        }

        add_line_btn.on('click', add_line_row);
        add_line_row(); // Start with 1 line row by default
    }

    // -----------------------------------------------------
    // Dialog 2: Propose Sale-Outward Allocation
    // -----------------------------------------------------
    open_allocation_dialog(sale, outward) {
        if (!this.require_live_view()) return;
        var self = this;
        var initial_sale_name = sale ? sale.name : '';
        var initial_outward_name = outward ? (outward.outward || outward.name) : '';
        var dialog_event_id = generate_uuid();

        var sale_lines_by_key = {};
        var outward_lines_by_key = {};
        var sale_load_seq = 0;
        var outward_load_seq = 0;

        var d = new frappe.ui.Dialog({
            title: __('Propose Sale-Outward Allocation'),
            fields: [
                {
                    fieldname: 'sale_name',
                    fieldtype: 'Link',
                    options: 'Fresko Commercial Sale',
                    label: __('Commercial Sale'),
                    reqd: 1,
                    default: initial_sale_name,
                    change: function() {
                        load_sale_lines(d.get_value('sale_name'));
                    }
                },
                {
                    fieldname: 'sale_line_key',
                    fieldtype: 'Select',
                    label: __('Sale Line'),
                    options: [''],
                    reqd: 1,
                    change: function() {
                        sync_uom();
                    }
                },
                {
                    fieldname: 'outward',
                    fieldtype: 'Link',
                    options: 'Fresko Outward',
                    label: __('Physical Outward'),
                    reqd: 1,
                    default: initial_outward_name,
                    change: function() {
                        load_outward_lines(d.get_value('outward'));
                    }
                },
                {
                    fieldname: 'outward_line_key',
                    fieldtype: 'Select',
                    label: __('Outward Line'),
                    options: [''],
                    reqd: 1,
                    change: function() {
                        sync_uom();
                    }
                },
                {
                    fieldname: 'col_break',
                    fieldtype: 'Column Break'
                },
                {
                    fieldname: 'qty',
                    fieldtype: 'Data',
                    label: __('Allocated Qty (Decimal Text)'),
                    reqd: 1
                },
                {
                    fieldname: 'uom',
                    fieldtype: 'Data',
                    label: __('UOM (from selected lines)'),
                    reqd: 1,
                    read_only: 1
                },
                {
                    fieldname: 'evidence',
                    fieldtype: 'Link',
                    options: 'Fresko Evidence',
                    label: __('Evidence'),
                    reqd: 1
                },
                {
                    fieldname: 'source_event_id',
                    fieldtype: 'Data',
                    label: __('Source Event ID'),
                    reqd: 1,
                    hidden: 1,
                    default: dialog_event_id
                },
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Allocation Reason')
                }
            ],
            primary_action_label: __('Propose Allocation'),
            primary_action: function(values) {
                if (!self.require_live_view()) return;
                var sale_k = d.get_value('sale_line_key');
                var out_k = d.get_value('outward_line_key');
                var s_line = sale_lines_by_key[sale_k];
                var o_line = outward_lines_by_key[out_k];

                if (!sale_k || !s_line) {
                    frappe.msgprint(__('Please select a valid Sale Line.'));
                    return;
                }
                if (!out_k || !o_line) {
                    frappe.msgprint(__('Please select a valid Outward Line.'));
                    return;
                }
                if (s_line.uom && o_line.uom && s_line.uom !== o_line.uom) {
                    frappe.msgprint(__('UOM mismatch: Sale Line UOM (') + s_line.uom + __(') does not match Outward Line UOM (') + o_line.uom + __(').'));
                    return;
                }

                var qty_str = String(d.get_value('qty') || '').trim();
                if (!is_positive_decimal_string(qty_str, 6)) {
                    frappe.msgprint(__('Valid positive decimal quantity required (up to 6 decimal places, no exponents or trailing junk).'));
                    return;
                }

                frappe.call({
                    method: 'fresko_universe.commercial.propose_sale_outward_allocation',
                    args: {
                        sale_name: values.sale_name,
                        sale_line_key: sale_k,
                        outward: values.outward,
                        outward_line_key: out_k,
                        qty: qty_str,
                        uom: values.uom || s_line.uom || o_line.uom,
                        evidence: values.evidence,
                        source_event_id: dialog_event_id,
                        reason: values.reason || null
                    }
                }).then(function(r) {
                    frappe.msgprint(__('Allocation proposed successfully: ') + (r.message ? r.message.name : ''));
                    d.hide();
                    self.load_container_data();
                }).catch(function(err) {
                    frappe.msgprint(__('Allocation proposal failed: ') + (err.message || 'Error'));
                });
            }
        });

        function sync_uom() {
            var s_key = d.get_value('sale_line_key');
            var o_key = d.get_value('outward_line_key');
            var s_line = sale_lines_by_key[s_key];
            var o_line = outward_lines_by_key[o_key];

            var uom = (s_line && s_line.uom) ? s_line.uom : ((o_line && o_line.uom) ? o_line.uom : '');
            d.set_value('uom', uom);

            if (s_line && o_line && s_line.uom && o_line.uom && s_line.uom !== o_line.uom) {
                frappe.msgprint(__('Warning: Mismatched UOM. Sale Line uses ') + s_line.uom + __(', while Outward Line uses ') + o_line.uom);
            }
        }

        function load_sale_lines(sale_name_val) {
            var seq = ++sale_load_seq;
            sale_lines_by_key = {};
            if (!sale_name_val) {
                d.set_df_property('sale_line_key', 'options', ['']);
                d.set_value('sale_line_key', '');
                sync_uom();
                return;
            }

            frappe.call({
                method: 'fresko_universe.commercial.get_sale_current',
                args: { sale_name: sale_name_val }
            }).then(function(r) {
                if (seq !== sale_load_seq) return; // guard stale async response
                var sale_data = r.message;
                var lines = (sale_data && sale_data.lines) ? sale_data.lines : [];
                var options = [{ label: __('-- Select Sale Line --'), value: '' }];
                lines.forEach(function(l) {
                    sale_lines_by_key[l.line_key] = l;
                    var lot_info = l.container_lot || l.raw_lot_text || 'No Lot';
                    var rem = (l.remaining_qty !== undefined && l.remaining_qty !== null) ? (' [Rem: ' + l.remaining_qty + ']') : '';
                    var label = l.line_key + ' | ' + (l.item || '') + ' (' + lot_info + ') - ' + (l.qty !== null ? l.qty : 'UNK') + ' ' + (l.uom || '') + rem;
                    options.push({ label: label, value: l.line_key });
                });
                d.set_df_property('sale_line_key', 'options', options);
                if (lines.length > 0) {
                    d.set_value('sale_line_key', lines[0].line_key);
                } else {
                    d.set_value('sale_line_key', '');
                }
                sync_uom();
            }).catch(function() {
                if (seq !== sale_load_seq) return;
                d.set_df_property('sale_line_key', 'options', ['']);
                d.set_value('sale_line_key', '');
                sync_uom();
            });
        }

        function load_outward_lines(outward_name_val) {
            var seq = ++outward_load_seq;
            outward_lines_by_key = {};
            if (!outward_name_val) {
                d.set_df_property('outward_line_key', 'options', ['']);
                d.set_value('outward_line_key', '');
                sync_uom();
                return;
            }

            frappe.call({
                method: 'fresko_universe.commercial.get_outward_reconciliation',
                args: { outward_name: outward_name_val, as_of: self.as_of_value || null }
            }).then(function(r) {
                if (seq !== outward_load_seq) return; // guard stale async response
                var outward_data = r.message;
                var lines = (outward_data && outward_data.lines) ? outward_data.lines : [];
                var options = [{ label: __('-- Select Outward Line --'), value: '' }];
                lines.forEach(function(ol) {
                    outward_lines_by_key[ol.line_key] = ol;
                    var rem = (ol.remaining_qty !== undefined && ol.remaining_qty !== null) ? (' [Rem: ' + ol.remaining_qty + ']') : '';
                    var label = ol.line_key + ' | ' + ol.qty + ' ' + ol.uom + rem;
                    options.push({ label: label, value: ol.line_key });
                });
                d.set_df_property('outward_line_key', 'options', options);
                if (lines.length > 0) {
                    d.set_value('outward_line_key', lines[0].line_key);
                } else {
                    d.set_value('outward_line_key', '');
                }
                sync_uom();
            }).catch(function() {
                if (seq !== outward_load_seq) return;
                d.set_df_property('outward_line_key', 'options', ['']);
                d.set_value('outward_line_key', '');
                sync_uom();
            });
        }

        d.show();

        var qty_field = d.get_field('qty');
        if (qty_field && qty_field.$input) {
            qty_field.$input.attr('inputmode', 'decimal');
            qty_field.$input.attr('placeholder', '0.000000');
        }

        if (initial_sale_name) {
            load_sale_lines(initial_sale_name);
        }
        if (initial_outward_name) {
            load_outward_lines(initial_outward_name);
        }
    }

    // -----------------------------------------------------
    // Dialog 3: Propose Rate for Sale Line
    // -----------------------------------------------------
    open_propose_rate_dialog(sale, line) {
        if (!this.require_mutation(sale, 'current_version')) return;
        var self = this;
        var dialog_event_id = generate_uuid();
        var d = new frappe.ui.Dialog({
            title: __('Propose Rate for Line: ') + line.line_key,
            fields: [
                {
                    fieldname: 'rate',
                    fieldtype: 'Data',
                    label: __('Proposed Rate (up to 2 decimals)'),
                    reqd: 1
                },
                {
                    fieldname: 'evidence',
                    fieldtype: 'Link',
                    options: 'Fresko Evidence',
                    label: __('Evidence'),
                    reqd: 1
                },
                {
                    fieldname: 'source_event_id',
                    fieldtype: 'Data',
                    label: __('Source Event ID'),
                    reqd: 1,
                    hidden: 1,
                    default: dialog_event_id
                },
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Reason for Rate Proposal'),
                    reqd: 1
                }
            ],
            primary_action_label: __('Propose Rate'),
            primary_action: function(values) {
                if (!self.require_live_view()) return;
                var rate_str = String(d.get_value('rate') || '').trim();
                if (!is_valid_decimal_string(rate_str, 2)) {
                    frappe.msgprint(__('Valid decimal rate (up to 2 decimal places, no exponents or trailing junk) required.'));
                    return;
                }
                frappe.call({
                    method: 'fresko_universe.commercial.propose_rate',
                    args: {
                        sale_name: sale.name,
                        line_key: line.line_key,
                        rate: rate_str,
                        evidence: values.evidence,
                        source_event_id: dialog_event_id,
                        reason: values.reason,
                        expected_version: sale.current_version
                    }
                }).then(function() {
                    frappe.msgprint(__('Rate proposed successfully.'));
                    d.hide();
                    self.load_container_data();
                }).catch(function(err) {
                    frappe.msgprint(__('Failed to propose rate: ') + (err.message || 'Error'));
                });
            }
        });
        d.show();
        var rate_field = d.get_field('rate');
        if (rate_field && rate_field.$input) {
            rate_field.$input.attr('inputmode', 'decimal');
        }
    }

    // -----------------------------------------------------
    // Dialog 4: Propose Alias Mapping
    // -----------------------------------------------------
    open_propose_alias_dialog() {
        if (!this.require_live_view()) return;
        var self = this;
        var dialog_event_id = generate_uuid();
        var d = new frappe.ui.Dialog({
            title: __('Propose Party Alias Mapping'),
            fields: [
                {
                    fieldname: 'company',
                    fieldtype: 'Link',
                    options: 'Company',
                    label: __('Company'),
                    reqd: 1
                },
                {
                    fieldname: 'raw_alias',
                    fieldtype: 'Data',
                    label: __('Raw Exact Alias'),
                    reqd: 1
                },
                {
                    fieldname: 'proposed_customer',
                    fieldtype: 'Link',
                    options: 'Customer',
                    label: __('Proposed Customer'),
                    reqd: 1
                },
                {
                    fieldname: 'evidence',
                    fieldtype: 'Link',
                    options: 'Fresko Evidence',
                    label: __('Evidence'),
                    reqd: 1
                },
                {
                    fieldname: 'source_event_id',
                    fieldtype: 'Data',
                    label: __('Source Event ID'),
                    reqd: 1,
                    hidden: 1,
                    default: dialog_event_id
                },
                {
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    label: __('Reason')
                }
            ],
            primary_action_label: __('Propose Mapping'),
            primary_action: function(values) {
                if (!self.require_live_view()) return;
                var raw_alias_input = d.get_field('raw_alias').$input;
                var raw_alias_val = raw_alias_input ? raw_alias_input.val() : values.raw_alias;
                frappe.call({
                    method: 'fresko_universe.commercial.propose_alias_mapping',
                    args: {
                        company: values.company,
                        raw_alias: raw_alias_val,
                        proposed_customer: values.proposed_customer,
                        evidence: values.evidence,
                        source_event_id: dialog_event_id,
                        reason: values.reason || null
                    }
                }).then(function(r) {
                    frappe.msgprint(__('Alias mapping proposed successfully: ') + (r.message ? r.message.name : ''));
                    d.hide();
                    if (self.active_tab === 'alias') self.load_alias_mappings();
                }).catch(function(err) {
                    frappe.msgprint(__('Failed to propose alias mapping: ') + (err.message || 'Error'));
                });
            }
        });
        d.show();
    }

    // -----------------------------------------------------
    // Backend Workflow Actions (Version guarded)
    // -----------------------------------------------------
    submit_sale(sale) {
        if (!this.require_mutation(sale, 'current_version')) return;
        var self = this;
        frappe.call({
            method: 'fresko_universe.commercial.submit_sale',
            args: { sale_name: sale.name, expected_version: sale.current_version }
        }).then(function() {
            frappe.msgprint(__('Sale submitted successfully.'));
            self.load_container_data();
        }).catch(function(err) {
            frappe.msgprint(__('Submit failed: ') + (err.message || 'Error'));
        });
    }

    verify_sale(sale) {
        if (!this.require_mutation(sale, 'current_version')) return;
        var self = this;
        frappe.call({
            method: 'fresko_universe.commercial.verify_sale',
            args: { sale_name: sale.name, expected_version: sale.current_version }
        }).then(function() {
            frappe.msgprint(__('Sale verified successfully.'));
            self.load_container_data();
        }).catch(function(err) {
            frappe.msgprint(__('Verification failed: ') + (err.message || 'Error'));
        });
    }

    approve_sale(sale) {
        if (!this.require_mutation(sale, 'current_version')) return;
        var self = this;
        frappe.call({
            method: 'fresko_universe.commercial.approve_sale',
            args: { sale_name: sale.name, expected_version: sale.current_version }
        }).then(function() {
            frappe.msgprint(__('Sale approved successfully.'));
            self.load_container_data();
        }).catch(function(err) {
            frappe.msgprint(__('Approval failed: ') + (err.message || 'Error'));
        });
    }

    reject_sale_dialog(sale) {
        if (!this.require_mutation(sale, 'current_version')) return;
        var self = this;
        frappe.prompt([
            { fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }
        ], function(values) {
            if (!self.require_live_view()) return;
            frappe.call({
                method: 'fresko_universe.commercial.reject_sale',
                args: {
                    sale_name: sale.name,
                    reason: values.reason,
                    expected_version: sale.current_version
                }
            }).then(function() {
                frappe.msgprint(__('Sale rejected.'));
                self.load_container_data();
            }).catch(function(err) {
                frappe.msgprint(__('Rejection failed: ') + (err.message || 'Error'));
            });
        }, __('Reject Sale: ') + sale.name, __('Reject'));
    }

    verify_alias(mapping) {
        if (!this.require_mutation(mapping, 'version')) return;
        var self = this;
        frappe.call({
            method: 'fresko_universe.commercial.verify_alias_mapping',
            args: { mapping_name: mapping.name, expected_version: mapping.version }
        }).then(function() {
            frappe.msgprint(__('Alias mapping verified.'));
            self.load_alias_mappings();
        }).catch(function(err) {
            frappe.msgprint(__('Verification failed: ') + (err.message || 'Error'));
        });
    }

    approve_alias(mapping) {
        if (!this.require_mutation(mapping, 'version')) return;
        var self = this;
        frappe.call({
            method: 'fresko_universe.commercial.approve_alias_mapping',
            args: { mapping_name: mapping.name, expected_version: mapping.version }
        }).then(function() {
            frappe.msgprint(__('Alias mapping approved.'));
            self.load_alias_mappings();
        }).catch(function(err) {
            frappe.msgprint(__('Approval failed: ') + (err.message || 'Error'));
        });
    }

    reject_alias_dialog(mapping) {
        if (!this.require_mutation(mapping, 'version')) return;
        var self = this;
        frappe.prompt([
            { fieldname: 'reason', fieldtype: 'Small Text', label: __('Rejection Reason'), reqd: 1 }
        ], function(values) {
            if (!self.require_live_view()) return;
            frappe.call({
                method: 'fresko_universe.commercial.reject_alias_mapping',
                args: {
                    mapping_name: mapping.name,
                    reason: values.reason,
                    expected_version: mapping.version
                }
            }).then(function() {
                frappe.msgprint(__('Alias mapping rejected.'));
                self.load_alias_mappings();
            }).catch(function(err) {
                frappe.msgprint(__('Rejection failed: ') + (err.message || 'Error'));
            });
        }, __('Reject Alias Mapping: ') + mapping.name, __('Reject'));
    }

    // -----------------------------------------------------
    // State Handlers
    // -----------------------------------------------------
    render_loading(msg) {
        this.content_panel.innerHTML = `
            <div class="fresko-state-container">
                <div class="fresko-state-title">${escape_html(msg || __('Loading...'))}</div>
            </div>
        `;
    }

    render_empty_state(msg) {
        this.content_panel.innerHTML = `
            <div class="fresko-state-container">
                <div class="fresko-state-title">${escape_html(msg || __('No data to display'))}</div>
            </div>
        `;
    }

    render_error(msg) {
        this.content_panel.innerHTML = `
            <div class="fresko-state-container" style="color:#c5221f;">
                <div class="fresko-state-title">${__('Error')}</div>
                <div>${escape_html(msg)}</div>
            </div>
        `;
    }

    render_fatal_error(msg) {
        this.page.main.empty().append(`
            <div class="fresko-workspace-container">
                <div class="fresko-section-card" style="border-color:#fad2cf; background:#fff9f9; text-align:center; padding:40px;">
                    <h3 style="color:#c5221f; margin-bottom:8px;">${__('Access Denied')}</h3>
                    <p class="text-muted">${escape_html(msg)}</p>
                </div>
            </div>
        `);
    }
}
