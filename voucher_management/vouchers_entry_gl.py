import frappe
from frappe.utils import flt, nowdate
from frappe import _
from erpnext.accounts.general_ledger import make_gl_entries

def on_submit(doc, method=None):
    gl_entries = []
    
    # 1. معالجة حساب الدفع الرئيسي (Payment Account)
    # إذا وجد موظف، يتم اعتباره هو الـ Party
    payment_debit = flt(doc.amount_after_tax) if doc.payment_type == "Receive" else 0
    payment_credit = flt(doc.amount_after_tax) if doc.payment_type == "Pay" else 0
    
    gl_entries.append({
        "account": doc.account_payment,
        "party_type": "Employee" if doc.employee else None,
        "party": doc.employee if doc.employee else None,
        "debit": payment_debit,
        "credit": payment_credit,
        "posting_date": doc.posting_date,
        "voucher_type": doc.doctype,
        "voucher_no": doc.name,
        "company": doc.company,
        "remarks": doc.remarks,
        "cost_center": doc.cost_center
    })

    # 2. معالجة أسطر الجدول (References)
    for row in doc.references:
        # أ: إذا كان هناك صنف (Item) -> إنشاء فاتورة شراء تلقائية
        if row.item and row.party_type == "Supplier":
            make_auto_purchase_invoice(doc, row)
            # ملاحظة: الفاتورة عند ترحيلها تنشئ GL Entry الخاص بها (Expense vs Supplier)
            # لذا سننشئ هنا GL Entry لسداد هذه الفاتورة (Supplier vs Bank)
            gl_entries.append({
                "account": row.account, # حساب المورد
                "party_type": "Supplier",
                "party": row.party,
                "debit": row.amount_after_tax if doc.payment_type == "Pay" else 0,
                "credit": row.amount_after_tax if doc.payment_type == "Receive" else 0,
                "posting_date": doc.posting_date,
                "voucher_type": doc.doctype,
                "voucher_no": doc.name,
                "company": doc.company,
                "remarks": f"Settlement for Item: {row.item}",
                "cost_center": row.cost_center or doc.cost_center
            })
            
        # ب: إذا لم يكن هناك صنف -> GL Entry مباشر
        else:
            gl_entries.append({
                "account": row.account,
                "party_type": row.party_type,
                "party": row.party,
                "debit": row.amount_after_tax if doc.payment_type == "Pay" else 0,
                "credit": row.amount_after_tax if doc.payment_type == "Receive" else 0,
                "posting_date": doc.posting_date,
                "voucher_type": doc.doctype,
                "voucher_no": doc.name,
                "company": doc.company,
                "remarks": row.user_remark or doc.remarks,
                "cost_center": row.cost_center or doc.cost_center
            })

    # ترحيل جميع القيود للأستاذ العام دفعة واحدة
    if gl_entries:
        make_gl_entries(gl_entries)

def on_cancel(doc, method=None):
    """إلغاء وحذف القيود والفواتير المرتبطة"""
    # 1. حذف الـ GL Entries المرتبطة بهذا السند
    frappe.db.sql("""DELETE FROM `tabGL Entry` WHERE voucher_no=%s""", doc.name)
    
    # 2. البحث عن فواتير الشراء التي تم إنشاؤها وإلغاؤها
    linked_p_invoices = frappe.get_all("Purchase Invoice", filters={"remarks": ["like", f"%{doc.name}%"]}, fields=["name", "docstatus"])
    for inv in linked_p_invoices:
        if inv.docstatus == 1:
            inv_doc = frappe.get_doc("Purchase Invoice", inv.name)
            inv_doc.cancel()
            
    frappe.msgprint(_("تم عكس قيود الأستاذ العام وإلغاء الفواتير المرتبطة بنجاح"))

def make_auto_purchase_invoice(doc, row):
    """دالة ذكية لإنشاء فاتورة شراء من سطر السند"""
    pi = frappe.new_doc("Purchase Invoice")
    pi.supplier = row.party
    pi.company = doc.company
    pi.posting_date = doc.posting_date
    pi.remarks = f"Generated from {doc.name}"
    
    # إضافة الصنف
    pi.append("items", {
        "item_code": row.item,
        "qty": 1,
        "rate": row.amount_before_tax,
        "expense_account": frappe.get_cached_value("Item", row.item, "item_group_account") or row.account,
        "cost_center": row.cost_center or doc.cost_center
    })
    
    # إضافة الضرائب إذا وجدت
    if row.taxes:
        tax_template = frappe.get_doc("Purchase Taxes and Charges Template", row.taxes)
        for t in tax_template.taxes:
            pi.append("taxes", {
                "category": t.category,
                "add_deduct_tax": t.add_deduct_tax,
                "charge_type": t.charge_type,
                "account_head": t.account_head,
                "description": t.description,
                "rate": t.rate
            })
            
    pi.insert(ignore_permissions=True)
    pi.submit()
    return pi.name
