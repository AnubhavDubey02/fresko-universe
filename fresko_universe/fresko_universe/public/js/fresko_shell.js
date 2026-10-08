/* Fresko Clear — Shell Controller & Navigation Guard */
(function() {
  'use strict';

  function init_fresko_shell() {
    if (typeof frappe === 'undefined') return;

    var fresko = frappe.boot && frappe.boot.fresko;
    var is_operator = Boolean(fresko && fresko.is_operator);

    // 1. Scoped Body Tagging & Bottom Nav Manager
    function update_shell_scope() {
      var current_fresko = frappe.boot && frappe.boot.fresko;
      var is_op = Boolean(current_fresko && current_fresko.is_operator);
      var route = (frappe.get_route && frappe.get_route()) || [];
      var page_name = route[0] || '';
      var is_fresko_page = page_name.indexOf('fresko-') === 0;

      if (document.body) {
        if (is_op && is_fresko_page) {
          document.body.classList.add('fresko-operator-shell');
        } else {
          document.body.classList.remove('fresko-operator-shell');
        }
      }

      ensure_bottom_nav(current_fresko, is_fresko_page, page_name);
    }

    // 2. Mobile Bottom Navigation Element
    function ensure_bottom_nav(fresko_data, is_fresko_page, current_page) {
      var existing_nav = document.querySelector('.fresko-bottom-nav');
      if (!fresko_data || !fresko_data.is_operator || !is_fresko_page) {
        if (existing_nav) {
          existing_nav.style.display = 'none';
        }
        return;
      }

      if (!existing_nav) {
        existing_nav = document.createElement('nav');
        existing_nav.className = 'fresko-bottom-nav';

        var caps = fresko_data.capabilities || [];
        var allowed = fresko_data.allowed_routes || [];
        var can_access_money = (caps.indexOf('view_money') !== -1) || (allowed.indexOf('fresko-money') !== -1);

        // Workspace nav item
        var ws_item = document.createElement('a');
        ws_item.className = 'fresko-bottom-nav-item';
        ws_item.dataset.route = 'fresko-workspace';
        ws_item.href = '#';
        ws_item.innerHTML = '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg><span>Workspace</span>';
        ws_item.addEventListener('click', function(e) {
          e.preventDefault();
          frappe.set_route('fresko-workspace');
        });
        existing_nav.appendChild(ws_item);

        if (can_access_money) {
          var money_item = document.createElement('a');
          money_item.className = 'fresko-bottom-nav-item';
          money_item.dataset.route = 'fresko-money';
          money_item.href = '#';
          money_item.innerHTML = '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg><span>Money</span>';
          money_item.addEventListener('click', function(e) {
            e.preventDefault();
            frappe.set_route('fresko-money');
          });
          existing_nav.appendChild(money_item);
        }

        document.body.appendChild(existing_nav);
      }

      existing_nav.style.display = 'flex';
      var items = existing_nav.querySelectorAll('.fresko-bottom-nav-item');
      items.forEach(function(item) {
        if (item.dataset.route === current_page) {
          item.classList.add('active');
        } else {
          item.classList.remove('active');
        }
      });
    }

    // 3. Soft-keyboard focus listener for mobile devices
    document.addEventListener('focusin', function(e) {
      var tag = e.target && e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
        document.body.classList.add('keyboard-open');
      }
    });

    document.addEventListener('focusout', function(e) {
      var tag = e.target && e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
        document.body.classList.remove('keyboard-open');
      }
    });

    // 4. Initial Route Evaluation and Redirection
    function check_initial_redirect() {
      var current_fresko = frappe.boot && frappe.boot.fresko;
      if (!current_fresko || !current_fresko.is_operator || !current_fresko.default_route) return;

      var route = (frappe.get_route && frappe.get_route()) || [];
      var is_empty_or_workspace = !route || route.length === 0 ||
        route[0] === '' || (route[0] === 'Workspaces' && !route[1]);

      if (is_empty_or_workspace) {
        var user = (frappe.session && frappe.session.user) || 'current';
        var storage_key = 'fresko_initial_routed_' + user;
        if (!sessionStorage.getItem(storage_key)) {
          sessionStorage.setItem(storage_key, 'true');
          frappe.set_route(current_fresko.default_route);
        }
      }
    }

    // Run initial scope check and redirect immediately on load
    update_shell_scope();
    check_initial_redirect();

    // 5. User-Scoped Dual-Layer Router Guard on Route Change
    if (frappe.router) {
      frappe.router.on('change', function() {
        update_shell_scope();
        check_initial_redirect();
      });
    }
  }

  // Hook into Frappe initialization
  if (typeof $ !== 'undefined') {
    $(document).ready(init_fresko_shell);
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init_fresko_shell);
  } else {
    init_fresko_shell();
  }
})();
