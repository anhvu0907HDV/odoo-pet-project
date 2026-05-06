import json
import html

from odoo import api, fields, models
from odoo.exceptions import UserError


class EstateRagAskWizard(models.TransientModel):
    _name = 'estate.rag.ask.wizard'
    _description = 'Estate RAG Q&A Wizard'

    property_id = fields.Many2one('estate.property', required=True, ondelete='cascade')
    question = fields.Text(required=True)
    top_k = fields.Integer(string='Top K', default=5)
    auto_index = fields.Boolean(
        string='Keep answers up to date',
        default=True,
        help='If enabled, the system will refresh knowledge automatically when needed.',
    )
    answer = fields.Text(readonly=True)
    sources_json = fields.Text(readonly=True)
    sources_html = fields.Html(string='Sources', compute='_compute_sources_html', sanitize=True)
    answer_html = fields.Html(string='Answer', compute='_compute_answer_html', sanitize=True)
    last_indexed_at = fields.Datetime(string='Last Indexed', readonly=True)
    indexed_chunk_count = fields.Integer(string='Indexed Chunks', readonly=True)

    def action_index(self):
        self.ensure_one()
        result = self.env['estate.rag.service'].index_property(self.property_id.id)
        inserted = (result or {}).get('inserted', 0)
        chunk_count = self.env['estate.rag.chunk'].sudo().search_count([
            ('res_model', '=', 'estate.property'),
            ('res_id', '=', self.property_id.id),
        ])
        self.write({
            'last_indexed_at': fields.Datetime.now(),
            'indexed_chunk_count': chunk_count,
        })
        return self.env['estate.notification.mixin']._notify_action(
            f'Indexed {inserted} chunks for Property #{self.property_id.id}.',
            'success',
            next_action={'type': 'ir.actions.client', 'tag': 'soft_reload'},
        )

    def action_ask(self):
        self.ensure_one()
        if not (self.question or '').strip():
            raise UserError('Question is required.')
        if self.auto_index:
            chunk_count = self.env['estate.rag.chunk'].sudo().search_count([
                ('res_model', '=', 'estate.property'),
                ('res_id', '=', self.property_id.id),
            ])
            if not chunk_count:
                self.env['estate.rag.service'].index_property(self.property_id.id)
                self.write({
                    'last_indexed_at': fields.Datetime.now(),
                    'indexed_chunk_count': self.env['estate.rag.chunk'].sudo().search_count([
                        ('res_model', '=', 'estate.property'),
                        ('res_id', '=', self.property_id.id),
                    ]),
                })

        result = self.env['estate.rag.service'].ask_property(self.property_id.id, self.question, limit=self.top_k)
        self.write({
            'answer': (result or {}).get('answer'),
            'sources_json': json.dumps((result or {}).get('sources') or []),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.depends('sources_json')
    def _compute_sources_html(self):
        for wizard in self:
            sources = []
            try:
                sources = json.loads(wizard.sources_json or '[]') or []
            except Exception:
                sources = []
            if not sources:
                wizard.sources_html = False
                continue
            items = []
            for src in sources:
                title = html.escape(str(src.get('title', '')))
                source = html.escape(str(src.get('source', '')))
                distance = src.get('distance')
                distance_txt = ''
                try:
                    if distance is not None:
                        d = float(distance)
                        if d <= 0.25:
                            label = 'High'
                            cls = 'text-bg-success'
                        elif d <= 0.45:
                            label = 'Medium'
                            cls = 'text-bg-warning'
                        else:
                            label = 'Low'
                            cls = 'text-bg-light'
                        distance_txt = f"<span class='badge {cls} ms-2'>Relevance: {label}</span>"
                except Exception:
                    distance_txt = ''
                items.append(
                    "<li class='mb-2'>"
                    f"<div><strong>{title}</strong>{distance_txt}</div>"
                    f"<div class='text-muted'>{source}</div>"
                    "</li>"
                )
            wizard.sources_html = "<ul class='mb-0 ps-3'>" + "".join(items) + "</ul>"

    @api.depends('answer')
    def _compute_answer_html(self):
        for wizard in self:
            text = (wizard.answer or '').strip()
            if not text:
                wizard.answer_html = False
                continue
            # keep it simple: preserve line breaks
            wizard.answer_html = "<div>" + html.escape(text).replace("\n", "<br/>") + "</div>"
