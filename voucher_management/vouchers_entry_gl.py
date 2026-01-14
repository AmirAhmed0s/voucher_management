import frappe
from frappe.utils import flt, nowdate

def on_submit(doc, method=None):
    make_gl_entries(doc)

def on_cancel(doc, method=None):
    frappe.db.delete("GL Entry", {"voucher_type": doc.doctype, "voucher_no": doc.name})

def make_gl_entries(doc):
    gl_entries = []
    company_currency = frappe.get_cached_value('Company', doc.company, 'default_currency')

    def append_gl_entry(account, debit, credit, party_type=None, party=None, ref_type=None, ref_name=None, cost_center=None, remark=None):
        if flt(debit) == 0 and flt(credit) == 0:
            return
        
        # جلب عملة الحساب
        account_currency = frappe.db.get_value("Account", account, "account_currency") or company_currency
        
        gl_entries.append(frappe._dict({
            "posting_date": doc.posting_date,
            "transaction_date": nowdate(),
            "account": account,
            "account_currency": account_currency,
            "transaction_currency": company_currency, # نفترض عملة الشركة للتبسيط
            "transaction_exchange_rate": 1.0,
            
            # تعبئة كافة حقول المبالغ لضمان الظهور في التقارير
            "debit": flt(debit),
            "credit": flt(credit),
            "debit_in_account_currency": flt(debit),
            "credit_in_account_currency": flt(credit),
            "debit_in_transaction_currency": flt(debit),
            "credit_in_transaction_currency": flt(credit),
            
            "party_type": party_type,
            "party": party,
            "voucher_type": doc.doctype,
            "voucher_no": doc.name,
            "company": doc.company,
            "remarks": remark or doc.remarks,
            "cost_center": cost_center or doc.cost_center,
            "project": doc.custom_project,
            "against": doc.account_payment if doc.payment_type != "Internal Transfer" else doc.paid_from,
            "against_voucher_type": ref_type,
            "against_voucher": ref_name,
            "is_opening": "No"
        }))

    # --- Case 1: Receive ---
    if doc.payment_type == "Receive":
        append_gl_entry(doc.account_payment, doc.amount_after_tax, 0)
        for row in doc.references:
            total_allocated = 0
            if doc.get("vouchers_payment_references"):
                for alloc in doc.get("vouchers_payment_references"):
                    if alloc.customer == row.party:
                        append_gl_entry(row.account, 0, alloc.allocated_amount, row.party_type, row.party, alloc.reference_doctype, alloc.reference_name, row.cost_center, row.user_remark)
                        total_allocated += flt(alloc.allocated_amount)
            
            remaining = flt(row.amount_before_tax) - total_allocated
            if remaining > 0:
                append_gl_entry(row.account, 0, remaining, row.party_type, row.party, cost_center=row.cost_center)
        
        # إضافة الضريبة إذا وجدت
        if doc.total_taxes > 0:
            tax_acc = frappe.db.get_value("Purchase Taxes and Charges", {"parent": doc.references[0].taxes}, "account_head") if doc.references else None
            if tax_acc: append_gl_entry(tax_acc, 0, doc.total_taxes)

    # --- Case 2: Pay ---
    elif doc.payment_type == "Pay":
        append_gl_entry(doc.account_payment, 0, doc.amount_after_tax)
        for row in doc.references:
            total_allocated = 0
            if doc.get("vouchers_payment_references2"):
                for alloc in doc.get("vouchers_payment_references2"):
                    if alloc.suppiler == row.party:
                        append_gl_entry(row.account, alloc.allocated_amount, 0, row.party_type, row.party, alloc.reference_doctype, alloc.reference_name, row.cost_center, row.user_remark)
                        total_allocated += flt(alloc.allocated_amount)
            remaining = flt(row.amount_before_tax) - total_allocated
            if remaining > 0:
                append_gl_entry(row.account, remaining, 0, row.party_type, row.party, cost_center=row.cost_center)
        
        if doc.total_taxes > 0:
            tax_acc = frappe.db.get_value("Purchase Taxes and Charges", {"parent": doc.references[0].taxes}, "account_head") if doc.references else None
            if tax_acc: append_gl_entry(tax_acc, doc.total_taxes, 0)

    # --- Case 3: Internal Transfer ---
    elif doc.payment_type == "Internal Transfer":
        append_gl_entry(doc.paid_from, 0, doc.paid_amount) # دائن (خارج من)
        append_gl_entry(doc.paid_to, doc.paid_amount, 0)   # مدين (داخل إلى)

    # تنفيذ الإدخال
    for entry in gl_entries:
        gl = frappe.new_doc("GL Entry")
        gl.update(entry)
        gl.insert(ignore_permissions=True)
        gl.submit()