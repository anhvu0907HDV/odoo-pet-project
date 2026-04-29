import base64
from datetime import date, datetime, timedelta
from io import BytesIO

import xlsxwriter

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EstateReportWizard(models.TransientModel):
    _name = 'estate.report.wizard'
    _description = 'Estate Report Wizard'

    name = fields.Char(default='Estate Report Export')
    state = fields.Selection(
        selection=[
            ('new', 'New'),
            ('offer', 'Offer Received'),
            ('sold', 'Sold'),
            ('cancel', 'Cancelled'),
        ],
        string='Property Status',
    )
    date_from = fields.Date(string='Created From')
    date_to = fields.Date(string='Created To')
    property_type_id = fields.Many2one('estate.property.type', string='Property Type')
    include_archived = fields.Boolean(default=False)
    file_data = fields.Binary(readonly=True)
    file_name = fields.Char(readonly=True)

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError('Created From must be before or equal to Created To.')

    def action_export_pdf(self):
        self.ensure_one()
        return self.env.ref('estate.action_report_property_pdf').report_action(
            self,
            data={'wizard_id': self.id},
        )

    def action_export_xlsx(self):
        self.ensure_one()
        workbook_buffer = BytesIO()
        workbook = xlsxwriter.Workbook(workbook_buffer, {'in_memory': True})
        worksheet = workbook.add_worksheet('Estate Report')

        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': '#0F172A',
            'align': 'left',
        })
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#E2E8F0',
            'border': 1,
            'font_color': '#0F172A',
            'align': 'center',
        })
        cell_format = workbook.add_format({'border': 1, 'valign': 'top'})
        money_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})

        worksheet.merge_range('A1:H1', 'Estate Property Report', title_format)
        worksheet.write('A2', f'Generated at: {fields.Datetime.now()}', cell_format)
        worksheet.write('A3', f'Filters: {self._filter_summary()}', cell_format)

        headers = ['Title', 'Type', 'State', 'Expected Price', 'Selling Price', 'Best Offer', 'Salesperson', 'Company']
        for col, header in enumerate(headers):
            worksheet.write(4, col, header, header_format)

        for row, property_record in enumerate(self._get_properties(), start=5):
            worksheet.write(row, 0, property_record.name or '', cell_format)
            worksheet.write(row, 1, property_record.property_type_id.name or '', cell_format)
            worksheet.write(row, 2, property_record.state or '', cell_format)
            worksheet.write_number(row, 3, property_record.expected_price or 0, money_format)
            worksheet.write_number(row, 4, property_record.selling_price or 0, money_format)
            worksheet.write_number(row, 5, property_record.best_price or 0, money_format)
            worksheet.write(row, 6, property_record.salesperson_id.name or '', cell_format)
            worksheet.write(row, 7, property_record.company_id.name or '', cell_format)

        worksheet.set_column('A:A', 28)
        worksheet.set_column('B:B', 18)
        worksheet.set_column('C:C', 14)
        worksheet.set_column('D:F', 16)
        worksheet.set_column('G:H', 20)
        workbook.close()

        workbook_buffer.seek(0)
        filename = f'estate_report_{date.today()}.xlsx'
        self.write({
            'file_data': base64.b64encode(workbook_buffer.read()),
            'file_name': filename,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/web/content?model=estate.report.wizard'
                f'&id={self.id}&field=file_data&filename_field=file_name&download=true'
            ),
            'target': 'self',
        }

    def _get_properties(self):
        self.ensure_one()
        domain = []
        if self.state:
            domain.append(('state', '=', self.state))
        if self.date_from:
            domain.append(('create_date', '>=', datetime.combine(self.date_from, datetime.min.time())))
        if self.date_to:
            domain.append(('create_date', '<', datetime.combine(self.date_to + timedelta(days=1), datetime.min.time())))
        if self.property_type_id:
            domain.append(('property_type_id', '=', self.property_type_id.id))
        if not self.include_archived:
            domain.append(('active', '=', True))
        return self.env['estate.property'].search(domain, order='create_date desc')

    def _filter_summary(self):
        self.ensure_one()
        chunks = []
        if self.state:
            chunks.append(f'State={self.state}')
        if self.property_type_id:
            chunks.append(f'Type={self.property_type_id.name}')
        if self.date_from:
            chunks.append(f'From={self.date_from}')
        if self.date_to:
            chunks.append(f'To={self.date_to}')
        if self.include_archived:
            chunks.append('Include archived')
        return ', '.join(chunks) if chunks else 'No filters'


class ReportEstatePropertyPdf(models.AbstractModel):
    _name = 'report.estate.report_property_pdf'
    _description = 'Estate Property PDF Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env['estate.report.wizard'].browse((data or {}).get('wizard_id')).exists()
        return {
            'doc_ids': wizard.ids,
            'doc_model': 'estate.report.wizard',
            'docs': wizard,
            'properties': wizard._get_properties() if wizard else self.env['estate.property'],
            'filter_summary': wizard._filter_summary() if wizard else 'No filters',
        }
