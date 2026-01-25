frappe.ui.form.on('Vouchers Entry', {
    refresh: function(frm) {
        // إضافة زر لمشاهدة الأستاذ العام مباشرة
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('View Ledger'), function() {
                frappe.set_route("query-report", "General Ledger", {
                    "voucher_no": frm.doc.name,
                    "company": frm.doc.company
                });
            }, __("View"));
        }
    },

    // عند تغيير الموظف، نقوم بفلترة حسابات الدفع لتناسبه إذا لزم الأمر
    employee: function(frm) {
        if (frm.doc.employee) {
            frappe.show_alert({message: __("Employee selected as Party for Payment Account"), indicator: 'info'});
        }
    }
});

frappe.ui.form.on('Voucher Entry Account', {
    item: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item) {
            // إذا اختار صنف، نتأكد أن الطرف مورد
            if (row.party_type !== 'Supplier') {
                frappe.model.set_value(cdt, cdn, 'party_type', 'Supplier');
                frappe.msgprint(__("Items can only be processed for Suppliers. Party Type changed to Supplier."));
            }
            // جلب سعر الصنف تلقائياً (اختياري)
            frappe.db.get_value('Item', row.item, 'standard_rate', (r) => {
                if (r.standard_rate) frappe.model.set_value(cdt, cdn, 'amount', r.standard_rate);
            });
        }
    }
});
