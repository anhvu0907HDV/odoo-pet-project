import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class EstatePropertyOffer(models.Model):
    _name = 'estate.property.offer'
    _description = 'Property Offer'
    _inherit = ['estate.notification.mixin']
    _order = 'price desc'
    _check_company_auto = True

    price = fields.Float(required=True)
    partner_id = fields.Many2one('res.partner', required=True, check_company=True)
    property_id = fields.Many2one('estate.property', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one('res.company', related='property_id.company_id', store=True, readonly=True)
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
            if record.state == 'refused':
                continue
            if record.property_id.state in ('cancel', 'sold'):
                raise ValidationError("You cannot create or update offers for sold/cancelled properties.")

            other_offers = record.property_id.offer_ids.filtered(
                lambda offer_record: offer_record.id != record.id and offer_record.state in ('pending', 'accepted')
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
        _logger.info(f'=== DEBUG: action_accept called for offer {self.id} ===')
        self._check_manager_permission('accept offers')
        if self.property_id.state in ('cancel', 'sold'):
            raise UserError("You cannot accept offers for sold/cancelled properties.")

        refused_offers = self.property_id.offer_ids.filtered(
            lambda offer: offer.id != self.id and offer.state != 'refused'
        )
        refused_offers.write({'state': 'refused'})

        self.write({'state': 'accepted'})

        self.property_id.write({
            'buyer_id': self.partner_id.id,
            'selling_price': self.price,
            'state': 'offer',
        })
        _logger.info(f'=== DEBUG: About to send email for accepted offer ===')
        self._send_offer_email('estate.email_template_offer_accepted')
        _logger.info(f'=== DEBUG: About to send email for refused offers ===')
        refused_offers._send_offer_email('estate.email_template_offer_refused')
        return self._notify_action("Offer accepted successfully.", "success")

    def action_refuse(self):
        self.ensure_one()
        self._check_manager_permission('refuse offers')
        if self.state == 'accepted':
            raise UserError("Cannot refuse an accepted offer. Accept another offer instead.")
        self.write({'state': 'refused'})
        self._sync_property_state_after_refuse()
        self._send_offer_email('estate.email_template_offer_refused')
        return self._notify_action("Offer has been refused.", "warning")

    def action_set_pending(self):
        self.ensure_one()
        self._check_manager_permission('set offers to pending')
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

    def _send_offer_email(self, template_xmlid):
        _logger.info(f'=== DEBUG: _send_offer_email called with template: {template_xmlid} ===')
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        _logger.info(f'Template found: {template}')
        if not template:
            _logger.warning(f'Mail template not found: {template_xmlid}')
            return
        
        # Filter offers with valid email
        offers_with_email = self.filtered(lambda offer_record: offer_record.partner_id.email)
        _logger.info(f'Offers with email: {len(offers_with_email)}')
        
        for offer in offers_with_email:
            partner_email = offer.partner_id.email
            _logger.info(f'Sending email to {offer.partner_id.name} ({partner_email}) for offer {offer.id}')
            
            try:
                # Manually render template with offer data
                property_name = offer.property_id.name or 'Unknown Property'
                partner_name = offer.partner_id.name or 'Customer'
                price = offer.price
                currency = offer.currency_id.name if offer.currency_id else 'USD'
                
                if 'accepted' in template_xmlid:
                    subject = f'Your offer for {property_name} was accepted'
                    body = f'''
<div>
    <p>Hello {partner_name},</p>
    <p>Your offer for <strong>{property_name}</strong> has been accepted.</p>
    <ul>
        <li>Offer price: {price:,.0f} {currency}</li>
        <li>Property: {property_name}</li>
    </ul>
    <p>Our team will contact you for next steps.</p>
</div>
'''
                elif 'refused' in template_xmlid:
                    subject = f'Update on your offer for {property_name}'
                    body = f'''
<div>
    <p>Hello {partner_name},</p>
    <p>Thank you for your interest in <strong>{property_name}</strong>.</p>
    <p>We regret to inform you that your current offer was not selected.</p>
    <p>If still interested, you can contact our team and submit a new offer.</p>
</div>
'''
                else:
                    subject = f'Reminder: your offer for {property_name} expires soon'
                    deadline = offer.deadline or 'N/A'
                    body = f'''
<div>
    <p>Hello {partner_name},</p>
    <p>Your offer for <strong>{property_name}</strong> is still pending and will expire on <strong>{deadline}</strong>.</p>
    <p>If you need to update your offer, please contact our team before the deadline.</p>
</div>
'''
                
                _logger.info(f'Rendered - Subject: {subject}')
                
                # Create and send mail
                mail = self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'email_from': 'estate@localhost',
                    'email_to': partner_email,
                    'body_html': body,
                    'model': 'estate.property.offer',
                    'res_id': offer.id,
                })
                mail.send()
                _logger.info(f'Mail sent successfully for offer {offer.id}')
            except Exception as e:
                _logger.error(f'Error sending email for offer {offer.id}: {e}')
                import traceback
                _logger.error(traceback.format_exc())

    @api.model
    def _cron_notify_expiring_offers(self):
        today = fields.Date.context_today(self)
        threshold_date = today + timedelta(days=2)
        expiring_offers = self.search([
            ('state', '=', 'pending'),
            ('deadline', '>=', today),
            ('deadline', '<=', threshold_date),
        ])

        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return

        for offer in expiring_offers:
            property_record = offer.property_id
            salesperson = property_record.salesperson_id
            if not salesperson:
                continue

            note = (
                f'Offer #{offer.id} from {offer.partner_id.display_name} '
                f'for "{property_record.name}" is expiring on {offer.deadline}.'
            )
            duplicate = self.env['mail.activity'].search_count([
                ('res_model', '=', 'estate.property'),
                ('res_id', '=', property_record.id),
                ('activity_type_id', '=', activity_type.id),
                ('user_id', '=', salesperson.id),
                ('summary', '=', 'Follow up expiring offer'),
                ('date_deadline', '=', today),
            ])
            if duplicate:
                continue

            property_record.activity_schedule(
                activity_type_id=activity_type.id,
                user_id=salesperson.id,
                date_deadline=today,
                summary='Follow up expiring offer',
                note=note,
            )
            offer._send_offer_email('estate.email_template_offer_expiring')
