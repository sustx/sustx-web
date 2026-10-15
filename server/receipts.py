"""Immutable purchase receipt snapshots and print-ready, branded PDF documents."""
import base64
from datetime import datetime, timezone
import hashlib
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape


def money(cents):
    return f"${cents / 100:,.2f}"


def snapshot(purchase, payment):
    """Use verified, stored values only; never accept receipt fields from a browser."""
    paid = datetime.fromisoformat(payment['paid_at'].replace('Z', '+00:00')).astimezone(timezone.utc)
    number = 'SA-' + paid.strftime('%Y%m%d') + '-' + purchase['purchase_id'].replace('-', '').upper()
    return {'schema': 1, 'purchase_id': purchase['purchase_id'], 'number': number,
            'seller': 'Sustx Audio', 'website': 'https://www.sustx.xyz',
            'customer': purchase['customer'], 'email': purchase['email'],
            'item': 'Parallax', 'description': 'Perpetual license · Two computer activations', 'quantity': 1,
            'subtotal_cents': purchase['price']['subtotal_cents'],
            'discount_cents': purchase['price']['discount_cents'], 'discount_code': purchase['price']['discount_code'],
            'total_cents': payment['amount_cents'], 'currency': payment['currency'], 'paid_at': payment['paid_at'],
            'created_at': payment['verified_at'], 'method': 'PayPal', 'order_id': payment['order_id'], 'capture_id': payment['capture_id'],
            'mode': payment['mode']}


def render(receipt):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

    # Ship the font supplied with ReportLab; don't rely on a host's system fonts.
    fonts = Path(reportlab.__file__).parent / 'fonts'
    for name, filename in [('Receipt', 'Vera.ttf'), ('ReceiptBold', 'VeraBd.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    ink = colors.HexColor('#101c25'); muted = colors.HexColor('#596b77'); mint = colors.HexColor('#72d8c9')
    styles = {
        'body': ParagraphStyle('body', fontName='Receipt', fontSize=10, leading=15, textColor=ink, splitLongWords=True),
        'label': ParagraphStyle('label', fontName='ReceiptBold', fontSize=8, leading=13, textColor=muted),
        'small': ParagraphStyle('small', fontName='Receipt', fontSize=8, leading=12, textColor=muted, splitLongWords=True),
        'title': ParagraphStyle('title', fontName='ReceiptBold', fontSize=31, leading=39, textColor=ink),
        'right': ParagraphStyle('right', fontName='ReceiptBold', fontSize=11, leading=17, alignment=TA_RIGHT, textColor=ink),
    }
    def p(value, style='body'):
        return Paragraph(escape(str(value)), styles[style])
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=(612, 792), leftMargin=48, rightMargin=48,
                            topMargin=116, bottomMargin=62, title='Parallax purchase receipt ' + receipt['number'],
                            author='Sustx Audio', invariant=1)
    def page(canvas, document):
        canvas.saveState()
        canvas.setFillColor(ink); canvas.rect(0, 692, 612, 100, fill=1, stroke=0)
        # The approved site mark, drawn directly to keep the PDF crisp at print size.
        canvas.setStrokeColor(colors.white); canvas.setLineWidth(2.0)
        path=canvas.beginPath()
        for x,y,start in [(32,13,True),(17,22,False),(47,41,False),(32,50,False),(47,22,True),(17,41,False)]:
            px=48+x*.65; py=721+(64-y)*.65
            if start: path.moveTo(px,py)
            else:path.lineTo(px,py)
        canvas.drawPath(path)
        canvas.setFillColor(colors.white)
        canvas.setFont('ReceiptBold',14);canvas.drawString(99,744,'SUSTX AUDIO')
        canvas.setFont('Receipt',8);canvas.setFillColor(mint);canvas.drawString(99,726,'www.sustx.xyz')
        canvas.setFillColor(mint);canvas.setFont('ReceiptBold',9)
        canvas.drawRightString(564,742,'SANDBOX · TEST PAYMENT' if receipt['mode']=='sandbox' else 'PAID')
        canvas.setStrokeColor(colors.HexColor('#dce4e8'));canvas.line(48,47,564,47)
        canvas.setFillColor(muted);canvas.setFont('Receipt',8)
        canvas.drawString(48,31,'Sustx Audio · Purchase receipt')
        canvas.drawRightString(564,31,f'{document.page}')
        canvas.restoreState()
    paid = datetime.fromisoformat(receipt['paid_at'].replace('Z','+00:00')).astimezone(timezone.utc)
    story=[p('Payment receipt','title'),Spacer(1,10)]
    if receipt['mode']=='sandbox':
        story += [p('TEST RECEIPT — No real money was charged. Not valid as proof of purchase.','small'),Spacer(1,14)]
    story += [p('RECEIPT NUMBER','label'),p(receipt['number'],'small'),Spacer(1,12),
              p('PAID ON','label'),p(paid.strftime('%B %d, %Y · %H:%M UTC')),Spacer(1,22),
              p('BILLED TO','label'),p(receipt['customer']),p(receipt['email']),Spacer(1,24)]
    table=Table([[p('ITEM','label'),p('QTY','label'),p('AMOUNT','label')],
                 [p(receipt['item']+' — '+receipt['description']),p(receipt['quantity']),p(money(receipt['subtotal_cents']),'right')]],
                colWidths=[376,40,100],hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
                               ('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),
                               ('BOTTOMPADDING',(0,0),(-1,-1),12),('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#dce4e8'))]))
    totals=[['Subtotal',money(receipt['subtotal_cents'])]]
    if receipt['discount_cents']:
        totals.append(['Discount'+(' · '+receipt['discount_code'] if receipt['discount_code'] else ''),'-'+money(receipt['discount_cents'])])
    totals.append(['Total paid · '+receipt['currency'],money(receipt['total_cents'])])
    summary=Table([[p(label),p(value,'right')] for label,value in totals],colWidths=[376,140],hAlign='LEFT')
    summary.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
                                 ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
                                 ('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#e8f7f4'))]))
    story += [table,Spacer(1,10),KeepTogether([summary]),Spacer(1,24),p('PAYMENT DETAILS','label'),
              p('Paid via PayPal'),p('Transaction: '+receipt['capture_id'],'small'),p('Order: '+receipt['order_id'],'small'),
              Spacer(1,26),p('Thank you for choosing Parallax.'),
              p('Your activation link arrives in a separate email. Keep this receipt for your records.','small')]
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()


def document(purchase, payment):
    data=snapshot(purchase,payment)
    pdf=render(data)
    return {**data, 'filename': data['number']+'.pdf', 'content_type': 'application/pdf',
            'pdf_base64': base64.b64encode(pdf).decode(), 'sha256': hashlib.sha256(pdf).hexdigest()}


def download(receipt):
    pdf=base64.b64decode(receipt['pdf_base64'],validate=True)
    if hashlib.sha256(pdf).hexdigest()!=receipt['sha256'] or not pdf.startswith(b'%PDF-'):
        raise ValueError('Stored receipt could not be verified.')
    return pdf,receipt['filename']
