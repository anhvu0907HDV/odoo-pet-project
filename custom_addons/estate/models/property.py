from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

class EstateProperty(models.Model):
    _name = 'estate.property'
    _description = 'Real Estate Property'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc, price desc'
    _check_company_auto = True

    # ========================
    # FIELDS
    # ========================

    name = fields.Char(string="Title", required=True, tracking=True)
    description = fields.Text()
    active = fields.Boolean(default=True)
    price = fields.Float(string="Expected Price", tracking=True)
    bedrooms = fields.Integer()
    living_area = fields.Float()
    garden_area = fields.Float()
    total_area = fields.Float(compute='_compute_total_area', store=True)
    buyer_id = fields.Many2one('res.partner', string="Buyer", copy=False, tracking=True)
    salesperson_id = fields.Many2one('res.users', string='Salesperson', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

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
        copy=False,
        tracking=True
    )

    offer_ids = fields.One2many(
        'estate.property.offer',
        'property_id',
        string="Offers"
    )

    best_price = fields.Float(
        compute='_compute_best_price',
        store=True,
        string='Best Offer'
    )

    offer_count = fields.Integer(
        compute='_compute_offer_count'
    )

    _sql_constraints = [
        ('estate_property_price_positive', 'CHECK(price > 0)', 'Expected price must be greater than 0.'),
    ]
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

    @api.depends('offer_ids.price', 'offer_ids.state')
    def _compute_best_price(self):
        for record in self:
            prices = record.offer_ids.filtered(lambda offer: offer.state != 'refused').mapped('price')
            record.best_price = max(prices) if prices else 0

    @api.depends('offer_ids')
    def _compute_offer_count(self):
        for record in self:
            record.offer_count = len(record.offer_ids)

    def action_view_offers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Offers - {self.name}',
            'res_model': 'estate.property.offer',
            'view_mode': 'tree,form',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
        }
    # ========================
    # VALIDATION METHODS
    # ========================

    def _check_can_be_sold(self):
        for record in self:
            if record.state == 'cancel':
                raise UserError("Cancelled property cannot be sold.")
            if record.state == 'sold':
                raise UserError("Property is already sold.")
            accepted_offer = record.offer_ids.filtered(lambda offer: offer.state == 'accepted')
            if not accepted_offer:
                raise UserError("You can only mark a property as sold after accepting at least one offer.")

    def _check_can_be_cancelled(self):
        for record in self:
            if record.state == 'sold':
                raise UserError("Sold property cannot be cancelled.")

    @api.constrains('price')
    def _check_price(self):
        for record in self:
            if record.price <= 0:
                raise ValidationError("Price must be greater than 0.")
