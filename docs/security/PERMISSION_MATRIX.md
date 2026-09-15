# PERMISSION_MATRIX — Fresko Universe

**Status:** living · verify against DocType permissions + whitelisted methods (backend), never UI alone.

## Roles (current / planned)

| Role | Notes |
|---|---|
| System Manager | Platform admin — treat as break-glass |
| Fresko Approver | Commercial approval / counter decisions (not accept_counter) |
| Fresko Salesperson | Originator path; accept_counter when assigned |
| Owner / Admin (D10) | Oversell override — System Manager only in current lock |
| Partner / Operations / Accountant / Warehouse / Viewer / External Buyer | Later phases — mark UNKNOWN until implemented |

## Sensitive actions (template — fill with evidence)

| Action | View | Create | Modify | Approve | Delete | Export | Backend enforcement evidence |
|---|---|---|---|---|---|---|---|
| Deal commercial fields after lock | | | | | | | |
| `accept_counter` | | | | | | | |
| Oversell override | | | | | | | |
| Material revision | | | | | | | |
| Exception open/close | | | | | | | |
| Evidence attach | | | | | | | |

Populate from DocType JSON `permissions`, `has_permission`, and `@frappe.whitelist` guards.
