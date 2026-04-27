from odoo import models, fields, api
from odoo.exceptions import ValidationError


class EstatePropertyOffer(models.Model):
    _name = 'estate.property.offer'
    _description = 'Property Offer'
    _order = 'price desc'

    price = fields.Float(required=True)
    partner_id = fields.Many2one('res.partner', required=True)
    property_id = fields.Many2one('estate.property', required=True)

    # ========================
    # CONSTRAINT
    # ========================

    @api.constrains('price')
    def _check_offer_price(self):
        for record in self:
            if record.property_id and record.price <= record.property_id.best_price:
                raise ValidationError("Offer must be higher than existing offers.")