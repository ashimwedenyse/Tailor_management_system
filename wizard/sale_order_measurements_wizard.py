from odoo import models, fields, api

class SaleOrderMeasurementsWizard(models.TransientModel):
    _name = 'sale.order.measurements.wizard'
    _description = 'Enter Tailoring Measurements for Sales Order'

    sale_order_id = fields.Many2one('sale.order', string="Sales Order", required=True)
    measurement_date = fields.Date(string="Measurement Date", default=fields.Date.today)
    chest_size = fields.Float(string="Chest Size")
    waist_size = fields.Float(string="Waist Size")
    height = fields.Float(string="Height")
    fabric_preference = fields.Char(string="Fabric Preference")
    style_preference = fields.Text(string="Style Preference")
    fitting_style = fields.Char(string="Fitting Style")
    measurement_notes = fields.Text(string="Measurement Notes")

    def save_measurements(self):
        """Create a customer.measurements record and link it to the sale order"""
        measurement = self.env['customer.measurements'].create({
            'partner_id': self.sale_order_id.partner_id.id,
            'measurement_date': self.measurement_date,
            'chest_size': self.chest_size,
            'waist_size': self.waist_size,
            'height': self.height,
            'fabric_preference': self.fabric_preference,
            'style_preference': self.style_preference,
        })
        # Link to sale.order
        self.sale_order_id.measurements_id = measurement.id
        # Add fitting style and notes directly on sale order
        self.sale_order_id.fitting_style = self.fitting_style
        self.sale_order_id.measurement_notes = self.measurement_notes
        return {'type': 'ir.actions.act_window_close'}
