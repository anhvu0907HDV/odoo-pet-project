from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class EstatePropertyOffer(models.Model):
    _name = 'estate.property.offer'
    _description = 'Property Offer'
    _order = 'price desc'

    price = fields.Float(required=True)
    partner_id = fields.Many2one('res.partner', required=True)
    property_id = fields.Many2one('estate.property', required=True, ondelete='cascade')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id.id, readonly=True)
    validity = fields.Integer(default=7)
    deadline = fields.Date(compute='_compute_deadline', inverse='_inverse_deadline', store=True)
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('accepted', 'Accepted'),
            ('refused', 'Refused'),
        ],
        default='pending',
        copy=False
    )

    _sql_constraints = [
        ('estate_property_offer_price_positive', 'CHECK(price > 0)', 'Offer price must be greater than 0.'),
        ('estate_property_offer_validity_positive', 'CHECK(validity >= 0)', 'Validity must be 0 or greater.'),
    ]

    # ========================
    # CONSTRAINTS
    # ========================

    @api.depends('create_date', 'validity')
    def _compute_deadline(self):
        for record in self:
            reference_date = fields.Date.context_today(record)
            if record.create_date:
                reference_date = fields.Date.to_date(record.create_date)
            record.deadline = reference_date + timedelta(days=record.validity)

    def _inverse_deadline(self):
        for record in self:
            reference_date = fields.Date.context_today(record)
            if record.create_date:
                reference_date = fields.Date.to_date(record.create_date)
            if record.deadline:
                record.validity = (record.deadline - reference_date).days

    @api.constrains('price', 'property_id', 'state')
    def _check_offer_price(self):
        for record in self:
            if not record.property_id:
                continue
            if record.property_id.state in ('cancel', 'sold'):
                raise ValidationError("You cannot create or update offers for sold/cancelled properties.")

            other_offers = record.property_id.offer_ids.filtered(
                lambda o: o.id != record.id
            )

            if other_offers:
                max_price = max(other_offers.mapped('price'))
                if record.price <= max_price:
                    raise ValidationError("Offer must be higher than existing offers.")

    @api.constrains('state', 'property_id')
    def _check_single_accepted_offer(self):
        for record in self.filtered(lambda offer: offer.state == 'accepted'):
            accepted_offers = record.property_id.offer_ids.filtered(lambda offer: offer.state == 'accepted')
            if len(accepted_offers) > 1:
                raise ValidationError("A property can only have one accepted offer.")

    # ========================
    # BUSINESS METHODS
    # ========================

    def action_accept(self):
        for record in self:
            if record.property_id.state in ('cancel', 'sold'):
                raise UserError("You cannot accept offers for sold/cancelled properties.")

            record.property_id.offer_ids.filtered(
                lambda offer: offer.id != record.id and offer.state != 'refused'
            ).write({'state': 'refused'})

            record.write({'state': 'accepted'})

            record.property_id.write({
                'buyer_id': record.partner_id.id,
                'state': 'offer'
            })

    def action_refuse(self):
        if any(offer.state == 'accepted' for offer in self):
            raise UserError("Cannot refuse an accepted offer. Accept another offer instead.")
        self.write({'state': 'refused'})
