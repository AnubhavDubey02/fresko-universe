from frappe.model.document import Document
from fresko_universe.fresko_core.services import money_service


class FreskoPaymentAllocation(Document):
    def validate(self):
        money_service.validate_money_document(self)

    def on_trash(self):
        money_service.forbid_money_delete(self)

    def before_rename(self, olddn, newdn, merge=False):
        money_service.forbid_money_rename(self)
