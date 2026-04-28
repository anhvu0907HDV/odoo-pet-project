from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class EstateProperty(models.Model):
    _name = 'estate.property'
    _description = 'Real Estate Property'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'estate.notification.mixin']
    _order = 'id desc, expected_price desc'
    _check_company_auto = True

    name = fields.Char(string='Title', required=True, tracking=True)
    description = fields.Text()
    active = fields.Boolean(default=True)

    expected_price = fields.Float(string='Expected Price', required=True, tracking=True)
    selling_price = fields.Float(string='Selling Price', readonly=True, copy=False, tracking=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)

    bedrooms = fields.Integer()
    living_area = fields.Float()
    garden_area = fields.Float()
    total_area = fields.Float(compute='_compute_total_area', store=True)
    availability_date = fields.Date(default=lambda self: fields.Date.today() + timedelta(days=90), copy=False)
    sold_date = fields.Date(copy=False, readonly=True)

    property_type_id = fields.Many2one('estate.property.type', string='Property Type', tracking=True)
    tag_ids = fields.Many2many('estate.property.tag', string='Tags')

    buyer_id = fields.Many2one('res.partner', string='Buyer', copy=False, tracking=True)
    salesperson_id = fields.Many2one('res.users', string='Salesperson', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    state = fields.Selection(
        selection=[
            ('new', 'New'),
            ('offer', 'Offer Received'),
            ('sold', 'Sold'),
            ('cancel', 'Cancelled'),
        ],
        string='Status',
        default='new',
        required=True,
        copy=False,
        tracking=True,
    )

    offer_ids = fields.One2many('estate.property.offer', 'property_id', string='Offers')
    best_price = fields.Float(compute='_compute_best_price', store=True, string='Best Offer')
    offer_count = fields.Integer(compute='_compute_offer_count')
    ai_recommended_offer_id = fields.Many2one('estate.property.offer', string='AI Recommended Offer', copy=False)
    ai_recommendation_confidence = fields.Float(string='AI Confidence', digits=(16, 2), copy=False)
    ai_recommendation_text = fields.Text(string='AI Recommendation Note', copy=False)
    ai_provider = fields.Char(string='AI Provider', copy=False)
    ai_last_analysis_at = fields.Datetime(string='AI Last Analysis', copy=False)

    _sql_constraints = [
        ('estate_property_expected_price_positive', 'CHECK(expected_price > 0)', 'Expected price must be greater than 0.'),
        ('estate_property_selling_price_positive', 'CHECK(selling_price >= 0)', 'Selling price cannot be negative.'),
    ]

    def action_mark_sold(self):
        self.ensure_one()
        self._check_manager_permission('mark properties as sold')
        self._check_can_be_sold()
        self.write({'state': 'sold', 'sold_date': fields.Date.today()})
        return self._notify_action('Property marked as sold.', 'success')

    def action_cancel(self):
        self.ensure_one()
        self._check_can_be_cancelled()
        self.write({
            'state': 'cancel',
            'sold_date': False,
            'buyer_id': False,
            'selling_price': 0,
        })
        return self._notify_action('Property has been cancelled.', 'warning')

    def action_archive_property(self):
        self.ensure_one()
        if not self.active:
            return self._notify_action('Property is already archived.', 'info')
        self.active = False
        return self._notify_action('Property archived.', 'warning')

    def action_unarchive_property(self):
        self.ensure_one()
        if self.active:
            return self._notify_action('Property is already active.', 'info')
        self.active = True
        return self._notify_action('Property unarchived.', 'success')

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

    def action_ai_recommend_offer(self):
        self.ensure_one()
        recommendation = self.env['estate.ai.service'].recommend_offer(self)
        offer = recommendation['offer']
        self.write({
            'ai_recommended_offer_id': offer.id,
            'ai_recommendation_confidence': recommendation.get('confidence', 0),
            'ai_recommendation_text': recommendation.get('reasoning'),
            'ai_provider': recommendation.get('provider'),
            'ai_last_analysis_at': fields.Datetime.now(),
        })
        message = (
            f"AI recommends offer #{offer.id} ({offer.partner_id.display_name}) "
            f"at {offer.price}. Confidence: {self.ai_recommendation_confidence}%."
        )
        return self._notify_action(message, 'info')

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

    def _check_can_be_sold(self):
        for record in self:
            if record.state == 'cancel':
                raise UserError('Cancelled property cannot be sold.')
            if record.state == 'sold':
                raise UserError('Property is already sold.')
            accepted_offer = record.offer_ids.filtered(lambda offer: offer.state == 'accepted')[:1]
            if not accepted_offer:
                raise UserError('You can only mark a property as sold after accepting at least one offer.')
            record.selling_price = accepted_offer.price
            record.buyer_id = accepted_offer.partner_id

    def _check_can_be_cancelled(self):
        for record in self:
            if record.state == 'sold':
                raise UserError('Sold property cannot be cancelled.')

    def _check_manager_permission(self, action_label):
        if not self.env.user.has_group('estate.group_estate_manager'):
            raise UserError(f'Only Estate Manager can {action_label}.')

    @api.constrains('expected_price')
    def _check_expected_price(self):
        for record in self:
            if record.expected_price <= 0:
                raise ValidationError('Expected price must be greater than 0.')

    @api.constrains('selling_price', 'expected_price')
    def _check_selling_price_threshold(self):
        for record in self:
            if not record.selling_price:
                continue
            if record.selling_price < record.expected_price * 0.9:
                raise ValidationError('Selling price cannot be lower than 90% of expected price.')
