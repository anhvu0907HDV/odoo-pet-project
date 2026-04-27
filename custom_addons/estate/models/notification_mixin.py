from odoo import _, models


class EstateNotificationMixin(models.AbstractModel):
    _name = 'estate.notification.mixin'
    _description = 'Estate Notification Mixin'

    def _notify_action(self, message, notif_type='info', *, title='Estate', sticky=False, next_action=None):
        params = {
            'title': _(title),
            'message': _(message),
            'type': notif_type,
            'sticky': sticky,
        }
        if next_action:
            params['next'] = next_action
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': params,
        }
