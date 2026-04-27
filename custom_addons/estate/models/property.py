from odoo import models, fields
from odoo.exceptions import UserError,ValidationError
from odoo import api

class EstateProperty(models.Model):
    _name = 'estate.property'
    _description = 'Real Estate Property'
    _order = 'id desc'

    # ========================
    # FIELDS
    # ========================

    name = fields.Char(string="Title", required=True)
    description = fields.Text()
    price = fields.Float(string="Price")
    bedrooms = fields.Integer()
    living_area = fields.Float()
    garden_area = fields.Float()
    total_area = fields.Float(compute='_compute_total_area', store=True)
    
    buyer_id = fields.Many2one('res.partner', string="Buyer")

    state = fields.Selection(
        selection=[
            ('new', 'New'),
            ('offer', 'Offer Received'),
            ('sold', 'Sold'),
            ('cancel', 'Cancelled'),
        ],
        string="Status",
        default='new',
        required=True,
    )

    offer_ids = fields.One2many(
        'estate.property.offer',
        'property_id',
        string="Offers"
    )

    best_price = fields.Float(
        compute='_compute_best_price',
        store=True
    )
    # ========================
    # BUSINESS METHODS
    # ========================

    def action_mark_sold(self):
        self._check_can_be_sold()
        self.write({'state': 'sold'})

    def action_cancel(self):
        self._check_can_be_cancelled()
        self.write({'state': 'cancel'})
    @api.depends('living_area', 'garden_area')
    def _compute_total_area(self):
        for record in self:
            record.total_area = record.living_area + record.garden_area
            
    @api.depends('offer_ids.price')
    def _compute_best_price(self):
        for record in self:
            prices = record.offer_ids.mapped('price')
            record.best_price = max(prices) if prices else 0

    # ========================
    # VALIDATION METHODS
    # ========================

    def _check_can_be_sold(self):
        for record in self:
            if record.state == 'cancel':
                raise UserError("Cancelled property cannot be sold.")

    def _check_can_be_cancelled(self):
        for record in self:
            if record.state == 'sold':
                raise UserError("Sold property cannot be cancelled.")
    @api.constrains('price')
    def _check_price(self):
        for record in self:
            if record.price <= 0:
                raise ValidationError("Price must be greater than 0.")