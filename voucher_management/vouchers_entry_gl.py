import frappe
from frappe.utils import flt, _
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries

def on_submit(doc, method=None):
    gl_entries = []
    
    # 1. تحديد الطرف والحساب الخاص بجهة الدفع/الاستلام الرئيسية
    payment_party_type = "Employee" if doc.employee else None
    payment_party = doc.employee if doc.employee else None

    # حساب القيمة الكلية للطرف الرئيسي
    # في الاستلام: البنك مدين (+) | في الدفع: البنك دائن (-)
    payment_debit = flt(doc.amount_after_tax) if doc.payment_type == "Receive" else 0
    payment_credit = flt(doc.amount_after_tax) if doc.payment_type == "Pay" else 0

    gl_entries.append(doc.get_gl_dict({
        "account": doc.account_payment,
        "party_type": payment_party_type,
        "party": payment_party,
        "debit": payment_debit,
        "credit": payment_credit,
        "remarks": doc.remarks or _("Voucher Payment Transaction"),
        "cost_center": doc.cost_center
    }))

    # 2. معالجة الأسطر (References)
    for row in doc.references:
        # الحالة الأولى: وجود صنف (Item) مع مورد -> إنشاء فاتورة شراء
        if row.item and row.party_type == "Supplier":
            pi_name = make_auto_purchase_invoice(doc, row)
            
            # هنا الفاتورة أنشأت قيد (مصروف -> مورد)
            # السند يجب أن ينشئ قيد السداد (مورد -> بنك) لإقفال حساب المورد
            row_debit = flt(row.amount_after_tax) if doc.payment_type == "Pay" else 0
            row_credit = flt(row.amount_after_tax) if doc.payment_type == "Receive" else 0
            
            gl_entries.append(doc.get_gl_dict({
                "account": row.account, # حساب المورد المرتبط
                "party_type": "Supplier",
                "party": row.party,
                "debit": row_debit,
                "credit": row_credit,
                "remarks": f"Settlement for PI: {pi_name} | Item: {row.item}",
                "against_voucher_type": "Purchase Invoice",
                "against_voucher": pi_name,
                "cost_center": row.cost_center or doc.cost_center
            }))
            
            # تحديث السطر باسم الفاتورة للرجوع إليها
            frappe.db.set_value("Voucher Entry Account", row.name, "user_remark", f"Linked PI: {pi_name}")

        # الحالة الثانية: قيد حساب مباشر (بدون صنف)
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

    # ترحيل جميع القيود للأستاذ العام
    if gl_entries:
        make_gl_entries(gl_entries)

def on_cancel(doc, method=None):
    """إلغاء قيود الـ GL وعكس الفواتير"""
    make_reverse_gl_entries(voucher_type=doc.doctype, voucher_no=doc.name)
    
    # البحث عن فواتير الشراء المرتبطة وإلغاؤها
    linked_invoices = frappe.get_all("Purchase Invoice", 
        filters={"remarks": ["like", f"%{doc.name}%"], "docstatus": 1})
    
    for inv in linked_invoices:
        pi = frappe.get_doc("Purchase Invoice", inv.name)
        pi.cancel()
    
    frappe.msgprint(_("General Ledger reversed and linked Purchase Invoices cancelled."))

def make_auto_purchase_invoice(doc, row):
    """إنشاء فاتورة شراء ذكية"""
    pi = frappe.new_doc("Purchase Invoice")
    pi.supplier = row.party
    pi.company = doc.company
    pi.posting_date = doc.posting_date
    pi.remarks = f"Generated from Voucher: {doc.name}"
    
    # جلب الحساب الخاص بالصنف أو استخدام حساب السطر
    expense_account = frappe.db.get_value("Item", row.item, "item_group_account") or row.account

    pi.append("items", {
        "item_code": row.item,
        "qty": flt(row.qty) or 1.0,
        "rate": row.amount, # السعر قبل الضريبة
        "expense_account": expense_account,
        "cost_center": row.cost_center or doc.cost_center
    })
    
    # إضافة الضرائب من القالب المختار في السطر
    if row.taxes:
        pi.taxes_and_charges = row.taxes
        pi.set_taxes()

    # تجاوز أخطاء التطبيقات الأخرى (مثل الحقول المفقودة في الترجمة)
    pi.flags.ignore_mandatory = True 
    pi.insert(ignore_permissions=True)
    pi.submit()
    return pi.name
