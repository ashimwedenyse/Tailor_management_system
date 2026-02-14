# -*- coding: utf-8 -*-
import base64
import mimetypes

from odoo import http, fields
from odoo.http import request


class TailorPortal(http.Controller):

    # --- Default Orders (normal Sale Orders) ---
    @http.route(['/my/orders'], type='http', auth="user", website=True)
    def portal_orders(self, **kwargs):
        partner = request.env.user.partner_id
        orders = request.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id)
        ], order='date_order desc')
        return request.render('tailor_management.portal_orders_list', {
            'orders': orders
        })

    # --- Tailor Orders ---
    @http.route(['/my/tailor-orders'], type='http', auth="user", website=True)
    def portal_tailor_orders(self, **kwargs):
        partner = request.env.user.partner_id
        tailor_orders = request.env['tailor.order'].sudo().search([
            ('partner_id', '=', partner.id)
        ], order='order_date desc')
        return request.render('tailor_management.portal_tailor_orders', {
            'orders': tailor_orders
        })

    # --- Tailor Order Detail ---
    @http.route(['/my/tailor-orders/<int:order_id>'], type='http', auth="user", website=True)
    def portal_tailor_order_detail(self, order_id, **kwargs):
        order = request.env['tailor.order'].sudo().browse(order_id)
        if order.partner_id.commercial_partner_id != request.env.user.partner_id.commercial_partner_id:
            return request.redirect('/my/tailor-orders')
        return request.render('tailor_management.portal_tailor_order_detail', {
            'order': order
        })

    # --- Customer Approve Tailor Order ---
    @http.route(
        ['/my/tailor-orders/<int:order_id>/approve'],
        type='http',
        auth="user",
        website=True,
        methods=['POST'],
        csrf=True
    )
    def portal_approve_order(self, order_id, **kwargs):
        order = request.env['tailor.order'].sudo().browse(order_id)
        if order.partner_id.commercial_partner_id != request.env.user.partner_id.commercial_partner_id:
            return request.redirect('/my/tailor-orders')

        # ✅ FIX: Portal customer must ONLY approve (do NOT confirm / change status)
        # Confirming is restricted to Stock Manager / Admin by your model rules.
        order.write({"customer_approved": True})

        return request.redirect(f'/my/tailor-orders/{order_id}')

    # ------------------------------------------------------------
    # Helpers (NEW, safe, small)
    # ------------------------------------------------------------
    def _portal_check_order_owner(self, order):
        return bool(order and order.partner_id.commercial_partner_id == request.env.user.partner_id.commercial_partner_id)

    def _portal_check_doc_owner(self, doc):
        return bool(
            doc and doc.tailor_order_id
            and doc.tailor_order_id.partner_id.commercial_partner_id == request.env.user.partner_id.commercial_partner_id
        )

    def _portal_allowed_doc_type(self, doc_type):
        # ✅ Portal allowed only invoice/contract (keep your rule)
        return doc_type in ('invoice', 'contract')

    def _portal_add_attachment_to_doc(self, doc, uploaded_file, fallback_name=None):
        """
        ✅ Adds a new ir.attachment linked to customer.documents (multi-file).
        Does NOT delete or replace existing ones.
        """
        if not uploaded_file or not doc:
            return False

        raw_filename = getattr(uploaded_file, 'filename', False) or ''
        raw_filename = (raw_filename or '').strip()
        safe_filename = raw_filename or (fallback_name or '').strip() or (doc.name or f"document_{doc.id}")

        file_bytes = uploaded_file.read() or b""
        if not file_bytes:
            return False

        datas_b64 = base64.b64encode(file_bytes)

        Attachment = request.env['ir.attachment'].sudo()
        att = Attachment.create({
            'name': safe_filename,
            'datas': datas_b64,
            'res_model': 'customer.documents',
            'res_id': doc.id,
            'mimetype': mimetypes.guess_type(safe_filename)[0] or 'application/octet-stream',
        })

        # ✅ IMPORTANT: ALWAYS link it to attachment_ids
        doc.sudo().write({
            'attachment_ids': [(4, att.id)],
            'upload_date': fields.Datetime.now(),  # refresh ordering in lists
        })

        # ✅ Backward compatibility: also update legacy single file fields to latest
        doc.sudo().write({
            'file': datas_b64,
            'filename': safe_filename,
        })

        return att

    # --- Upload Document to Tailor Order ---
    @http.route(
        ['/my/tailor-orders/<int:order_id>/upload'],
        type='http',
        auth="user",
        website=True,
        methods=['POST'],
        csrf=True
    )
    def portal_upload_document(self, order_id, **kwargs):
        order = request.env['tailor.order'].sudo().browse(order_id)
        if not self._portal_check_order_owner(order):
            return request.redirect('/my/tailor-orders')

        # ✅ FIXED: portal file must be read from request.httprequest.files
        uploaded_file = request.httprequest.files.get('file')
        doc_type = (kwargs.get('document_type') or '').strip()

        # ✅ ONLY allow invoice + contract
        if not self._portal_allowed_doc_type(doc_type):
            return request.redirect(f'/my/tailor-orders/{order_id}')

        Document = request.env['customer.documents'].sudo()

        # ✅ Always upload into the SAME placeholder doc for (order + type)
        doc = Document.search([
            ('tailor_order_id', '=', order.id),
            ('document_type', '=', doc_type),
        ], order='upload_date desc, id desc', limit=1)

        # If no doc exists, create it once
        if not doc:
            raw_filename = (uploaded_file and getattr(uploaded_file, 'filename', False)) or (kwargs.get('filename') or '')
            raw_filename = (raw_filename or '').strip()
            safe_filename = raw_filename or (kwargs.get('name') or '').strip() or f"document_{order_id}"

            doc = Document.create({
                'name': (kwargs.get('name') or safe_filename).strip(),
                'document_type': doc_type,
                'partner_id': order.partner_id.commercial_partner_id.id,
                'tailor_order_id': order.id,
                'uploaded_by': request.env.user.id,
                'description': (kwargs.get('description', '') or '').strip(),
            })

        # ✅ Add uploaded file as attachment
        if uploaded_file:
            self._portal_add_attachment_to_doc(doc, uploaded_file, fallback_name=kwargs.get('name'))

        return request.redirect(f'/my/tailor-orders/{order_id}')

    # ------------------------------------------------------------
    # ✅ Add file to a SPECIFIC document (GET)
    # ------------------------------------------------------------
    @http.route(['/my/documents/<int:doc_id>/add-file'], type='http', auth='user', website=True)
    def portal_document_add_file(self, doc_id, **kwargs):
        doc = request.env['customer.documents'].sudo().browse(doc_id)

        if not doc or not doc.tailor_order_id:
            return request.not_found()

        if not self._portal_check_doc_owner(doc):
            return request.redirect('/my/tailor-orders')

        if not self._portal_allowed_doc_type(doc.document_type):
            return request.redirect(f"/my/tailor-orders/{doc.tailor_order_id.id}")

        return request.render('tailor_management.portal_document_add_file', {
            'doc': doc,
            'order': doc.tailor_order_id,
        })

    # ------------------------------------------------------------
    # ✅ Add file to a SPECIFIC document (POST)
    # ------------------------------------------------------------
    @http.route(
        ['/my/documents/<int:doc_id>/add-file'],
        type='http',
        auth='user',
        website=True,
        methods=['POST'],
        csrf=True
    )
    def portal_document_add_file_post(self, doc_id, **kwargs):
        doc = request.env['customer.documents'].sudo().browse(doc_id)

        if not doc or not doc.tailor_order_id:
            return request.not_found()

        if not self._portal_check_doc_owner(doc):
            return request.redirect('/my/tailor-orders')

        if not self._portal_allowed_doc_type(doc.document_type):
            return request.redirect(f"/my/tailor-orders/{doc.tailor_order_id.id}")

        uploaded_file = request.httprequest.files.get('file')

        if uploaded_file:
            self._portal_add_attachment_to_doc(doc, uploaded_file, fallback_name=(kwargs.get('name') or doc.name))

        return request.redirect(f"/my/tailor-orders/{doc.tailor_order_id.id}")

    # --- Edit Customer Document (GET) ---
    @http.route(['/my/documents/<int:doc_id>/edit'], type='http', auth='user', website=True)
    def portal_edit_document(self, doc_id, **kwargs):
        doc = request.env['customer.documents'].sudo().browse(doc_id)

        if not doc or not doc.tailor_order_id:
            return request.not_found()

        if not self._portal_check_doc_owner(doc):
            return request.redirect('/my/tailor-orders')

        if not self._portal_allowed_doc_type(doc.document_type):
            return request.redirect(f"/my/tailor-orders/{doc.tailor_order_id.id}")

        return request.render('tailor_management.portal_document_edit', {
            'doc': doc
        })

    # --- Edit Customer Document (POST) ---
    @http.route(
        ['/my/documents/<int:doc_id>/edit'],
        type='http',
        auth='user',
        website=True,
        methods=['POST'],
        csrf=True
    )
    def portal_edit_document_post(self, doc_id, **kwargs):
        doc = request.env['customer.documents'].sudo().browse(doc_id)

        if not doc or not doc.tailor_order_id:
            return request.not_found()

        if not self._portal_check_doc_owner(doc):
            return request.redirect('/my/tailor-orders')

        if not self._portal_allowed_doc_type(doc.document_type):
            return request.redirect(f"/my/tailor-orders/{doc.tailor_order_id.id}")

        # ✅ FIXED: portal file must be read from request.httprequest.files
        uploaded_file = request.httprequest.files.get('file')

        if uploaded_file:
            self._portal_add_attachment_to_doc(doc, uploaded_file, fallback_name=doc.name)

        return request.redirect(f"/my/tailor-orders/{doc.tailor_order_id.id}")

    # --- Download Customer Document ---
    @http.route(['/my/documents/<int:doc_id>/download'], type='http', auth='user', website=True)
    def portal_download_document(self, doc_id, **kwargs):
        doc = request.env['customer.documents'].sudo().browse(doc_id)

        if not doc or not doc.tailor_order_id:
            return request.not_found()

        if not self._portal_check_doc_owner(doc):
            return request.not_found()

        # ✅ NEW: If att_id is provided, download THAT attachment
        att_id = kwargs.get('att_id')
        if att_id:
            try:
                att_id = int(att_id)
            except Exception:
                return request.not_found()

            att = request.env['ir.attachment'].sudo().browse(att_id)
            if not att.exists():
                return request.not_found()

            # ✅ Security: attachment must belong to this document
            if att.res_model != 'customer.documents' or att.res_id != doc.id:
                return request.not_found()

            if not att.datas:
                return request.not_found()

            filecontent = base64.b64decode(att.datas)
            safe_filename = att.name or f"document_{doc.id}"
            content_type, _ = mimetypes.guess_type(safe_filename)
            if not content_type:
                content_type = 'application/octet-stream'

            return request.make_response(
                filecontent,
                headers=[
                    ('Content-Type', content_type),
                    ('Content-Disposition', f'attachment; filename=\"{safe_filename}\"')
                ]
            )

        # ✅ Otherwise fallback: latest attachment if exists
        if 'attachment_ids' in doc._fields and doc.attachment_ids:
            att = doc.attachment_ids.sorted(lambda a: (a.create_date or fields.Datetime.now(), a.id))[-1]
            if not att or not att.datas:
                return request.not_found()

            filecontent = base64.b64decode(att.datas)
            safe_filename = att.name or f"document_{doc.id}"
            content_type, _ = mimetypes.guess_type(safe_filename)
            if not content_type:
                content_type = 'application/octet-stream'

            return request.make_response(
                filecontent,
                headers=[
                    ('Content-Type', content_type),
                    ('Content-Disposition', f'attachment; filename=\"{safe_filename}\"')
                ]
            )

        # ✅ Legacy fallback
        if not doc.file:
            return request.not_found()

        filecontent = base64.b64decode(doc.file)
        safe_filename = doc.filename or doc.name or f"document_{doc.id}"
        if not isinstance(safe_filename, str):
            safe_filename = f"document_{doc.id}"

        content_type, _ = mimetypes.guess_type(safe_filename)
        if not content_type:
            content_type = 'application/octet-stream'

        return request.make_response(
            filecontent,
            headers=[
                ('Content-Type', content_type),
                ('Content-Disposition', f'attachment; filename=\"{safe_filename}\"')
            ]
        )
