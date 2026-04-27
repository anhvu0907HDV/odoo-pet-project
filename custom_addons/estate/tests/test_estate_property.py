from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestEstateProperty(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': 'Test Buyer'})
        self.property = self.env['estate.property'].create({
            'name': 'Test Property',
            'expected_price': 200000,
        })

    def test_offer_accept_sets_buyer_and_selling_price(self):
        offer = self.env['estate.property.offer'].create({
            'price': 220000,
            'partner_id': self.partner.id,
            'property_id': self.property.id,
        })

        offer.action_accept()
        self.assertEqual(self.property.buyer_id, self.partner)
        self.assertEqual(self.property.selling_price, 220000)
        self.assertEqual(self.property.state, 'offer')

    def test_cannot_mark_sold_without_accepted_offer(self):
        with self.assertRaises(UserError):
            self.property.action_mark_sold()

    def test_selling_price_threshold_constraint(self):
        with self.assertRaises(ValidationError):
            self.property.write({'selling_price': 100000})
