from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class EstatePropertyOffer(models.Model):
    _name = 'estate.property.offer'
    _description = 'Property Offer'
    _inherit = ['estate.notification.mixin']
    _order = 'price desc'

    price = fields.Float(required=True)
    partner_id = fields.Many2one('res.partner', required=True)
    property_id = fields.Many2one('estate.property', required=True, ondelete='cascade')
    currency_id = fields.Many2one('res.currency', related='property_id.currency_id', readonly=True)
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

    @api.model_create_multi
    def create(self, vals_list):
        offers = super().create(vals_list)
        properties = offers.mapped('property_id').filtered(lambda property_record: property_record.state == 'new')
        properties.write({'state': 'offer'})
        return offers

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
        self.ensure_one()
        self._check_manager_permission('accept offers')
        if self.property_id.state in ('cancel', 'sold'):
            raise UserError("You cannot accept offers for sold/cancelled properties.")

        self.property_id.offer_ids.filtered(
            lambda offer: offer.id != self.id and offer.state != 'refused'
        ).write({'state': 'refused'})

        self.write({'state': 'accepted'})

        self.property_id.write({
            'buyer_id': self.partner_id.id,
            'selling_price': self.price,
            'state': 'offer',
        })
        return self._notify_action("Offer accepted successfully.", "success")

    def action_refuse(self):
        self.ensure_one()
        if self.state == 'accepted':
            raise UserError("Cannot refuse an accepted offer. Accept another offer instead.")
        self.write({'state': 'refused'})
        self._sync_property_state_after_refuse()
        return self._notify_action("Offer has been refused.", "warning")

    def action_set_pending(self):
        self.ensure_one()
        if self.state == 'pending':
            return self._notify_action("Offer is already pending.", "info")
        if self.state == 'accepted':
            raise UserError("Cannot reset an accepted offer to pending.")
        self.write({'state': 'pending'})
        if self.property_id.state == 'new':
            self.property_id.state = 'offer'
        return self._notify_action("Offer moved back to pending.", "info")

    def _sync_property_state_after_refuse(self):
        self.ensure_one()
        remaining_active_offers = self.property_id.offer_ids.filtered(lambda offer: offer.state in ('pending', 'accepted'))
        if not remaining_active_offers and self.property_id.state == 'offer':
            self.property_id.write({'state': 'new', 'buyer_id': False, 'selling_price': 0})

    def _check_manager_permission(self, action_label):
        if not self.env.user.has_group('estate.group_estate_manager'):
            raise UserError(f'Only Estate Manager can {action_label}.')
