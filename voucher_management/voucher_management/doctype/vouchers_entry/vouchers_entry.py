# Copyright (c) 2025, Amir and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class VouchersEntry(Document):
	def validate(self):
		"""التحقق من صحة البيانات قبل الحفظ"""
		self._validate_accounts()
		self._compute_totals()
		self._fetch_employee_account()

	def _validate_accounts(self):
		"""التأكد من وجود الحسابات المطلوبة"""
		if not self.company:
			frappe.throw(_("Company is required"))

		for row in self.references:
			if not row.account:
				frappe.throw(_("Account is required in row {0}").format(row.idx))

	def _compute_totals(self):
		"""إعادة حساب المجاميع من أسطر الجدول"""
		total = 0.0
		tax = 0.0
		for row in self.references:
			total += flt(row.amount_before_tax) or flt(row.amount)
			tax += flt(row.tax_amount)
		self.total_allocated_amount = total
		self.total_taxes = tax
		self.amount_after_tax = total + tax

	def _fetch_employee_account(self):
		"""جلب حساب الموظف الافتراضي إذا لم يكن محدداً"""
		if self.employee and not self.account_payment:
			emp_account = frappe.db.get_value("Employee", self.employee, "custom_default_employee_account")
			if emp_account:
				self.account_payment = emp_account

	def before_submit(self):
		"""التحقق النهائي قبل الترحيل"""
		if not self.account_payment:
			frappe.throw(_("Payment Account (account_payment) is required before submitting"))

		total_debit = flt(self.amount_after_tax)
		total_credit = sum(flt(r.amount_after_tax) for r in self.references if r.account)

		# التأكد من توازن القيد (في حالة Pay: المصروفات == المدفوع)
		if self.payment_type in ("Pay", "Receive") and abs(total_debit - total_credit) > 0.01:
			frappe.throw(
				_(
					"Voucher is not balanced. Payment amount {0} does not match "
					"references total {1}. Difference: {2}"
				).format(total_debit, total_credit, abs(total_debit - total_credit))
			)
