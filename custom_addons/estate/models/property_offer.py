from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class EstatePropertyOffer(models.Model):
    _name = 'estate.property.offer'
    _description = 'Property Offer'
    _order = 'price desc'

    price = fields.Float(required=True)
    partner_id = fields.Many2one('res.partner', required=True)
    property_id = fields.Many2one('estate.property', required=True)
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('accepted', 'Accepted'),
            ('refused', 'Refused'),
        ],
        default='pending'
    )

    # ========================
    # CONSTRAINTS
    # ========================

    @api.constrains('price', 'property_id')
    def _check_offer_price(self):
        for record in self:
            if not record.property_id:
                continue

            other_offers = record.property_id.offer_ids.filtered(
                lambda o: o.id != record.id
            )

            if other_offers:
                max_price = max(other_offers.mapped('price'))
                if record.price <= max_price:
                    raise ValidationError("Offer must be higher than existing offers.")
    # ========================
    # BUSINESS METHODS
    # ========================

    def action_accept(self):
        for record in self:
            record.write({'state': 'accepted'})

            record.property_id.write({
                'buyer_id': record.partner_id.id,
                'state': 'offer'
            })


    def action_refuse(self):
        self.write({'state': 'refused'})