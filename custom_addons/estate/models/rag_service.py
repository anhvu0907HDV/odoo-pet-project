import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EstateRagService(models.AbstractModel):
    _name = 'estate.rag.service'
    _description = 'Estate RAG Service'

    @api.model
    def index_property(self, property_id):
        property_record = self.env['estate.property'].browse(int(property_id)).exists()
        if not property_record:
            raise UserError('Property not found.')
        property_record.check_access_rights('read')
        property_record.check_access_rule('read')

        tag_names = ', '.join(property_record.tag_ids.mapped('name')) if property_record.tag_ids else ''
        property_type = property_record.property_type_id.name if property_record.property_type_id else ''

        offers = property_record.offer_ids.sorted(key=lambda o: o.price, reverse=True)
        offer_lines = []
        for offer in offers[:20]:
            offer_lines.append(
                f"- offer_id={offer.id}, price={offer.price}, state={offer.state}, buyer={offer.partner_id.display_name}, deadline={offer.deadline or 'N/A'}"
            )

        chunks = []
        core_text = (
            f"Property #{property_record.id}: {property_record.name}\n"
            f"Type: {property_type}\n"
            f"Tags: {tag_names}\n"
            f"State: {property_record.state}\n"
            f"Expected price: {property_record.expected_price}\n"
            f"Selling price: {property_record.selling_price}\n"
            f"Bedrooms: {property_record.bedrooms}\n"
            f"Living area: {property_record.living_area}\n"
            f"Garden area: {property_record.garden_area}\n"
            f"Total area: {property_record.total_area}\n"
        ).strip()
        chunks.append({
            'title': f'Property #{property_record.id} core',
            'source': 'estate.property',
            'chunk': core_text,
        })

        desc = (property_record.description or '').strip()
        if desc:
            chunks.append({
                'title': f'Property #{property_record.id} description',
                'source': 'estate.property.description',
                'chunk': desc,
            })

        if offer_lines:
            chunks.append({
                'title': f'Property #{property_record.id} offers',
                'source': 'estate.property.offer',
                'chunk': "Offers:\n" + "\n".join(offer_lines),
            })

        ai = self.env['estate.ai.service']
        for item in chunks:
            item['embedding'] = ai.embed_text(item['chunk'])

        inserted = self.env['estate.rag.chunk'].sudo().upsert_chunks('estate.property', property_record.id, chunks)
        return {'inserted': inserted}

    @api.model
    def ask_property(self, property_id, question, limit=5):
        property_record = self.env['estate.property'].browse(int(property_id)).exists()
        if not property_record:
            raise UserError('Property not found.')
        property_record.check_access_rights('read')
        property_record.check_access_rule('read')

        question = (question or '').strip()
        if not question:
            raise UserError('Question is required.')

        ai = self.env['estate.ai.service']
        query_embedding = ai.embed_text(question)
        matches = self.env['estate.rag.chunk'].sudo().search_similar(
            'estate.property',
            property_record.id,
            query_embedding,
            limit=int(limit or 5),
        )
        if not matches:
            raise UserError('No indexed content found. Click "Index Knowledge" first.')

        context_text = "\n\n".join([f"[{m['source']}] {m['chunk']}" for m in matches])
        prompt = f"""
You are an assistant helping a real estate team.
Use ONLY the provided context to answer the question. If the answer is not in the context, say you don't know.
Answer in a concise, helpful way.

Question:
{question}

Context:
{context_text}
""".strip()

        provider = ai._get_provider()
        try:
            answer = ai._call_provider(provider, prompt, expect_json=False)
        except Exception as exc:
            _logger.warning('RAG answer failed, provider=%s: %s', provider, exc)
            raise UserError(str(exc))

        return {
            'answer': (answer or '').strip(),
            'sources': [
                {
                    'id': m.get('id'),
                    'source': m.get('source'),
                    'title': m.get('title'),
                    'distance': m.get('distance'),
                }
                for m in matches
            ],
        }
