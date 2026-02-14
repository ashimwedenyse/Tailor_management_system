# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.tools.translate import _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round, float_compare

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # ------------------------------------------------------------
    # Only required fields
    # ------------------------------------------------------------
    delivery_date = fields.Datetime(string="Delivery Date")

    advance_payment = fields.Monetary(
        string="Advance Payment",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )

    remaining_amount = fields.Monetary(
        string="Remaining Amount",
        currency_field="currency_id",
        compute="_compute_remaining_amount",
        store=True,
        readonly=True,
    )

    @api.depends("amount_total")
    def _compute_remaining_amount(self):
        """
        After we add down payment deduction line, amount_total becomes the remaining amount.
        """
        for order in self:
            order.remaining_amount = max(order.amount_total or 0.0, 0.0)

    measurements_ids = fields.One2many(
        "customer.measurements",
        "sale_order_id",
        string="Customer Measurements",
    )

    latest_measurement_id = fields.Many2one(
        "customer.measurements",
        string="Latest Measurement",
        compute="_compute_latest_measurement",
        store=False,
        readonly=True,
    )

    def _compute_latest_measurement(self):
        Measurements = self.env["customer.measurements"]
        for order in self:
            meas = Measurements.search(
                [("sale_order_id", "=", order.id)],
                order="create_date desc, id desc",
                limit=1,
            )
            if not meas and order.partner_id:
                meas = Measurements.search(
                    [("partner_id", "=", order.partner_id.id)],
                    order="create_date desc, id desc",
                    limit=1,
                )
            order.latest_measurement_id = meas.id if meas else False

    # ------------------------------------------------------------
    # Add measurement popup
    # ------------------------------------------------------------
    def action_open_measurements_wizard(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Please select a customer first."))

        return {
            "name": _("Add Measurement"),
            "type": "ir.actions.act_window",
            "res_model": "customer.measurements",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_partner_id": self.partner_id.id,
                "default_sale_order_id": self.id,
                "default_measurement_date": fields.Date.today(),
            },
        }

    # ------------------------------------------------------------
    # ADVANCE PAYMENT INVOICE (Odoo 19)
    # ------------------------------------------------------------
    def _get_down_payment_product(self):
        Product = self.env["product.product"].sudo()
        product = Product.search([
            ("name", "=", "Down Payment"),
            ("sale_ok", "=", True),
            ("type", "=", "service"),
        ], limit=1)
        if product:
            return product

        return Product.create({
            "name": "Down Payment",
            "type": "service",
            "sale_ok": True,
            "purchase_ok": False,
            "invoice_policy": "order",
        })

    def _get_existing_draft_advance_invoice(self):
        self.ensure_one()
        drafts = self.invoice_ids.filtered(lambda m: m.move_type == "out_invoice" and m.state == "draft")
        for inv in drafts:
            if any(
                line.sale_line_ids and any(sl.is_downpayment for sl in line.sale_line_ids)
                for line in inv.invoice_line_ids
            ):
                return inv
        return False

    def _compute_base_from_total_included(self, taxes, total_included, currency, product=None, partner=None):
        """
        Compute untaxed base such that total_included matches after taxes.
        Keep more precision (6 decimals) to reduce rounding drift.
        """
        total_included = float(total_included or 0.0)
        if total_included <= 0:
            return 0.0

        if not taxes:
            return float_round(total_included, precision_digits=6)

        def _ti(base):
            res = taxes.compute_all(base, currency=currency, quantity=1.0, product=product, partner=partner)
            return float(res.get("total_included", 0.0))

        low = 0.0
        high = total_included
        for _ in range(25):
            if _ti(high) >= total_included:
                break
            high *= 2.0

        for _ in range(60):
            mid = (low + high) / 2.0
            if _ti(mid) >= total_included:
                high = mid
            else:
                low = mid

        return float_round(high, precision_digits=6)

    def _ensure_invoice_total_equals_advance(self, invoice):
        """
        If invoice total is off by a small rounding amount (0.01),
        add a rounding adjustment line (no tax) so invoice total becomes exact.
        """
        self.ensure_one()
        currency = self.currency_id
        expected = currency.round(self.advance_payment)
        got = currency.round(invoice.amount_total)

        if expected == got:
            return

        diff = currency.round(expected - got)
        if abs(diff) > (currency.rounding * 5):
            raise UserError(_(
                "Advance invoice total (%.2f) is too far from Advance Payment (%.2f). "
                "Check your tax configuration."
            ) % (got, expected))

        invoice.write({
            "invoice_line_ids": [(0, 0, {
                "name": _("Rounding Adjustment"),
                "quantity": 1.0,
                "price_unit": diff,
                "tax_ids": [(6, 0, [])],
            })]
        })
        invoice._compute_amount()

        got2 = currency.round(invoice.amount_total)
        if got2 != expected:
            raise UserError(_(
                "Could not adjust rounding. Invoice total (%.2f) still doesn't match Advance Payment (%.2f)."
            ) % (got2, expected))

    def action_create_advance_payment_invoice(self):
        """
        ✅ Customer pays advance_payment now (invoice total exactly equals advance_payment)
        ✅ Sale Order totals reduce immediately using a DOWN PAYMENT line:
           - We use NEGATIVE QUANTITY (-1) with POSITIVE PRICE (important!)
           - This avoids Odoo double-negative on the final invoice.
        """
        self.ensure_one()
        _logger.warning("### ADVANCE INVOICE LOGIC RUNNING for %s (advance=%s) ###", self.name, self.advance_payment)

        if self.state == "cancel":
            raise UserError(_("You cannot create an advance invoice for a cancelled order."))
        if not self.partner_id:
            raise UserError(_("Please select a customer first."))
        if not self.advance_payment or self.advance_payment <= 0:
            raise UserError(_("Please set an Advance Payment amount greater than 0."))

        down_payment_product = self._get_down_payment_product()

        # taxes from product mapped by fiscal position
        taxes = down_payment_product.taxes_id.filtered(lambda t: t.company_id == self.company_id and t.active)
        if self.fiscal_position_id:
            taxes = self.fiscal_position_id.map_tax(taxes, down_payment_product, self.partner_shipping_id)
        taxes = taxes.browse(list(set(taxes.ids)))

        # compute POSITIVE invoice price_unit so total incl tax ~ advance_payment
        if taxes and all(t.price_include for t in taxes):
            invoice_price_unit = float_round(self.advance_payment, precision_digits=6)
        else:
            invoice_price_unit = self._compute_base_from_total_included(
                taxes=taxes,
                total_included=self.advance_payment,
                currency=self.currency_id,
                product=down_payment_product,
                partner=self.partner_id,
            )

        # ✅ CRITICAL FIX:
        # SO line must reduce totals, but DO NOT use negative price_unit
        # because Odoo uses negative quantity on the final invoice.
        so_qty = -1.0
        so_price_unit = abs(invoice_price_unit)  # keep positive

        # ------------------------------------------------------------
        # A) Create or FIX existing down payment SO line
        # ------------------------------------------------------------
        dp_lines = self.order_line.filtered(lambda l: l.is_downpayment and l.product_id == down_payment_product)
        if dp_lines:
            dp_line = dp_lines[-1]
            dp_line.write({
                "name": _("Advance Payment for %s") % self.name,
                "product_uom_qty": so_qty,           # ✅ NEGATIVE QTY
                "price_unit": so_price_unit,         # ✅ POSITIVE PRICE
                "tax_ids": [(6, 0, taxes.ids)],
            })
            extras = dp_lines[:-1]
            if extras:
                extras.unlink()
        else:
            dp_line = self.env["sale.order.line"].create({
                "order_id": self.id,
                "name": _("Advance Payment for %s") % self.name,
                "product_id": down_payment_product.id,
                "product_uom_qty": so_qty,           # ✅ NEGATIVE QTY
                "product_uom_id": down_payment_product.uom_id.id,
                "price_unit": so_price_unit,         # ✅ POSITIVE PRICE
                "is_downpayment": True,
                "tax_ids": [(6, 0, taxes.ids)],
            })

        # ------------------------------------------------------------
        # B) Create OR UPDATE draft invoice (customer pays POSITIVE)
        # ------------------------------------------------------------
        existing = self._get_existing_draft_advance_invoice()
        if existing:
            inv_line = existing.invoice_line_ids[:1]
            if inv_line:
                inv_line.write({
                    "name": dp_line.name,
                    "product_id": down_payment_product.id,
                    "quantity": 1.0,
                    "product_uom_id": dp_line.product_uom_id.id,
                    "price_unit": invoice_price_unit,  # ✅ POSITIVE
                    "tax_ids": [(6, 0, taxes.ids)],
                    "sale_line_ids": [(6, 0, [dp_line.id])],
                })
            else:
                existing.write({
                    "invoice_line_ids": [(0, 0, {
                        "name": dp_line.name,
                        "product_id": down_payment_product.id,
                        "quantity": 1.0,
                        "product_uom_id": dp_line.product_uom_id.id,
                        "price_unit": invoice_price_unit,
                        "tax_ids": [(6, 0, taxes.ids)],
                        "sale_line_ids": [(6, 0, [dp_line.id])],
                    })]
                })
            existing._compute_amount()
            self._ensure_invoice_total_equals_advance(existing)

            return {
                "type": "ir.actions.act_window",
                "name": _("Advance Payment Invoice"),
                "res_model": "account.move",
                "view_mode": "form",
                "res_id": existing.id,
            }

        Move = self.env["account.move"]
        invoice = Move.create({
            "move_type": "out_invoice",
            "partner_id": self.partner_invoice_id.id,
            "invoice_origin": self.name,
            "invoice_user_id": self.user_id.id,
            "currency_id": self.currency_id.id,
            "company_id": self.company_id.id,
            "invoice_payment_term_id": self.payment_term_id.id if self.payment_term_id else False,
            "invoice_line_ids": [
                (0, 0, {
                    "name": dp_line.name,
                    "product_id": down_payment_product.id,
                    "quantity": 1.0,
                    "product_uom_id": dp_line.product_uom_id.id,
                    "price_unit": invoice_price_unit,  # ✅ POSITIVE
                    "tax_ids": [(6, 0, taxes.ids)],
                    "sale_line_ids": [(6, 0, [dp_line.id])],
                })
            ],
        })

        invoice._compute_amount()
        self._ensure_invoice_total_equals_advance(invoice)

        self.message_post(body=_("Advance Payment Invoice created: %s") % (invoice.name or invoice.display_name))

        return {
            "type": "ir.actions.act_window",
            "name": _("Advance Payment Invoice"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": invoice.id,
        }

    # ------------------------------------------------------------
    # Sync Sales Order -> Tailor Order
    # ------------------------------------------------------------
    def write(self, vals):
        res = super(SaleOrder, self).write(vals)

        sync_keys = {"partner_id", "delivery_date", "advance_payment"}
        if sync_keys.intersection(vals.keys()):
            TailorOrder = self.env["tailor.order"]
            for so in self:
                to = TailorOrder.search([("sale_order_id", "=", so.id)], limit=1)
                if to:
                    update_vals = {}
                    if "partner_id" in vals:
                        update_vals["partner_id"] = so.partner_id.id
                    if "delivery_date" in vals:
                        update_vals["delivery_date"] = so.delivery_date
                    if "advance_payment" in vals:
                        update_vals["advance_payment_input"] = so.advance_payment or 0.0
                    to.sudo().write(update_vals)

        return res
