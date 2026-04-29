from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestEstateProperty(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner_1 = self.env['res.partner'].create({'name': 'Buyer One'})
        self.partner_2 = self.env['res.partner'].create({'name': 'Buyer Two'})
        self.property = self.env['estate.property'].create({
            'name': 'Test Property',
            'expected_price': 200000,
        })
        self.user_employee = self.env['res.users'].create({
            'name': 'Estate Employee',
            'login': 'estate_employee',
            'email': 'estate_employee@example.com',
            'groups_id': [Command.link(self.env.ref('base.group_user').id)],
        })
        self.user_manager = self.env['res.users'].create({
            'name': 'Estate Manager',
            'login': 'estate_manager',
            'email': 'estate_manager@example.com',
            'groups_id': [
                Command.link(self.env.ref('base.group_user').id),
                Command.link(self.env.ref('estate.group_estate_manager').id),
            ],
        })

    def _create_offer(self, price, partner):
        return self.env['estate.property.offer'].create({
            'price': price,
            'partner_id': partner.id,
            'property_id': self.property.id,
        })

    def test_creating_first_offer_moves_property_to_offer_state(self):
        self._create_offer(210000, self.partner_1)
        self.assertEqual(self.property.state, 'offer')

    def test_offer_accept_sets_buyer_price_and_refuses_other_offers(self):
        offer_1 = self._create_offer(210000, self.partner_1)
        offer_2 = self._create_offer(220000, self.partner_2)

        offer_2.with_user(self.user_manager).action_accept()
        self.property.invalidate_recordset()
        offer_1.invalidate_recordset()
        offer_2.invalidate_recordset()

        self.assertEqual(offer_2.state, 'accepted')
        self.assertEqual(offer_1.state, 'refused')
        self.assertEqual(self.property.buyer_id, self.partner_2)
        self.assertEqual(self.property.selling_price, 220000)
        self.assertEqual(self.property.state, 'offer')

    def test_accept_offer_requires_manager_permission(self):
        offer = self._create_offer(210000, self.partner_1)
        with self.assertRaises(UserError):
            offer.with_user(self.user_employee).action_accept()

    def test_cannot_mark_sold_without_accepted_offer(self):
        self._create_offer(210000, self.partner_1)
        with self.assertRaises(UserError):
            self.property.with_user(self.user_manager).action_mark_sold()

    def test_mark_sold_requires_manager_permission(self):
        offer = self._create_offer(210000, self.partner_1)
        offer.with_user(self.user_manager).action_accept()
        with self.assertRaises(UserError):
            self.property.with_user(self.user_employee).action_mark_sold()

    def test_cancel_resets_sale_data(self):
        offer = self._create_offer(220000, self.partner_1)
        offer.with_user(self.user_manager).action_accept()
        self.property.with_user(self.user_manager).action_cancel()
        self.property.invalidate_recordset()
        self.assertEqual(self.property.state, 'cancel')
        self.assertFalse(self.property.buyer_id)
        self.assertEqual(self.property.selling_price, 0)
        self.assertFalse(self.property.sold_date)

    def test_cancel_requires_manager_permission(self):
        with self.assertRaises(UserError):
            self.property.with_user(self.user_employee).action_cancel()

    def test_offer_price_must_be_higher_than_active_offers(self):
        self._create_offer(210000, self.partner_1)
        with self.assertRaises(ValidationError):
            self._create_offer(200000, self.partner_2)

    def test_offer_price_can_be_below_refused_offer(self):
        offer = self._create_offer(240000, self.partner_1)
        offer.with_user(self.user_manager).action_refuse()
        second_offer = self._create_offer(210000, self.partner_2)
        self.assertEqual(second_offer.state, 'pending')

    def test_refusing_last_active_offer_resets_property_state(self):
        offer = self._create_offer(210000, self.partner_1)
        offer.with_user(self.user_manager).action_refuse()
        self.property.invalidate_recordset()
        self.assertEqual(self.property.state, 'new')
        self.assertFalse(self.property.buyer_id)
        self.assertEqual(self.property.selling_price, 0)

    def test_refuse_offer_requires_manager_permission(self):
        offer = self._create_offer(210000, self.partner_1)
        with self.assertRaises(UserError):
            offer.with_user(self.user_employee).action_refuse()

    def test_selling_price_threshold_constraint(self):
        with self.assertRaises(ValidationError):
            self.property.write({'selling_price': 100000})

    def test_ai_recommendation_uses_fallback_when_provider_fails(self):
        offer = self._create_offer(230000, self.partner_1)
        with patch(
            'odoo.addons.estate.models.ai_service.EstateAiService._call_openrouter',
            side_effect=RuntimeError('quota exceeded'),
        ):
            recommendation = self.env['estate.ai.service'].recommend_offer(self.property)
        self.assertEqual(recommendation['offer'], offer)
        self.assertEqual(recommendation['provider'], 'fallback')
        self.assertIn('Fallback recommendation used', recommendation['reasoning'])
