from typing import Any, Dict, Optional
from playwright.sync_api import Browser, BrowserContext, Locator, Page


class BrowserSession:
    def __init__(
        self,
        browser: Browser,
        base_url: str,
        email: str,
        password: str,
        viewport: Dict[str, int],
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        width = viewport.get("width", 1280)
        height = viewport.get("height", 800)
        is_mobile = width < 500
        self.context: BrowserContext = browser.new_context(
            viewport={"width": width, "height": height},
            is_mobile=is_mobile,
            has_touch=is_mobile,
        )
        self.page: Page = self.context.new_page()
        self._authenticate(email, password)

    def _authenticate(self, email: str, password: str) -> None:
        self.page.goto(f"{self.base_url}/login")
        login_form = self.page.locator("form.form-signin:visible, form:has(input#login_email):visible").first
        login_form.locator("input#login_email").fill(email)
        login_form.locator("input#login_password").fill(password)
        login_form.locator("button[type=submit]").click()
        self.page.wait_for_url(lambda url: "/login" not in url)
        response = self.context.request.get(f"{self.base_url}/api/method/frappe.auth.get_logged_user")
        if not response.ok or response.json().get("message") != email:
            raise AssertionError("Real login did not establish the expected user")

    def goto(self, route: str) -> None:
        clean_route = route.lstrip("/")
        self.page.goto(f"{self.base_url}/{clean_route}")

    def _get_frappe_field_value(self, fieldname: str, dialog: bool) -> Any:
        return self.page.evaluate(
            """([fieldname, dialog]) => {
                if (dialog && window.cur_dialog) {
                    if (window.cur_dialog.fields_dict && window.cur_dialog.fields_dict[fieldname]) {
                        return window.cur_dialog.fields_dict[fieldname].get_value();
                    }
                    if (typeof window.cur_dialog.get_value === 'function') {
                        return window.cur_dialog.get_value(fieldname);
                    }
                } else {
                    const page = (window.frappe && window.frappe.container && window.frappe.container.page) ||
                                 (window.frappe && window.frappe.ui && window.frappe.ui.pages && window.frappe.ui.pages[window.frappe.get_route_str()]);
                    if (page && page.fields_dict && page.fields_dict[fieldname]) {
                        return page.fields_dict[fieldname].get_value();
                    }
                    if (page && page.fresko_workspace && page.fresko_workspace[fieldname + '_field']) {
                        return page.fresko_workspace[fieldname + '_field'].get_value();
                    }
                    if (window.fresko_money && window.fresko_money[fieldname + '_field']) {
                        return window.fresko_money[fieldname + '_field'].get_value();
                    }
                }
                return null;
            }""",
            [fieldname, dialog],
        )

    def _close_active_datepicker(self) -> None:
        """Dismiss any active Frappe datepicker popup through normal user interaction."""
        active_dp = self.page.locator("#datepickers-container .datepicker.active:visible")
        if active_dp.count() > 0:
            self.page.keyboard.press("Escape")
            try:
                active_dp.wait_for(state="hidden", timeout=2000)
            except Exception:
                self.page.evaluate("() => document.activeElement && document.activeElement.blur()")
                active_dp.wait_for(state="hidden", timeout=2000)

    def field(
        self,
        fieldname: str,
        value: Any,
        dialog: bool = False,
        require_autocomplete: bool = False,
    ) -> None:
        scope: Locator
        if dialog:
            scope = self.page.locator(".modal.show:visible, .modal:visible").first
        else:
            # Page fields live in the page head while the app-specific panel is
            # mounted in page.main. Scoping to the first page container misses
            # native Page controls such as Container and As Of.
            scope = self.page.locator("body")

        container = scope.locator(f"div[data-fieldname='{fieldname}']:visible").first
        control = container.locator("input:not([type=hidden]), select, textarea").first
        control.wait_for(state="visible")

        if control.is_disabled() or control.get_attribute("readonly") is not None:
            raise ValueError(f"Field '{fieldname}' is readonly or disabled; cannot modify.")

        tag = control.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            control.select_option(str(value))
        elif container.get_attribute("data-fieldtype") == "Link":
            expected = str(value)
            if control.input_value() == expected:
                committed = self._get_frappe_field_value(fieldname, dialog)
                if committed == expected:
                    return

            control.fill(expected)

            rows = container.locator(".awesomplete ul:visible [role='option']:visible")
            if require_autocomplete:
                rows.first.wait_for(state="visible")
            else:
                try:
                    rows.first.wait_for(state="visible", timeout=600)
                except Exception:
                    pass

            if rows.count() > 0:
                selected = None
                for index in range(rows.count()):
                    candidate = rows.nth(index)
                    text = candidate.inner_text().strip()
                    first_line = text.splitlines()[0].strip() if text else ""
                    if first_line == expected or first_line.startswith(expected + " "):
                        selected = candidate
                        break
                if selected is not None:
                    selected.click()
                elif require_autocomplete:
                    raise AssertionError(
                        f"Frappe Link '{fieldname}' returned suggestions but not the requested value '{expected}'"
                    )

            control.press("Tab")
            self._close_active_datepicker()

            # Verify actual Frappe dialog/control value after commit
            try:
                self.page.wait_for_function(
                    """([fieldname, dialog, expected]) => {
                        let val = null;
                        if (dialog && window.cur_dialog) {
                            if (window.cur_dialog.fields_dict && window.cur_dialog.fields_dict[fieldname]) {
                                val = window.cur_dialog.fields_dict[fieldname].get_value();
                            } else if (typeof window.cur_dialog.get_value === 'function') {
                                val = window.cur_dialog.get_value(fieldname);
                            }
                        } else {
                            const page = (window.frappe && window.frappe.container && window.frappe.container.page) ||
                                         (window.frappe && window.frappe.ui && window.frappe.ui.pages && window.frappe.ui.pages[window.frappe.get_route_str()]);
                            if (page && page.fields_dict && page.fields_dict[fieldname]) {
                                val = page.fields_dict[fieldname].get_value();
                            } else if (page && page.fresko_workspace && page.fresko_workspace[fieldname + '_field']) {
                                val = page.fresko_workspace[fieldname + '_field'].get_value();
                            } else if (window.fresko_money && window.fresko_money[fieldname + '_field']) {
                                val = window.fresko_money[fieldname + '_field'].get_value();
                            }
                        }
                        return val === expected;
                    }""",
                    arg=[fieldname, dialog, expected],
                    timeout=5000,
                )
            except Exception as wait_err:
                actual_val = self._get_frappe_field_value(fieldname, dialog)
                input_val = control.input_value()
                if actual_val != expected:
                    raise AssertionError(
                        f"Frappe Link '{fieldname}' did not commit requested value: control value is {actual_val!r}, input value is {input_val!r}, expected {expected!r}"
                    ) from wait_err

            if control.input_value().strip() != expected:
                raise AssertionError(
                    f"Frappe Link '{fieldname}' visible input value {control.input_value()!r} does not match expected {expected!r}"
                )
        else:
            control.fill(str(value))
            control.press("Tab")
            self._close_active_datepicker()

    def datetime_field(self, fieldname: str, iso_value: str) -> None:
        """Enter a canonical timestamp through Frappe's native display format."""
        container = self.page.locator(f"body div[data-fieldname='{fieldname}']:visible").first
        control = container.locator("input:not([type=hidden])").first
        control.wait_for(state="visible")
        native_value = self.page.evaluate(
            "iso => frappe.datetime.str_to_user(iso)", iso_value
        )
        control.fill(native_value)
        control.press("Tab")
        getter = (
            "frappe.container.page.fresko_workspace.as_of_field.get_value()"
            if fieldname == "as_of"
            else "fresko_money.cutoff_field.get_value()"
        )
        self.page.wait_for_function(
            f"expected => {getter} === expected", arg=iso_value
        )
        actual = self.page.evaluate(f"() => {getter}")
        if actual != iso_value:
            raise AssertionError(
                f"Native Datetime field '{fieldname}' returned {actual!r}, expected canonical ISO value"
            )

        # Close any visible Frappe datepicker through normal user interaction (Escape/blur)
        self._close_active_datepicker()
        if self.page.locator("#datepickers-container .datepicker.active:visible").count() > 0:
            raise AssertionError(
                f"Visible datepicker overlay remained active after Escape/blur for field '{fieldname}'"
            )

    def clear_datetime_field(self, fieldname: str) -> None:
        container = self.page.locator(f"body div[data-fieldname='{fieldname}']:visible").first
        control = container.locator("input:not([type=hidden])").first
        control.wait_for(state="visible")
        control.fill("")
        control.press("Tab")
        getter = (
            "frappe.container.page.fresko_workspace.as_of_field.get_value()"
            if fieldname == "as_of"
            else "fresko_money.cutoff_field.get_value()"
        )
        self.page.wait_for_function(
            f"() => {{ const value = {getter}; return value === null || value === ''; }}"
        )
        actual = self.page.evaluate(f"() => {getter}")
        if actual not in (None, ""):
            raise AssertionError(f"Native Datetime field '{fieldname}' did not clear")
        self._close_active_datepicker()

    def dialog(self, title: Optional[str] = None) -> Locator:
        modal = self.page.locator(".modal.show:visible, .modal:visible").first
        modal.wait_for(state="visible")
        if title:
            modal.locator(".modal-title").filter(has_text=title).wait_for(state="visible")
        return modal

    def click_dialog(self, label: str) -> None:
        modal = self.dialog()
        btn = modal.locator(".modal-footer button:visible, .modal-header button:visible").filter(has_text=label).first
        btn.wait_for(state="visible")
        btn.click()

    def dismiss_messages(self) -> None:
        dialogs = self.page.locator(".msgprint-dialog:visible, .modal:has(.msgprint):visible")
        count = dialogs.count()
        for i in range(count):
            d = dialogs.nth(i)
            close_btn = d.locator("button.btn-modal-close:visible, button[data-dismiss='modal']:visible, .modal-header .close:visible").first
            if close_btn.count() > 0 and close_btn.is_visible():
                close_btn.click()
                d.wait_for(state="hidden")

    def rpc(self, method: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = args or {}
        return self.page.evaluate(
            """async ([method, args]) => {
                return new Promise((resolve) => {
                    if (!window.frappe || !window.frappe.call) {
                        resolve({ ok: false, error_type: 'FrappeUnavailable' });
                        return;
                    }
                    window.frappe.call({
                        method: method,
                        args: args,
                        callback: (r) => {
                            resolve(r && r.exc ? {ok:false, error_type:r.exc_type || 'ServerError'} : { ok: true, message: r ? r.message : null });
                        },
                        error: (r) => {
                            let errorType = 'ServerError';
                            if (r && r.responseJSON && r.responseJSON.exc_type) {
                                errorType = r.responseJSON.exc_type;
                            } else if (r && r._server_messages) {
                                errorType = 'FrappeServerMessage';
                            }
                            resolve({ ok: false, error_type: errorType });
                        }
                    });
                });
            }""",
            [method, payload],
        )

    def close(self) -> None:
        self.context.close()
