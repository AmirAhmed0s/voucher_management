import frappe
from frappe import _
from frappe.utils import flt, nowdate
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries

def on_submit(doc, method=None):
    gl_entries = []
    
    # 1. معالجة حساب الدفع (Account Payment) - دعم الموظف كـ Party
    payment_party_type = "Employee" if doc.employee else None
    payment_party = doc.employee if doc.employee else None
    
    # في حالة الاستلام: الحساب مدين | في حالة الدفع: الحساب دائن
    p_debit = flt(doc.amount_after_tax) if doc.payment_type == "Receive" else 0
    p_credit = flt(doc.amount_after_tax) if doc.payment_type == "Pay" else 0

    gl_entries.append(doc.get_gl_dict({
        "account": doc.account_payment,
        "party_type": payment_party_type,
        "party": payment_party,
        "debit": p_debit,
        "credit": p_credit,
        "remarks": doc.remarks or _("Voucher Direct GL Entry"),
        "cost_center": doc.cost_center
    }))

    # 2. معالجة أسطر الجدول (References)
    for row in doc.references:
        # أ: إذا كان هناك صنف ومورد -> إنشاء فاتورة شراء سريعة
        if row.item and row.party_type == "Supplier":
            pi_name = make_auto_purchase_invoice(doc, row)
            
            # الفاتورة أنشأت (مصروف -> مورد)
            # نحن هنا ننشئ قيد السداد (مورد -> بنك) لربطهما معاً
            row_debit = flt(row.amount_after_tax) if doc.payment_type == "Pay" else 0
            row_credit = flt(row.amount_after_tax) if doc.payment_type == "Receive" else 0
            
            gl_entries.append(doc.get_gl_dict({
                "account": row.account,
                "party_type": "Supplier",
                "party": row.party,
                "debit": row_debit,
                "credit": row_credit,
                "against_voucher_type": "Purchase Invoice",
                "against_voucher": pi_name,
                "remarks": f"Settlement for PI: {pi_name} | Item: {row.item}",
                "cost_center": row.cost_center or doc.cost_center
            }))
            
        # ب: قيد حساب مباشر (بدون صنف)
        else:
            row_debit = flt(row.amount_after_tax) if doc.payment_type == "Pay" else 0
            row_credit = flt(row.amount_after_tax) if doc.payment_type == "Receive" else 0
            
            gl_entries.append(doc.get_gl_dict({
                "account": row.account,
                "party_type": row.party_type,
                "party": row.party,
                "debit": row_debit,
                "credit": row_credit,
                "remarks": row.user_remark or doc.remarks,
                "cost_center": row.cost_center or doc.cost_center
            }))

    # ترحيل القيود للأستاذ العام مباشرة
    if gl_entries:
        make_gl_entries(gl_entries)

def on_cancel(doc, method=None):
    """إلغاء قيود الـ GL وعكس الفواتير المرتبطة"""
    make_reverse_gl_entries(voucher_type=doc.doctype, voucher_no=doc.name)
    
    # البحث عن الفواتير التي أنشئت بواسطة هذا السند وإلغاؤها
    linked_pi = frappe.get_all("Purchase Invoice", 
                               filters={"remarks": ["like", f"%{doc.name}%"], "docstatus": 1})
    for inv in linked_pi:
        pi_doc = frappe.get_doc("Purchase Invoice", inv.name)
        pi_doc.cancel()

def make_auto_purchase_invoice(doc, row):
    """دالة لإنشاء فاتورة شراء وتجاوز أخطاء الحقول المفقودة في التطبيقات الأخرى"""
    pi = frappe.new_doc("Purchase Invoice")
    pi.supplier = row.party
    pi.company = doc.company
    pi.posting_date = doc.posting_date
    pi.remarks = f"Auto-generated from {doc.name}"
    
    # تحديد حساب المصروف بناءً على الصنف أو السطر
    exp_account = frappe.db.get_value("Item", row.item, "item_group_account") or row.account
    
    pi.append("items", {
        "item_code": row.item,
        "qty": flt(row.qty) or 1.0,
        "rate": row.amount, # السعر قبل الضريبة
        "expense_account": exp_account,
        "cost_center": row.cost_center or doc.cost_center
    })
    
    if row.taxes:
        pi.taxes_and_charges = row.taxes
        pi.set_taxes()
    
    # حل مشكلة (supplier_name_in_arabic) وأي حقول مفقودة
    # نستخدم ignore_mandatory لتجاوز قيود الحفظ في التطبيقات الجانبية
    pi.flags.ignore_mandatory = True
    pi.insert(ignore_permissions=True)
    pi.submit()
    return pi.name
