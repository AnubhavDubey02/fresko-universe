/* Fresko read-only authenticated reports. Frappe server is the sole data/ACL authority. */
frappe.pages['fresko-reports'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({parent: wrapper, title: __('Fresko Reports'), single_column: true});
    fresko_reports.mount(page);
};

frappe.pages['fresko-reports'].on_page_show = function() {
    // Desk caches pages: recheck live Company and roles on every revisit.
    if (fresko_reports.page) fresko_reports.load_context();
};

var fresko_reports = {
    page: null, generation: 0, in_flight: false, current: null,
    method: 'fresko_universe.reporting_engine.',
    _root: function() {
        var m = this.page ? this.page.main : null;
        if (!m) return document;
        return (m.jquery || m.get) ? (m[0] || m.get(0)) : m;
    },
    mount: function(page) {
        var me = this; me.page = page;
        var root = me._root();
        root.innerHTML = '<section class="frp-root" aria-label="Fresko authenticated reports">' +
          '<p class="frp-notice">Read-only reports from authorized Fresko ledgers. UNKNOWN is not zero; bank pending is not bank cleared.</p>' +
          '<div class="frp-filters">' +
          '<label>Company <output id="frp-company" aria-live="polite">Loading…</output></label>' +
          '<label>Report<select id="frp-type"><option value="container_stock">Container stock</option><option value="sales">Sales</option><option value="receivables">Receivables</option></select></label>' +
          '<label>Container ID<input id="frp-container" list="frp-container-options" placeholder="Select a permitted container" autocomplete="off"/><datalist id="frp-container-options"></datalist></label>' +
          '<label>As-of date/time (optional, site time)<input id="frp-cutoff" type="datetime-local" step="1" /></label>' +
          '<div class="frp-actions"><button type="button" id="frp-run" class="btn btn-primary">Run report</button>' +
          '<button type="button" id="frp-export" class="btn btn-default" disabled>Download CSV</button>' +
          '<button type="button" id="frp-refresh" class="btn btn-default">Refresh access</button></div></div>' +
          '<p id="frp-status" class="frp-status" role="status" aria-live="polite">Checking permitted company and containers…</p>' +
          '<section id="frp-warnings" aria-label="Report limitations"></section>' +
          '<section id="frp-output" aria-label="Results"></section></section>';
        function el(id) { return root.querySelector('#' + id); }
        ['frp-type', 'frp-container', 'frp-cutoff'].forEach(function(id) {
            el(id).addEventListener('input', function() { me.clear_results('Filters changed. Run the report again.'); });
        });
        el('frp-run').addEventListener('click', function() { me.run(); });
        el('frp-export').addEventListener('click', function() { me.export_csv(); });
        el('frp-refresh').addEventListener('click', function() { me.load_context(); });
        me.load_context();
    },
    el: function(id) { return this._root().querySelector('#' + id); },
    status: function(text) { this.el('frp-status').textContent = text; },
    clear_results: function(message) {
        ++this.generation; this.current = null;
        this.el('frp-export').disabled = true;
        this.el('frp-output').replaceChildren();
        this.el('frp-warnings').replaceChildren();
        if (message) this.status(message);
    },
    args: function() {
        var cutoff = this.el('frp-cutoff').value;
        var args = {report: this.el('frp-type').value, container: this.el('frp-container').value.trim()};
        if (cutoff) args.as_of = cutoff.replace('T', ' ') + (cutoff.length === 16 ? ':00' : '');
        return args;
    },
    call: function(fn, args) {
        // Never accept CSV rows or authority claims from the client.
        return Promise.resolve(frappe.call({method: this.method + fn, args: args || {}})).then(function(reply) {
            if (reply && reply.exc) throw new Error('Read operation unavailable');
            return reply && reply.message;
        });
    },
    load_context: function() {
        var me = this, seq;
        me.clear_results('Checking permitted company and containers…');
        seq = me.generation;
        me.el('frp-run').disabled = true;
        return me.call('get_report_context', {}).then(function(result) {
            if (seq !== me.generation) return;
            if (!result || !result.company || !Array.isArray(result.containers)) throw Error('Unavailable');
            me.el('frp-company').textContent = result.company;
            var options = me.el('frp-container-options'); options.replaceChildren();
            result.containers.forEach(function(c) {
                var option = document.createElement('option');
                option.value = c.name; option.label = c.container_no || c.name;
                options.append(option);
            });
            if (!me.el('frp-container').value && result.containers.length) me.el('frp-container').value = result.containers[0].name;
            me.el('frp-run').disabled = false;
            me.status('Ready — ' + result.containers.length + ' permitted containers listed. Exact ID may also be entered.');
        }).catch(function() {
            if (seq !== me.generation) return;
            me.el('frp-company').textContent = 'Unavailable';
            me.status('Report access unavailable. Check your signed-in role/company grants.');
        });
    },
    run: function() {
        var me = this, args = me.args();
        if (!args.container) { me.clear_results('Select a container.'); return Promise.resolve(); }
        me.clear_results('Loading authorized report…');
        var seq = me.generation;
        me.el('frp-run').disabled = true;
        return me.call('execute_report', args).then(function(data) {
            if (seq !== me.generation) return;
            if (!data || data.read_only !== true || data.report !== args.report || data.container !== args.container ||
                data.company !== me.el('frp-company').textContent || !Array.isArray(data.columns) || !Array.isArray(data.rows)) throw Error('Unexpected server report');
            me.current = {args: args, data: data};
            me.render(data);
            me.el('frp-export').disabled = false;
            me.status('Read-only report ready — ' + data.rows.length + ' rows. Source: ' + data.source_authority);
        }).catch(function() {
            if (seq === me.generation) me.status('Report could not be loaded. No ledger changes were made.');
        }).finally(function() { if (seq === me.generation) me.el('frp-run').disabled = false; });
    },
    render: function(data) {
        var warnings = this.el('frp-warnings'), output = this.el('frp-output');
        warnings.replaceChildren(); output.replaceChildren();
        (data.warnings || []).forEach(function(item) {
            var p = document.createElement('p'); p.className = 'frp-warning'; p.textContent = item; warnings.append(p);
        });
        var meta = document.createElement('p'); meta.className = 'frp-meta';
        meta.textContent = 'Company: ' + data.company + ' · Container: ' + data.container + ' · As-of: ' + data.as_of +
                           ' · Read-only · ' + data.status;
        output.append(meta);
        var wrapper = document.createElement('div'); wrapper.className = 'frp-table-wrap';
        var table = document.createElement('table'); table.className = 'frp-table';
        var thead = document.createElement('thead'), head = document.createElement('tr');
        data.columns.forEach(function(c) { var cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = c.replaceAll('_', ' '); head.append(cell); });
        thead.append(head); table.append(thead);
        var body = document.createElement('tbody');
        data.rows.forEach(function(row) {
            var tr = document.createElement('tr');
            if (row.row_type === 'TOTAL' || row.row_type === 'CURRENCY_TOTAL') tr.className = 'frp-total';
            data.columns.forEach(function(c) {
                var cell = document.createElement('td'), val = row[c];
                cell.setAttribute('data-label', c.replaceAll('_', ' '));
                cell.textContent = val === null || val === undefined || val === '' ? 'UNKNOWN' : String(val);
                if (val === null || val === undefined || val === '') cell.className = 'frp-unknown';
                tr.append(cell);
            }); body.append(tr);
        });
        table.append(body); wrapper.append(table); output.append(wrapper);
    },
    export_csv: function() {
        var me = this, current = me.current;
        if (!current) return Promise.resolve();
        var seq = me.generation;
        me.el('frp-export').disabled = true;
        me.status('Rechecking access and generating server-side CSV…');
        return me.call('export_report_csv', current.args).then(function(file) {
            if (seq !== me.generation || !me.current) return;
            if (!file || file.read_only !== true || !file.filename || !file.filename.endsWith('.csv') ||
                file.mime_type !== 'text/csv;charset=utf-8' || typeof file.content !== 'string') throw Error('Bad export');
            var url = URL.createObjectURL(new Blob([file.content], {type: file.mime_type}));
            var a = document.createElement('a'); a.href = url; a.download = file.filename;
            document.body.append(a); a.click(); a.remove();
            setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
            me.status('CSV downloaded from reauthorized read-only report (' + file.rows + ' rows).');
        }).catch(function() {
            if (seq === me.generation) me.status('CSV export unavailable; no file or ledger changes made.');
        }).finally(function() { if (seq === me.generation && me.current) me.el('frp-export').disabled = false; });
    }
};
