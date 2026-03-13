import frappe
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from frappe import _
from frappe.utils import flt


def _build_gl_dict(doc, args):
	"""
	Helper to build a GL Entry dict with all standard fields required by make_gl_entries.
	This replaces doc.get_gl_dict() which is only available on ERPNext AccountsController
	subclasses, not on plain Document subclasses.
	"""
	gl = frappe._dict(
		{
			"doctype": "GL Entry",
			"posting_date": doc.posting_date,
			"voucher_type": doc.doctype,
			"voucher_no": doc.name,
			"company": doc.company,
			"is_opening": "No",
			"is_advance": "No",
			"remarks": doc.remarks or _("Voucher Direct GL Entry"),
			"debit_in_account_currency": 0,
			"credit_in_account_currency": 0,
		}
	)
	gl.update(args)

	# Keep debit/credit_in_account_currency in sync when not explicitly set
	if not gl.get("debit_in_account_currency"):
		gl["debit_in_account_currency"] = gl.get("debit", 0)
	if not gl.get("credit_in_account_currency"):
		gl["credit_in_account_currency"] = gl.get("credit", 0)

	return gl


def on_submit(doc, method=None):
	"""
	Create GL Entries when a Vouchers Entry is submitted.
	Handles both direct account payment and line-item references.
	"""
	gl_entries = []

	# 1. معالجة حساب الدفع (Account Payment) - دعم الموظف كـ Party
	payment_party_type = "Employee" if doc.employee else None
	payment_party = doc.employee if doc.employee else None

	# في حالة الاستلام: الحساب مدين | في حالة الدفع: الحساب دائن
	p_debit = flt(doc.amount_after_tax) if doc.payment_type == "Receive" else 0
	p_credit = flt(doc.amount_after_tax) if doc.payment_type == "Pay" else 0

	if doc.account_payment:
		gl_entries.append(
			_build_gl_dict(
				doc,
				{
					"account": doc.account_payment,
					"party_type": payment_party_type,
					"party": payment_party,
					"debit": p_debit,
					"credit": p_credit,
					"remarks": doc.remarks or _("Voucher Direct GL Entry"),
					"cost_center": doc.cost_center,
				},
			)
		)

	# 2. معالجة أسطر الجدول (References)
	for row in doc.references:
		if not row.account:
			continue

		# أ: إذا كان fixed_asset مفعلاً وهناك صنف ومورد -> إنشاء فاتورة شراء
		if getattr(row, "fixed_asset", 0) and row.item and row.party_type == "Supplier":
			pi_name = make_auto_purchase_invoice(doc, row)

			# الفاتورة أنشأت (مصروف -> مورد)
			# نحن هنا ننشئ قيد السداد (مورد -> بنك) لربطهما معاً
			row_debit = flt(row.amount_after_tax) if doc.payment_type == "Pay" else 0
			row_credit = flt(row.amount_after_tax) if doc.payment_type == "Receive" else 0

			gl_entries.append(
				_build_gl_dict(
					doc,
					{
						"account": row.account,
						"party_type": "Supplier",
						"party": row.party,
						"debit": row_debit,
						"credit": row_credit,
						"against_voucher_type": "Purchase Invoice",
						"against_voucher": pi_name,
						"remarks": f"Settlement for PI: {pi_name} | Item: {row.item}",
						"cost_center": row.cost_center or doc.cost_center,
					},
				)
			)

		# ب: قيد حساب مباشر (بدون fixed_asset)
		else:
			row_debit = flt(row.amount_after_tax) if doc.payment_type == "Pay" else 0
			row_credit = flt(row.amount_after_tax) if doc.payment_type == "Receive" else 0

			gl_entries.append(
				_build_gl_dict(
					doc,
					{
						"account": row.account,
						"party_type": row.party_type,
						"party": row.party,
						"debit": row_debit,
						"credit": row_credit,
						"remarks": row.user_remark or doc.remarks,
						"cost_center": row.cost_center or doc.cost_center,
					},
				)
			)

	# ترحيل القيود للأستاذ العام مباشرة (منع التكرار بـ allow_negative_stock=False)
	if gl_entries:
		make_gl_entries(gl_entries)


def on_cancel(doc, method=None):
	"""إلغاء قيود الـ GL وعكس الفواتير المرتبطة"""
	make_reverse_gl_entries(voucher_type=doc.doctype, voucher_no=doc.name)

	# البحث عن الفواتير التي أنشئت بواسطة هذا السند وإلغاؤها
	linked_pi = frappe.get_all(
		"Purchase Invoice", filters={"remarks": ["like", f"%{doc.name}%"], "docstatus": 1}
	)
	for inv in linked_pi:
		pi_doc = frappe.get_doc("Purchase Invoice", inv.name)
		pi_doc.cancel()


def on_trash(doc, method=None):
	"""منع حذف المستند إذا كانت هناك قيود مرتبطة به"""
	if frappe.db.exists("GL Entry", {"voucher_no": doc.name}):
		frappe.throw(_("Cannot delete {0} as GL Entries exist against it.").format(doc.name))


def make_auto_purchase_invoice(doc, row):
	"""دالة لإنشاء فاتورة شراء تلقائية لعناصر الأصول الثابتة (Fixed Assets)"""
	pi = frappe.new_doc("Purchase Invoice")
	pi.supplier = row.party
	pi.company = doc.company
	pi.posting_date = doc.posting_date
	pi.remarks = f"Auto-generated from {doc.name}"

	# تحديد حساب المصروف من Item Defaults أو من السطر مباشرة
	exp_account = (
		frappe.db.get_value(
			"Item Default",
			{"parent": row.item, "company": doc.company},
			"expense_account",
		)
		or row.account
	)

	pi.append(
		"items",
		{
			"item_code": row.item,
			"qty": flt(getattr(row, "qty", None)) or 1.0,
			"rate": row.amount,  # السعر قبل الضريبة
			"expense_account": exp_account,
			"cost_center": row.cost_center or doc.cost_center,
		},
	)

	if row.taxes:
		pi.taxes_and_charges = row.taxes
		pi.set_taxes()

	# ignore_mandatory لتجاوز قيود الحفظ في التطبيقات الجانبية مثل supplier_name_in_arabic
	pi.flags.ignore_mandatory = True
	pi.insert(ignore_permissions=True)
	pi.submit()
	return pi.name
